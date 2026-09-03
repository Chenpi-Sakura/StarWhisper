"""POST /api/story（photo-level，spec §3.1）。

- 接受 PhotoStoryRequest（lang / style / cache_bust / context）
- context.constellations 空 → 400 EMPTY_CONTEXT
- SSE 字符级协议沿用 P2-16（event:title 一次 / event:char ×N / event:done）
- 错误统一走 event:error（HTTP 200），无 degraded fallback
- 缓存 key = _signature(context, style, lang)，TTL 10min（TTLCache maxsize=96）
- cache_bust=true 跳过 cache；degraded 不写 cache（spec §5.4 / §16.4）
- P1-7 总时长兜底 / P1-9 熔断 / P1-10 限流
- 系统提示词完全由 AgentArts 后台管；本路由只拼 user_content

注：atlas 路径迁到 routers/atlas_story.py（Task 3），本文件仅 photo-level。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from threading import Lock
from typing import AsyncIterator

import httpx

from cachetools import TTLCache
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from config import STORY_TOTAL_TIMEOUT
from services.ai_provider import make_provider
from services.photo_story import _build_user_content, _signature
from services.story_throttle import check_rate_limit, get_circuit


router = APIRouter(prefix="/api/story", tags=["story"])

logger = logging.getLogger(__name__)

_STYLES = {"myth", "science"}
_STORY_CACHE: TTLCache = TTLCache(maxsize=96, ttl=600)
_CACHE_LOCK = Lock()

# I5：photo-level 独立熔断窗口（与 atlas 解耦）
_CIRCUIT = get_circuit("photo")


# ---------- Schemas ----------


class _PhotoStar(BaseModel):
    bayer: str
    name: str
    name_zh: str | None = None
    magnitude: float
    constellations: list[str] = Field(default_factory=list)


class _PhotoConstellation(BaseModel):
    abbr: str
    tradition: str  # "western" / "chinese"
    name: str
    latin: str | None = None
    confidence: float | None = None
    mansion: str | None = None  # chinese tradition 专用


class _PhotoCenter(BaseModel):
    ra: float
    dec: float


class _PhotoField(BaseModel):
    width_deg: float
    height_deg: float


class _PhotoContext(BaseModel):
    constellations: list[_PhotoConstellation]
    bright_stars: list[_PhotoStar] = Field(default_factory=list)
    center: _PhotoCenter | None = None
    field: _PhotoField | None = None


class PhotoStoryRequest(BaseModel):
    lang: str = "zh"
    style: str
    cache_bust: bool = False
    context: _PhotoContext

    @field_validator("style")
    @classmethod
    def _style_in_set(cls, v: str) -> str:
        if v not in _STYLES:
            raise ValueError(f"INVALID_STYLE: {v}")
        return v

    @field_validator("context")
    @classmethod
    def _context_non_empty(cls, v: _PhotoContext) -> _PhotoContext:
        if not v.constellations:
            raise ValueError("EMPTY_CONTEXT: photo-level 故事需要至少一个命中星座")
        return v


# ---------- SSE helpers ----------


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _provider_name(provider) -> str:
    """取得 provider 的字符串名；AsyncMock（测试夹具）的 .name 是子 Mock，
    不能 JSON 序列化，统一 fallback "ai"（photo-level 由 AgentArts 后台管人设）。"""
    raw = getattr(provider, "name", None)
    return raw if isinstance(raw, str) else "ai"


def _classify_reason(exc: BaseException) -> str:
    """P2 修复：从异常类型 + 文本识别 AI 失败原因（spec §9）。

    优先按异常类型判定，回退到 str(exc).lower() 子串匹配：
    - httpx.TimeoutException → "AI_PROVIDER_TIMEOUT"
    - json.JSONDecodeError    → "AI_PARSE_ERROR"
    - str 包含 "timeout"      → "AI_PROVIDER_TIMEOUT"
    - str 包含 "parse"/"json" → "AI_PARSE_ERROR"
    - 其它                    → "AI_PROVIDER_5XX"
    """
    if isinstance(exc, httpx.TimeoutException):
        return "AI_PROVIDER_TIMEOUT"
    if isinstance(exc, json.JSONDecodeError):
        return "AI_PARSE_ERROR"
    msg = str(exc).lower()
    if "timeout" in msg:
        return "AI_PROVIDER_TIMEOUT"
    if "parse" in msg or "json" in msg:
        return "AI_PARSE_ERROR"
    return "AI_PROVIDER_5XX"


# ---------- Main endpoint ----------


@router.post("")
async def post_story(req: Request, body: PhotoStoryRequest) -> StreamingResponse:
    """photo-level SSE 字符级流（spec §3.1）。

    流程：
      1. 限流（IP 维度，> 限额 → 429）
      2. 缓存命中（cache_bust=false 且 key 命中）→ 重放 title + char ×N + done
      3. 熔断开启（冷却期）→ event:error AI_CIRCUIT_OPEN
      4. AI 不可用（health=False）→ event:error AI_DISABLED
      5. 真流式 chat_stream → event:title 一次 → event:char ×N → event:done
      6. 异常 / 超时 → event:error + 熔断计数
    """
    # 限流
    check_rate_limit(req)

    # 缓存 key
    key = _signature(body.context.model_dump(mode="json"), body.style, body.lang)
    if not body.cache_bust:
        with _CACHE_LOCK:
            cached = _STORY_CACHE.get(key)
        if cached is not None:
            # I4：缓存命中也要带 SSE anti-buffering headers，否则 nginx 会
            # 把一次性的 cache 重放缓冲到 4KB 再吐出，前端看到「卡了一下」。
            return StreamingResponse(
                _replay_cache(cached, body.style),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                },
            )

    # 熔断
    if not _CIRCUIT.allow():
        return StreamingResponse(
            _error_only("AI_CIRCUIT_OPEN", "AI 服务暂不可用，请稍后再试"),
            media_type="text/event-stream",
        )

    return StreamingResponse(
        _events(body, key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _replay_cache(cached: dict, style: str) -> AsyncIterator[str]:
    """缓存命中：一次性 yield title + char ×N + done。

    done 载荷补齐 StoryResponse 必填字段（title / paragraphs / style），
    与 atlas 流 done 字段对齐——前端 `state` computed 依赖
    `current.style === scan.selectedStyle` 决定 ready，否则会跌回 loading。
    同一 cache key 的 style 必然一致（_signature 包含 style 入参），
    但 cached dict 不存 style，所以由调用方传进来。
    """
    yield _sse("title", {"title": cached["title"]})
    for ch in cached["body"]:
        yield _sse("char", {"char": ch})
    paragraphs = [p for p in cached["body"].split("\n\n") if p]
    yield _sse("done", {
        "ok": True,
        "degraded": False,
        "abbr": "",  # photo-level 无 abbr
        "style": style,
        "title": cached["title"],
        "paragraphs": paragraphs,
        "provider": cached.get("provider") if isinstance(cached.get("provider"), str) else "cache",
        "model": "",
        "latency_ms": 0,
        "cached": True,
    })


async def _error_only(code: str, message: str) -> AsyncIterator[str]:
    """熔断 / 健康检查失败：仅一条 error 事件。"""
    yield _sse("error", {"code": code, "message": message})


async def _events(body: PhotoStoryRequest, key: str) -> AsyncIterator[str]:
    """SSE 字符级流：title 一次 → char ×N → done / error。

    桥接：chat_stream 的同步 on_delta → asyncio.Queue → async generator yield。
    P1-7 总时长兜底：超时即取消 AI 任务 + 发 error。
    """
    provider = make_provider()
    # health 是 async，必须 await（否则 coroutine 真值永远为 True）
    if not await provider.health():
        yield _sse("error", {"code": "AI_DISABLED", "message": "AI 未配置"})
        return

    user_content = _build_user_content(
        body.context.model_dump(mode="json"), body.style, body.lang,
    )

    title_emitted = False
    title = ""
    body_text = ""
    title_buf = ""
    started = time.time()
    chunk_queue: asyncio.Queue = asyncio.Queue()
    finished = asyncio.Event()

    def _on_delta(chunk: str) -> None:
        chunk_queue.put_nowait(chunk)

    async def _producer() -> None:
        try:
            # system=""：AgentArts 后台已配置人设，photo-level 不传 system prompt
            await provider.chat_stream("", user_content, _on_delta)
        except Exception as e:
            # 把异常对象本身放进队列（asyncio.Queue 支持任意对象），
            # 让 consumer 用 _classify_reason 按 isinstance 精确分类。
            chunk_queue.put_nowait(e)
        finally:
            finished.set()

    producer_task = asyncio.create_task(_producer())

    try:
        while not finished.is_set() or not chunk_queue.empty():
            try:
                chunk = await asyncio.wait_for(chunk_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                # P1-7 总时长兜底
                if time.time() - started > STORY_TOTAL_TIMEOUT:
                    if not producer_task.done():
                        producer_task.cancel()
                    _CIRCUIT.record_failure()
                    yield _sse("error", {"code": "STORY_TIMEOUT", "message": "故事生成超时"})
                    return
                continue

            if isinstance(chunk, BaseException):
                _CIRCUIT.record_failure()
                # isinstance 精确分类（httpx.TimeoutException / json.JSONDecodeError）；
                # str 兜底（OpenAI provider 抛自定义异常时仍能命中 timeout/parse 子串）
                yield _sse("error", {
                    "code": _classify_reason(chunk),
                    "message": str(chunk) or repr(chunk),
                })
                return

            # 字符级切分（沿用 P2-16 _consume 逻辑）
            for ch in chunk:
                # spec §9：超长截断到 3000 字——已到达上限就停 yield，
                # 避免内存膨胀；done 仍由主流程收尾。
                if len(body_text) >= 3000:
                    break
                if not title_emitted:
                    title_buf += ch
                    if "\n" in title_buf:
                        nl = title_buf.index("\n")
                        title = title_buf[:nl].strip()
                        title_emitted = True
                        yield _sse("title", {"title": title or "星空故事"})
                        # 切完后剩余字符逐字 yield
                        rest = title_buf[nl + 1:]
                        for c in rest:
                            if len(body_text) >= 3000:
                                break
                            yield _sse("char", {"char": c})
                            body_text += c
                        title_buf = ""
                else:
                    yield _sse("char", {"char": ch})
                    body_text += ch
    finally:
        if not producer_task.done():
            producer_task.cancel()

    # 空输出保护（spec §9：AI 返回空字符串 → AI_PARSE_ERROR）
    if not title_emitted and not body_text:
        _CIRCUIT.record_failure()
        yield _sse("error", {"code": "AI_PARSE_ERROR", "message": "AI 返回为空"})
        return

    # 缓存写（仅成功）。流式阶段已在 yield 时截断到 ≤ 3000 字（spec §9）。
    if title or body_text:
        _CIRCUIT.record_success()
        provider_name = _provider_name(provider)
        final_title = title or "星空故事"
        with _CACHE_LOCK:
            _STORY_CACHE[key] = {
                "title": final_title,
                "body": body_text,
                "provider": provider_name,
                "model": "",
            }
        # done 载荷补齐 StoryResponse 必填字段（与 _replay_cache 对齐），
        # 前端 state 依赖 current.style === scan.selectedStyle 才能留在 ready。
        paragraphs = [p for p in body_text.split("\n\n") if p]
        yield _sse("done", {
            "ok": True,
            "degraded": False,
            "abbr": "",  # photo-level 无 abbr
            "style": body.style,
            "title": final_title,
            "paragraphs": paragraphs,
            "provider": provider_name,
            "model": "",
            "latency_ms": int((time.time() - started) * 1000),
            "cached": False,
        })
