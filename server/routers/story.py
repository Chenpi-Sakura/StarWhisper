"""POST /api/story（spec §3.3 + §5.4 + §16.4）与 POST /api/story/stream（AgentArts v0.3）。

- 10 分钟 LRU（cachetools.TTLCache），**不缓存 degraded:true**
- Cache-Bust: 1 header 或 cacheBust=true body 字段绕过缓存
- 未知星座 → 404 CONSTELLATION_NOT_FOUND（spec §3.3）
- 风格非法 → 400 INVALID_STYLE
- DisabledProvider / AI 失败 → fallback preset（`degraded:true`，**非 503**）
- 503 STORY_DISABLED 仅当 preset 文件缺失时
- `/api/story/stream`：SSE 字符级流（event:title / char / done / error / reset）。
  字符级协议：title 事件发一次（首 \n 触发）；之后逐字 yield event:char，
  AI 推多快前端就显示多快（不做人为节流）。\n 自然换行、\n\n 自然段间距。
  降级前先发 `reset` 事件（P0-3：前端清空半截内容，避免拼接）。
- P1-7 端到端总时长预算（STORY_TOTAL_TIMEOUT）/ P1-8 断连取消 AI 调用 /
  P1-9 故障熔断 / P1-10 按 IP 限流 / P1-11 缓存命中 latency_ms 归零
- P2-12 请求可显式携带 tradition（缺省仍按 abbr 跨 tradition 首命中向后兼容）；
  缓存 key 升级为 (tradition, abbr, style) 三维
- P2-13 prompt 星点按星等截断（STORY_PROMPT_MAX_STARS）+ 数据 .get() 防护
- P2-14 AI 输出剥离 Markdown 标记（非流式 / parse_story_text 路径）；流式字符级
  信任 prompt 约束（输出仅含标题+段落正文，不要 JSON / Markdown 标记），按原样透传
- P2-16 流式字符级：缓存命中与降级 preset 路径也走 char 事件，前端单套渲染逻辑
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
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
    STORY_PROMPT_MAX_STARS,
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

logger = logging.getLogger(__name__)

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


def _cache_key(tradition: str, abbr: str, style: str) -> tuple[str, str, str]:
    """P2-12：缓存 key 升级为 (tradition, abbr, style) 三维。"""
    return (tradition, abbr, style)


def _find_constellation(abbr: str, tradition: str | None = None) -> dict | None:
    """查找星座条目（含 tradition 字段），或 None。

    P2-12：显式传 tradition 时只在该 tradition 内查（不再隐式首命中）；
    未传时保持向后兼容——跨 tradition 按 key 字母序取首个命中。
    """
    if tradition:
        return get_constellation(tradition, abbr)
    for t in list_traditions():
        entry = get_constellation(t["key"], abbr)
        if entry is not None:
            return entry
    return None


def _resolve_tradition(abbr: str, requested: str | None) -> str:
    """解析缓存/降级要用的 tradition key（P2-12）。

    请求带 tradition → 直接用（调用方已校验命中）；否则回退跨 tradition
    首命中结果的 tradition 字段。找不到（_check_request 已拦，这里兜底）→ "western"。
    """
    if requested:
        return requested.lower()
    entry = _find_constellation(abbr)
    return (entry or {}).get("tradition", "western")


def _cache_get(tradition: str, abbr: str, style: str) -> dict | None:
    with _CACHE_LOCK:
        return _STORY_CACHE.get(_cache_key(tradition, abbr, style))


def _cache_put(tradition: str, abbr: str, style: str, payload: dict) -> None:
    """degraded:true 不写缓存（spec §5.4 / §16.4：失败一次别让整场都是离线故事）。"""
    if payload.get("degraded"):
        return
    with _CACHE_LOCK:
        _STORY_CACHE[_cache_key(tradition, abbr, style)] = payload


class StoryRequest(BaseModel):
    """请求体：星座缩写 + 视角 + 语言 + 可选 cacheBust / tradition。"""

    model_config = ConfigDict(populate_by_name=True)

    abbr: str = Field(..., description="星座缩写（如 ori）")
    style: str = Field(..., description="视角 myth | science")
    lang: str = Field("zh", description="语言代码，暂固定 zh")
    cacheBust: bool = Field(False, alias="cacheBust")
    tradition: str | None = Field(
        None,
        description="P2-12：tradition key（western / chinese）；缺省时按 abbr 跨 tradition 首命中",
    )


_TITLE_PREFIXES = ("标题：", "标题:", "Title:", "title:", "# ")

# P2-14：AI 输出常见 Markdown 标记的清洗规则
_MD_CODE = re.compile(r"`([^`]*)`")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_MD_HEADING = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_BULLET = re.compile(r"^[-*•]\s+", re.MULTILINE)
_MD_NUM_LIST = re.compile(r"^\d+[.、）)]\s*", re.MULTILINE)


def clean_markdown(text: str) -> str:
    """剥离 LLM 输出中常见 Markdown 标记（P2-14），返回清洗后的纯文本。

    处理：行内代码反引号、**加粗** / *斜体*、行首 # 标题、行首 -/*• 列表符、
    行首 1. / 一、编号。幂等：纯文本原样返回。
    """
    s = text or ""
    s = _MD_CODE.sub(r"\1", s)
    s = _MD_BOLD.sub(r"\1", s)
    s = _MD_ITALIC.sub(r"\1", s)
    s = _MD_HEADING.sub("", s)
    s = _MD_BULLET.sub("", s)
    s = _MD_NUM_LIST.sub("", s)
    return s.strip()


def _strip_title_prefix(line: str) -> str:
    """剥掉「标题： / Title: / # 」等标题前缀（spec §5.2 约定）。"""
    line = line.strip()
    for prefix in _TITLE_PREFIXES:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return line


def parse_story_text(text: str, fallback_title: str) -> tuple[str, list[str]]:
    """解析 LLM 输出全文（P0-2：流式/非流式共用同一套算法，spec §646）。

    - **首行为 title**（先清洗 Markdown 再剥前缀，避免「**标题：猎户**」漏剥），
      其余按 \\n\\n 切 paragraphs 并逐段清洗 Markdown（P2-14）
    - 只有单行没有正文 → 回退 fallback_title + 整段为单 paragraph
    - 空文本 → (fallback_title, [])
    """
    text = (text or "").strip()
    if not text:
        return fallback_title, []
    first_line, _, rest = text.partition("\n")
    # P2-14：清洗先行，再剥前缀——处理 AI 输出「**标题：猎户**」这类被 Markdown 包裹的标题
    title = _strip_title_prefix(clean_markdown(first_line))
    body = [clean_markdown(p) for p in rest.split("\n\n") if p.strip()]
    body = [p for p in body if p]
    if not body:
        return fallback_title, [clean_markdown(text)]
    return title or fallback_title, body


def _classify_reason(exc: Exception) -> str:
    """根据异常 message 推断 degraded_reason。"""
    msg = str(exc).lower()
    if "timeout" in msg or "timed out" in msg:
        return "AI_PROVIDER_TIMEOUT"
    if "parse" in msg or "json" in msg:
        return "AI_PROVIDER_PARSE_ERROR"
    return "AI_PROVIDER_5XX"


def _check_request(body: StoryRequest) -> tuple[str, str, str | None]:
    """校验 style / abbr / tradition；合法则返回 (abbr, style, tradition | None)。"""
    if body.style not in _STYLES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_STYLE",
                "message": f"style 必须是 {sorted(_STYLES)} 之一",
            },
        )
    if body.tradition:
        trad_keys = {t["key"] for t in list_traditions()}
        if body.tradition.lower() not in trad_keys:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_TRADITION",
                    "message": f"tradition 必须是 {sorted(trad_keys)} 之一",
                },
            )
        if get_constellation(body.tradition.lower(), body.abbr) is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "CONSTELLATION_NOT_FOUND",
                    "message": "未收录此星座",
                },
            )
        return body.abbr, body.style, body.tradition.lower()
    # 未带 tradition：跨 tradition 收集 abbr（向后兼容，首命中）
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
    return body.abbr, body.style, None


def _build_prompt(abbr: str, style: str, tradition: str | None = None) -> tuple[str, str, str]:
    """构造 system/user prompt + 兜底标题。

    P2-12：显式 tradition 优先；P2-13：星点按星等取最亮的前
    STORY_PROMPT_MAX_STARS 颗，字段全部 .get() 访问（缺键跳过不抛错）。
    """
    constellation = _find_constellation(abbr, tradition)
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

    # P2-13：先做字段防护再按星等排序截断，防止 token 膨胀（轩辕 70 星）
    star_entries: list[tuple[float, str]] = []
    for s in constellation.get("stars", {}).values():
        name = s.get("name") or s.get("bayer")
        if not name:
            continue
        mag = s.get("magnitude")
        mag_val = mag if isinstance(mag, (int, float)) else 99.0
        star_entries.append((float(mag_val), name))
    star_entries.sort(key=lambda x: x[0])
    primary_stars = "\n".join(
        f"- {name}，星等 {mag:g}" if mag < 99 else f"- {name}"
        for mag, name in star_entries[:STORY_PROMPT_MAX_STARS]
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
    tradition: str | None = None,
) -> dict:
    """生成/取故事完整 payload（缓存命中 / AI / preset 降级）。

    P2-12：tradition 先解析为具体 key 再参与缓存 key；degraded 不写缓存。
    """
    trad = _resolve_tradition(abbr, tradition)

    # 查缓存（不缓存 degraded:true；bust 跳过）
    if not bust:
        cached = _cache_get(trad, abbr, style)
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
        return _preset_payload(abbr, style, "AI_CIRCUIT_OPEN", tradition=trad)

    system_prompt, user_prompt, fallback_title = _build_prompt(abbr, style, trad)

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

        # P2-14：字数/段落数软校验——只记日志，不阻断（输出异常宽进严出）
        total_chars = sum(len(p) for p in body_paragraphs)
        if len(body_paragraphs) < 2 or total_chars < 150:
            logger.warning(
                "story output short: abbr=%s style=%s paras=%d chars=%d",
                abbr, style, len(body_paragraphs), total_chars,
            )

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
        _cache_put(trad, abbr, style, payload)
        return payload

    except Exception as exc:
        _BREAKER.record_failure()
        return _preset_payload(
            abbr, style, _classify_reason(exc), elapsed=time.time() - start,
            tradition=trad,
        )


def _preset_payload(
    abbr: str,
    style: str,
    reason: str,
    *,
    elapsed: float = 0.0,
    tradition: str | None = None,
) -> dict:
    """构造 preset 降级 payload；preset 缺失时抛 503 STORY_DISABLED。"""
    preset = get_preset(abbr, style, tradition)
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
    abbr, style, tradition = _check_request(body)
    bust = bool(body.cacheBust) or cache_bust == 1
    return await _resolve_payload(abbr, style, bust, tradition)


def _sse(event: str, data: object) -> str:
    """封装一条 SSE 帧。data 为 JSON 字符串。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _preset_chars_sse(
    abbr: str, style: str, reason: str, *, elapsed: float = 0.0,
    tradition: str | None = None,
) -> str:
    """P2-16：降级事件的完整 SSE 帧串（title + char ×N + done）。

    字符级协议：title 一次，body 按段落拆 char，段落间两个 \\n 字符。
    调用方须先 yield `reset` 事件，前端收到后清空已渲染的半截 AI 内容，
    避免半截 AI 字符与完整 preset 字符首尾拼接。
    """
    preset = get_preset(abbr, style, tradition)
    if preset is None:
        return _sse("error", {
            "code": "STORY_DISABLED",
            "message": "服务端未配置 AI 且预设缺失",
        })
    frames = [_sse("title", {"title": preset["title"]})]
    for i, para in enumerate(preset["paragraphs"]):
        if i > 0:
            frames.append(_sse("char", {"char": "\n"}))
            frames.append(_sse("char", {"char": "\n"}))
        for ch in para:
            frames.append(_sse("char", {"char": ch}))
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


# 向后兼容旧测试 — _preset_sse 已重命名为 _preset_chars_sse（P2-16）
_preset_sse = _preset_chars_sse


@router.post("/stream")
async def post_story_stream(
    body: StoryRequest,
    request: Request,
    cache_bust: int = Header(0, alias="Cache-Bust"),
):
    """SSE 字符级真流式（P2-16）。

    事件流：title → char ×N → done。
    - title：AI 输出首个 \\n 时一次性发出（先 clean_markdown 再剥前缀，与
      parse_story_text 算法对齐，避免流式/非流式产生不同结果）。
    - char：title 之后每个字符（含 \\n）逐字 yield event:char，
      AI 推多快前端就显示多快（不人为节流）。\\n 自然换行、\\n\\n 自然段间距。
    - done：缓存命中 / 成功生成后写完 cache 后 yield。
    - reset + char ×N + done：失败 / 熔断时降级路径。
    - 缓存命中与降级 preset 也走 char 事件，前端一套渲染逻辑。

    桥接：chat_stream 同步 on_delta → asyncio.Queue → async generator。
    """
    _check_rate_limit(request)  # P1-10
    abbr, style, requested_tradition = _check_request(body)
    bust = bool(body.cacheBust) or cache_bust == 1

    async def _events() -> AsyncIterator[str]:
        # P2-12：先解析 tradition（显式 > 首命中），缓存 key 三维
        trad = _resolve_tradition(abbr, requested_tradition)
        # 缓存命中：一次性 yield（缓存本来就是同步数据）
        if not bust:
            cached = _cache_get(trad, abbr, style)
            if cached is not None:
                yield _sse("title", {"title": cached["title"]})
                for i, para in enumerate(cached["paragraphs"]):
                    if i > 0:
                        yield _sse("char", {"char": "\n"})
                        yield _sse("char", {"char": "\n"})
                    for ch in para:
                        yield _sse("char", {"char": ch})
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
            yield _preset_chars_sse(abbr, style, "AI_CIRCUIT_OPEN", tradition=trad)
            return

        system_prompt, user_prompt, fallback_title = _build_prompt(abbr, style, trad)
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

        # P2-16：字符级状态机
        # - title_buf：收集首段首行（遇到首个 \n 才发 title）
        # - body_text：title 之后逐字符累积（用于成功后按 \n\n 切段落写缓存）
        title_emitted = False
        title = ""
        title_buf = ""
        body_text = ""

        def _consume(chunk: str) -> list[str]:
            """消费一段 AI delta，产出 SSE 帧列表。同步函数便于 hot path 复用。

            title 未发时：累积 title_buf；遇到首个 \\n 才切出 title + 进入 body 流。
            title 已发时：把 chunk 每个字符逐字 yield event:char。
            """
            nonlocal title_emitted, title, title_buf, body_text
            frames: list[str] = []
            if not title_emitted:
                title_buf += chunk
                if "\n" in title_buf:
                    nl_idx = title_buf.index("\n")
                    title_line = title_buf[:nl_idx]
                    rest = title_buf[nl_idx + 1:]
                    title = (
                        _strip_title_prefix(clean_markdown(title_line))
                        or fallback_title
                    )
                    frames.append(_sse("title", {"title": title}))
                    title_emitted = True
                    title_buf = ""
                    for ch in rest:
                        frames.append(_sse("char", {"char": ch}))
                        body_text += ch
                # else: 还没遇到 \n，继续累积
            else:
                for ch in chunk:
                    frames.append(_sse("char", {"char": ch}))
                    body_text += ch
            return frames

        def _finalize() -> list[str]:
            """流结束时的 flush。

            仅当 title_buf 有实际内容但始终没遇到 \\n（单行 AI 输出）才兜底发
            title + body；空缓冲交由主流程失败检查接管（reset + preset）。
            正常情况最后一个 delta 已经把字符 yield 完了，这里不做任何事。
            """
            nonlocal title_emitted, title, title_buf, body_text
            frames: list[str] = []
            if not title_emitted and title_buf.strip():
                # 单行 AI 输出：fallback_title + 整段作为 body
                # （对齐 parse_story_text「单行无正文」语义）
                title = fallback_title
                frames.append(_sse("title", {"title": title}))
                title_emitted = True
                body_text = clean_markdown(title_buf)
                title_buf = ""
                for ch in body_text:
                    frames.append(_sse("char", {"char": ch}))
            return frames

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
                    for frame in _consume(str(payload)):
                        yield frame
                elif kind == "end":
                    for frame in _finalize():
                        yield frame
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
        if timed_out or exc is not None or not title_emitted:
            if timed_out:
                reason = "AI_PROVIDER_TIMEOUT"
            else:
                reason = _classify_reason(exc) if isinstance(exc, Exception) else "AI_PROVIDER_5XX"
            _BREAKER.record_failure()
            yield _sse("reset", {})  # P0-3
            yield _preset_chars_sse(abbr, style, reason, elapsed=time.time() - start,
                                    tradition=trad)
            return

        # 成功路径：把 body_text 按 \n\n 切段落，组装 payload 写缓存
        _BREAKER.record_success()
        body_paragraphs = [p for p in body_text.split("\n\n") if p.strip()]
        # P2-14：字数/段落数软校验——只记日志，不阻断
        total_chars = sum(len(p) for p in body_paragraphs)
        if len(body_paragraphs) < 2 or total_chars < 150:
            logger.warning(
                "story stream output short: abbr=%s style=%s paras=%d chars=%d",
                abbr, style, len(body_paragraphs), total_chars,
            )
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
        _cache_put(trad, abbr, style, payload)
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