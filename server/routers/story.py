"""POST /api/story（spec §3.3 + §5.4 + §16.4）与 POST /api/story/stream（AgentArts v0.3）。

- 10 分钟 LRU（cachetools.TTLCache），**不缓存 degraded:true**
- Cache-Bust: 1 header 或 cacheBust=true body 字段绕过缓存
- 未知星座 → 404 CONSTELLATION_NOT_FOUND（spec §3.3）
- 风格非法 → 400 INVALID_STYLE
- DisabledProvider / AI 失败 → fallback preset（`degraded:true`，**非 503**）
- 503 STORY_DISABLED 仅当 preset 文件缺失时
- `/api/story/stream`：SSE 打字机流（event:title / paragraph / done / error）；
  降级前先发 `reset` 事件（P0-3：前端清空半截内容，避免拼接）
- P1-7 端到端总时长预算（STORY_TOTAL_TIMEOUT）/ P1-8 断连取消 AI 调用 /
  P1-9 故障熔断 / P1-10 按 IP 限流 / P1-11 缓存命中 latency_ms 归零
"""
from __future__ import annotations

import asyncio
import json
import time
from threading import Lock
from typing import AsyncIterator

from cachetools import TTLCache
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from config import (
    AI_MODEL,
    STORY_CB_COOLDOWN,
    STORY_CB_THRESHOLD,
    STORY_RATE_LIMIT,
    STORY_RATE_WINDOW,
    STORY_TOTAL_TIMEOUT,
)
from services.ai_provider import (
    STYLE_ZH,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    make_provider,
    myth_pool_rule,
)
from services.traditions import get_constellation, list_traditions, list_constellations
from services.story_fallback import get_preset


router = APIRouter(prefix="/api/story", tags=["story"])

_STYLES = {"myth", "science"}
_STORY_CACHE: TTLCache = TTLCache(maxsize=96, ttl=600)  # 10 min
_CACHE_LOCK = Lock()


class _CircuitBreaker:
    """P1-9：AI 故障熔断（固定窗口冷却）。

    连续失败 STORY_CB_THRESHOLD 次后进入 STORY_CB_COOLDOWN 秒冷却期；
    冷却期内 allow() 返回 False（直接走 preset），冷却结束自动半开重试。
    """

    def __init__(self, threshold: int, cooldown: float) -> None:
        self._threshold = max(1, threshold)
        self._cooldown = cooldown
        self._lock = Lock()
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def allow(self) -> bool:
        """熔断开启且仍在冷却期内 → False（跳过 AI 直走 preset）。"""
        with self._lock:
            if self._opened_at is None:
                return True
            if time.time() - self._opened_at >= self._cooldown:
                # 冷却结束：半开，放行一次尝试
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._threshold:
                self._opened_at = time.time()

    def reset(self) -> None:
        """恢复初始态（测试夹具用）。"""
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None


_BREAKER = _CircuitBreaker(STORY_CB_THRESHOLD, STORY_CB_COOLDOWN)

# P1-10：按客户端 IP 的固定窗口限流。STORY_RATE_LIMIT<=0 关闭。
_RATE_BUCKETS: dict[str, list[float]] = {}
_RATE_LOCK = Lock()


def _check_rate_limit(request: Request) -> None:
    """超限抛 429 RATE_LIMITED；窗口过期的时间戳惰性清理。"""
    if STORY_RATE_LIMIT <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE_BUCKETS.get(ip, []) if now - t < STORY_RATE_WINDOW]
        if len(hits) >= STORY_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "RATE_LIMITED",
                    "message": "请求过于频繁，请稍后再试",
                },
            )
        hits.append(now)
        _RATE_BUCKETS[ip] = hits
        # 防桶泄漏：桶数超阈值时顺手清掉全过期 ip（低频执行）
        if len(_RATE_BUCKETS) > 1024:
            for k in [k for k, v in _RATE_BUCKETS.items() if not v or now - v[-1] >= STORY_RATE_WINDOW]:
                _RATE_BUCKETS.pop(k, None)


def _cache_key(abbr: str, style: str) -> tuple[str, str]:
    return (abbr, style)


def _find_constellation(abbr: str) -> dict | None:
    """跨 tradition 查找 abbr（保持 story 端点向后兼容）。

    返回第一个命中的 entry（含 tradition 字段），或 None。
    MVP 阶段 abbr 在多 tradition 中重复时选择 traditions 中字母序靠前的。
    """
    for t in list_traditions():
        entry = get_constellation(t["key"], abbr)
        if entry is not None:
            return entry
    return None


def _cache_get(abbr: str, style: str) -> dict | None:
    with _CACHE_LOCK:
        return _STORY_CACHE.get(_cache_key(abbr, style))


def _cache_put(abbr: str, style: str, payload: dict) -> None:
    """degraded:true 不写缓存（spec §5.4 / §16.4：失败一次别让整场都是离线故事）。"""
    if payload.get("degraded"):
        return
    with _CACHE_LOCK:
        _STORY_CACHE[_cache_key(abbr, style)] = payload


class StoryRequest(BaseModel):
    """请求体：星座缩写 + 视角 + 语言 + 可选 cacheBust。"""

    model_config = ConfigDict(populate_by_name=True)

    abbr: str = Field(..., description="星座缩写（如 ori）")
    style: str = Field(..., description="视角 myth | science")
    lang: str = Field("zh", description="语言代码，暂固定 zh")
    cacheBust: bool = Field(False, alias="cacheBust")


_TITLE_PREFIXES = ("标题：", "标题:", "Title:", "title:", "# ")


def _strip_title_prefix(line: str) -> str:
    """剥掉「标题： / Title: / # 」等标题前缀（spec §5.2 约定）。"""
    line = line.strip()
    for prefix in _TITLE_PREFIXES:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return line


def parse_story_text(text: str, fallback_title: str) -> tuple[str, list[str]]:
    """解析 LLM 输出全文（P0-2：流式/非流式共用同一套算法，spec §646）。

    - **首行为 title**（剥前缀），其余按 \\n\\n 切 paragraphs
    - 只有单行没有正文 → 回退 fallback_title + 整段为单 paragraph
    - 空文本 → (fallback_title, [])
    """
    text = (text or "").strip()
    if not text:
        return fallback_title, []
    first_line, _, rest = text.partition("\n")
    title = _strip_title_prefix(first_line)
    body = [p.strip() for p in rest.split("\n\n") if p.strip()]
    if not body:
        return fallback_title, [text]
    return title or fallback_title, body


def _classify_reason(exc: Exception) -> str:
    """根据异常 message 推断 degraded_reason。"""
    msg = str(exc).lower()
    if "timeout" in msg or "timed out" in msg:
        return "AI_PROVIDER_TIMEOUT"
    if "parse" in msg or "json" in msg:
        return "AI_PROVIDER_PARSE_ERROR"
    return "AI_PROVIDER_5XX"


def _check_request(body: StoryRequest) -> tuple[str, str]:
    """校验 style / abbr；合法则返回 (abbr, style)。"""
    if body.style not in _STYLES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_STYLE",
                "message": f"style 必须是 {sorted(_STYLES)} 之一",
            },
        )
    # 跨 tradition 收集 abbr（保持向后兼容，不需客户端传 tradition）
    valid_abbrs = {
        c["abbr"]
        for t in list_traditions()
        for c in list_constellations(t["key"])
    }
    if body.abbr not in valid_abbrs:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "CONSTELLATION_NOT_FOUND",
                "message": "未收录此星座",
            },
        )
    return body.abbr, body.style


def _build_prompt(abbr: str, style: str) -> tuple[str, str, str]:
    """构造 system/user prompt + 兜底标题。"""
    constellation = _find_constellation(abbr)
    if constellation is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "CONSTELLATION_NOT_FOUND",
                "message": "未收录此星座",
            },
        )
    constellation_zh = constellation.get("name", abbr)
    latin = constellation.get("latin", "")
    style_zh = STYLE_ZH.get(style, style)
    tradition = constellation.get("tradition", "western")
    primary_stars = "\n".join(
        f"- {s['bayer']} {s['name']}，星等 {s['magnitude']}"
        for s in constellation.get("stars", {}).values()
    ) or "（无）"

    user_prompt = USER_TEMPLATE.format(
        constellation_zh=constellation_zh,
        latin=latin,
        style_zh=style_zh,
        primary_stars=primary_stars,
    )
    system_prompt = SYSTEM_PROMPT.format(
        style_zh=style_zh,
        constellation_zh=constellation_zh,
        latin=latin,
        myth_pool_rule=myth_pool_rule(tradition),
    )
    fallback_title = f"{constellation_zh}的故事"
    return system_prompt, user_prompt, fallback_title


async def _resolve_payload(
    abbr: str,
    style: str,
    bust: bool,
) -> dict:
    """生成/取故事完整 payload（缓存命中 / AI / preset 降级）。

    返回字段与既有 `POST /api/story` 一致；degraded 不写缓存。
    """
    # 查缓存（不缓存 degraded:true；bust 跳过）
    if not bust:
        cached = _cache_get(abbr, style)
        if cached is not None:
            # P1-11：latency_ms 为本次命中耗时（≈0），首次生成耗时挪到 origin_latency_ms
            return {
                **cached,
                "cached": True,
                "latency_ms": 0,
                "origin_latency_ms": cached.get("latency_ms", 0),
            }

    # P1-9：熔断开启（冷却期内）→ 直接走 preset，不让请求干等超时
    if not _BREAKER.allow():
        return _preset_payload(abbr, style, "AI_CIRCUIT_OPEN")

    system_prompt, user_prompt, fallback_title = _build_prompt(abbr, style)

    start = time.time()
    provider = make_provider()
    try:
        # P1-7：总时长预算（区别于 httpx 每 chunk 读超时）
        text = await asyncio.wait_for(
            provider.chat(system_prompt, user_prompt, timeout=30.0),
            timeout=STORY_TOTAL_TIMEOUT,
        )
        title, body_paragraphs = parse_story_text(text, fallback_title)
        if not body_paragraphs:
            raise RuntimeError("AI_PROVIDER_PARSE_ERROR: empty paragraphs")

        _BREAKER.record_success()
        payload = {
            "ok": True,
            "abbr": abbr,
            "style": style,
            "title": title,
            "paragraphs": body_paragraphs,
            "provider": provider.name,
            "model": AI_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "cached": False,
            "degraded": False,
        }
        _cache_put(abbr, style, payload)
        return payload

    except Exception as exc:
        _BREAKER.record_failure()
        return _preset_payload(
            abbr, style, _classify_reason(exc), elapsed=time.time() - start
        )


def _preset_payload(
    abbr: str,
    style: str,
    reason: str,
    *,
    elapsed: float = 0.0,
) -> dict:
    """构造 preset 降级 payload；preset 缺失时抛 503 STORY_DISABLED。"""
    preset = get_preset(abbr, style)
    if preset is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "STORY_DISABLED",
                "message": "服务端未配置 AI 且预设缺失",
            },
        )
    return {
        "ok": True,
        "abbr": abbr,
        "style": style,
        "title": preset["title"],
        "paragraphs": preset["paragraphs"],
        "provider": "fallback",
        "model": "preset",
        "latency_ms": int(elapsed * 1000),
        "cached": False,
        "degraded": True,
        "degraded_reason": reason,
    }


@router.post("")
async def post_story(
    body: StoryRequest,
    request: Request,
    cache_bust: int = Header(0, alias="Cache-Bust"),
):
    _check_rate_limit(request)  # P1-10
    abbr, style = _check_request(body)
    bust = bool(body.cacheBust) or cache_bust == 1
    return await _resolve_payload(abbr, style, bust)


def _sse(event: str, data: object) -> str:
    """封装一条 SSE 帧。data 为 JSON 字符串。"""
    import json as _json

    return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"


def _preset_sse(abbr: str, style: str, reason: str, *, elapsed: float = 0.0) -> str:
    """P0-3：降级事件的完整 SSE 帧串（title + paragraphs + done）。

    调用方须先 yield `reset` 事件，前端收到后清空已渲染的半截 AI 内容，
    避免半截 AI 段落与完整 preset 段落首尾拼接。
    """
    preset = get_preset(abbr, style)
    if preset is None:
        return _sse("error", {
            "code": "STORY_DISABLED",
            "message": "服务端未配置 AI 且预设缺失",
        })
    frames = [_sse("title", {"title": preset["title"]})]
    for i, para in enumerate(preset["paragraphs"]):
        frames.append(_sse("paragraph", {"index": i, "text": para}))
    frames.append(_sse("done", {
        "ok": True,
        "abbr": abbr,
        "style": style,
        "provider": "fallback",
        "model": "preset",
        "latency_ms": int(elapsed * 1000),
        "cached": False,
        "degraded": True,
        "degraded_reason": reason,
    }))
    return "".join(frames)


@router.post("/stream")
async def post_story_stream(
    body: StoryRequest,
    request: Request,
    cache_bust: int = Header(0, alias="Cache-Bust"),
):
    """SSE 真流式（spec §4.6 + AgentArts v0.3）。

    事件流：title → paragraph ×N → done（缓存命中走一次性 yield）。
    降级时先发 `reset`（P0-3：前端清空半截内容）再发 preset 全量。

    缓存未命中时通过 `chat_stream` + queue 桥接实现真流式：
    - chat_stream 是 async generator，逐 message event 调同步 on_delta
    - on_delta 把增量推入 asyncio.Queue
    - async generator 从 queue 消费增量，检测 `\n\n` 边界后 yield 事件
    """
    _check_rate_limit(request)  # P1-10
    abbr, style = _check_request(body)
    bust = bool(body.cacheBust) or cache_bust == 1

    async def _events() -> AsyncIterator[str]:
        # 缓存命中：一次性 yield（缓存本来就是同步数据）
        if not bust:
            cached = _cache_get(abbr, style)
            if cached is not None:
                yield _sse("title", {"title": cached["title"]})
                for i, para in enumerate(cached["paragraphs"]):
                    yield _sse("paragraph", {"index": i, "text": para})
                meta = {k: v for k, v in cached.items() if k not in ("title", "paragraphs")}
                meta["cached"] = True
                # P1-11：命中耗时 ≈0，首次生成耗时挪到 origin_latency_ms
                meta["latency_ms"] = 0
                meta["origin_latency_ms"] = cached.get("latency_ms", 0)
                yield _sse("done", meta)
                return

        # P1-9：熔断开启（冷却期内）→ 直接 preset，不让请求干等超时
        if not _BREAKER.allow():
            yield _sse("reset", {})
            yield _preset_sse(abbr, style, "AI_CIRCUIT_OPEN")
            return

        system_prompt, user_prompt, fallback_title = _build_prompt(abbr, style)
        provider = make_provider()
        start = time.time()
        deadline = start + STORY_TOTAL_TIMEOUT  # P1-7：端到端总预算

        # 桥接：chat_stream 的同步 on_delta → async generator 的 yield。
        q: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        def _on_delta(text: str) -> None:
            q.put_nowait(("delta", text))

        chat_state: dict[str, object] = {"exc": None}

        async def _run_chat() -> None:
            try:
                await provider.chat_stream(
                    system_prompt, user_prompt, _on_delta, timeout=30.0,
                )
            except Exception as exc:  # noqa: BLE001
                chat_state["exc"] = exc
            finally:
                q.put_nowait(("end", None))

        chat_task = asyncio.create_task(_run_chat())

        title_emitted = False
        paragraph_idx = 0
        title = ""
        body_paragraphs: list[str] = []
        buffer = ""

        async def _emit_chunk(chunk: str) -> AsyncIterator[str]:
            """flush 一个完整段；首个段的首行为标题（P0-2 与 parse_story_text 同算法）。"""
            nonlocal title_emitted, title, paragraph_idx
            t = chunk.strip()
            if not t:
                return
            if not title_emitted:
                first_line, _, rest = t.partition("\n")
                title = _strip_title_prefix(first_line) or fallback_title
                yield _sse("title", {"title": title})
                title_emitted = True
                rest_text = rest.strip()
                if rest_text:
                    yield _sse("paragraph", {"index": paragraph_idx, "text": rest_text})
                    body_paragraphs.append(rest_text)
                    paragraph_idx += 1
            else:
                yield _sse("paragraph", {"index": paragraph_idx, "text": t})
                body_paragraphs.append(t)
                paragraph_idx += 1

        timed_out = False
        client_gone = False
        try:
            while True:
                # P1-7：总时长预算——超时按 AI 失败处理（降级 preset）
                remaining = deadline - time.time()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    kind, payload = await asyncio.wait_for(q.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    timed_out = True
                    break
                if kind == "delta":
                    buffer += str(payload)
                    # 检测段落边界 `\n\n`：每次出现就把当前段 flush
                    while "\n\n" in buffer:
                        para, _, buffer = buffer.partition("\n\n")
                        async for frame in _emit_chunk(para):
                            yield frame
                elif kind == "end":
                    # 处理 buffer 末尾未配对的 `\n\n` 段
                    async for frame in _emit_chunk(buffer):
                        yield frame
                    buffer = ""
                    break
        except (asyncio.CancelledError, GeneratorExit):
            # P1-8：客户端断连（生成器被关闭）——取消上游 AI 调用，
            # 避免孤儿调用白烧配额。GeneratorExit 中不能 await，只 cancel。
            client_gone = True
            raise
        finally:
            if client_gone:
                chat_task.cancel()
                # 抑制 "exception was never retrieved" 告警
                chat_task.add_done_callback(
                    lambda t: t.exception() if not t.cancelled() else None
                )
            else:
                if timed_out and not chat_task.done():
                    chat_task.cancel()
                try:
                    await chat_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

        # 失败处理：AI 抛异常 / 总超时 / 无有效输出 → reset + preset 降级
        exc = chat_state["exc"]
        if timed_out or exc is not None or not title_emitted or not body_paragraphs:
            if timed_out:
                reason = "AI_PROVIDER_TIMEOUT"
            else:
                reason = _classify_reason(exc) if isinstance(exc, Exception) else "AI_PROVIDER_5XX"
            _BREAKER.record_failure()
            yield _sse("reset", {})  # P0-3
            yield _preset_sse(abbr, style, reason, elapsed=time.time() - start)
            return

        # 成功路径：写缓存 + yield done
        _BREAKER.record_success()
        payload = {
            "ok": True,
            "abbr": abbr,
            "style": style,
            "title": title,
            "paragraphs": body_paragraphs,
            "provider": provider.name,
            "model": AI_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "cached": False,
            "degraded": False,
        }
        _cache_put(abbr, style, payload)
        meta = {k: v for k, v in payload.items() if k not in ("title", "paragraphs")}
        yield _sse("done", meta)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )