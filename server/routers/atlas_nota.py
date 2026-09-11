"""POST /api/atlas-nota 与 POST /api/atlas-nota/stream（atlas 详情页「星座简介」段）。

- POST /api/atlas-nota         纯非流式，一次 JSON 返回（向后兼容）
- POST /api/atlas-nota/stream  SSE 字符级流（AtlasNota 详情页使用，
                               与 /api/atlas-story/stream 同协议）

单档「星图导读」风格（不复用 myth/science）；100-200 字中文一段。
- 10 分钟 LRU（cachetools.TTLCache），key=(tradition, abbr) 二维，**不缓存 degraded**
- Cache-Bust：1 header 或 cacheBust=true body 字段绕过缓存
- 未知星座 → 404 CONSTELLATION_NOT_FOUND
- 非法 tradition → 400 INVALID_TRADITION
- DisabledProvider / AI 失败 → fallback caption（`degraded:true`，**非 503**）
- 503 NOTE_FALLBACK_MISSING：caption 也缺失（数据损坏时出现）
- P1-9 故障熔断（atlas-nota 独立窗口）/ P1-10 按 IP 限流

SSE 事件流（stream 端点）：
- char：每收到一段 AI 增量 yield 字符级 event:char（包含 \n）
- done：成功 / 降级 / 缓存命中后 yield event:done（带 meta）
- reset：AI 失败、需降级时发——前端清空半截字符，等 preset 字符流重放
- error：caption 也缺失（数据损坏）时发 event:error（不常见）
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from config import STORY_TOTAL_TIMEOUT
from services.atlas_nota import (
    AI_MODEL,
    _BREAKER,
    _clean_markdown,
    _resolve_tradition,
    build_system_prompt,
    build_user_content,
    cache_clear,
    cache_get,
    cache_put,
    get_caption,
    reset_breaker,
    resolve_payload,
)
from services.story_throttle import check_rate_limit
from services.traditions import get_constellation, list_traditions


router = APIRouter(prefix="/api/atlas-nota", tags=["atlas-nota"])

logger = logging.getLogger(__name__)


class AtlasNotaRequest(BaseModel):
    """请求体：星座缩写 + 可选 tradition / cacheBust / lang。"""

    model_config = ConfigDict(populate_by_name=True)

    abbr: str = Field(..., description="星座缩写（如 ori）")
    tradition: str | None = Field(
        None,
        description="tradition key（western / chinese）；缺省跨 tradition 首命中",
    )
    cacheBust: bool = Field(False, alias="cacheBust")
    lang: str = Field("zh", description="语言代码，暂固定 zh")


def _check_request(body: AtlasNotaRequest) -> tuple[str, str | None]:
    """校验 abbr / tradition；合法则返回 (abbr, tradition | None)。

    - 未带 tradition：跨 tradition 收集 abbr，首命中视为合法（向后兼容）
    - 带 tradition：必须在 list_traditions() 内 + 该 tradition 内能查到
    """
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
        return body.abbr, body.tradition.lower()
    valid_abbrs = {
        c["abbr"]
        for t in list_traditions()
        for c in list_constellations_safe(t["key"])
    }
    if body.abbr not in valid_abbrs:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "CONSTELLATION_NOT_FOUND",
                "message": "未收录此星座",
            },
        )
    return body.abbr, None


def list_constellations_safe(tradition: str) -> list[dict]:
    """包一层：list_constellations 可能抛（数据缺失），这里兜底 []。"""
    from services.traditions import list_constellations

    try:
        return list_constellations(tradition)
    except Exception:  # noqa: BLE001
        return []


@router.post("")
async def post_atlas_nota(
    body: AtlasNotaRequest,
    request: Request,
    cache_bust: int = Header(0, alias="Cache-Bust"),
):
    """atlas 详情页 ConstellationView「星座简介」段入口。

    返回：{ ok, tradition, abbr, intro, degraded, source }
    - source: agentarts | preset | cache
    - degraded:true 时 source="preset"，intro 来自 traditions caption 字段
    """
    check_rate_limit(request)  # P1-10
    abbr, requested_tradition = _check_request(body)
    bust = bool(body.cacheBust) or cache_bust == 1

    return await resolve_payload(abbr, requested_tradition, bust)


# 暴露给测试夹具
def _reset_breaker() -> None:
    reset_breaker()


def _clear_cache() -> None:
    cache_clear()


# ============= SSE 字符级流 =============


def _sse(event: str, data: object) -> str:
    """封装一条 SSE 帧。data 为 JSON 字符串。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _preset_chars_sse(abbr: str, trad: str, reason: str, elapsed: float = 0.0) -> str:
    """把 caption 降级路径包成字符级 SSE 帧，发送完返回整块 SSE 文本。

    caption 缺失 → yield event:error（NOTE_FALLBACK_MISSING）。
    """
    caption = get_caption(abbr, trad)
    if caption is None:
        return _sse("error", {
            "code": "NOTE_FALLBACK_MISSING",
            "message": "AI 与 caption 兜底同时不可用",
        })
    frames: list[str] = []
    for ch in caption:
        frames.append(_sse("char", {"char": ch}))
    frames.append(_sse("done", {
        "ok": True,
        "abbr": abbr,
        "tradition": trad,
        "intro": caption,
        "degraded": True,
        "degraded_reason": reason,
        "source": "preset",
        "model": "preset",
        "provider": "fallback",
        "latency_ms": int(elapsed * 1000),
        "cached": False,
    }))
    return "".join(frames)


async def _events(
    abbr: str,
    trad: str,
    bust: bool,
) -> AsyncIterator[str]:
    """atlas-nota/stream 字符级 SSE 事件主流程。

    顺序：
    1. 缓存命中（bust=False）→ 一次性 yield 缓存内容的 char 帧 + done
    2. 熔断开启（冷却期）→ yield reset + 走 preset 降级
    3. AI 流式：chat_stream 同步 on_delta → asyncio.Queue → 逐字符 yield char
    4. 失败：yield reset + 走 preset 降级
    """
    # 1. 缓存命中
    if not bust:
        cached = cache_get(trad, abbr)
        if cached is not None:
            intro = cached.get("intro", "")
            for ch in intro:
                yield _sse("char", {"char": ch})
            meta = {k: v for k, v in cached.items() if k != "intro"}
            meta["cached"] = True
            meta["latency_ms"] = 0
            meta["origin_latency_ms"] = cached.get("latency_ms", 0)
            yield _sse("done", meta)
            return

    # 2. 熔断
    if not _BREAKER.allow():
        yield _sse("reset", {})
        yield _preset_chars_sse(abbr, trad, "AI_CIRCUIT_OPEN")
        return

    # 3. AI 流式
    constellation = get_constellation(trad, abbr)
    if constellation is None:
        # 跨 tradition 兑底（路由层已校验过，这里再防一次）
        for t in list_traditions():
            entry = get_constellation(t["key"], abbr)
            if entry is not None:
                constellation = entry
                break
    if constellation is None:
        # 理论上路由层 404 不会走到这
        yield _sse("error", {"code": "CONSTELLATION_NOT_FOUND", "message": "未收录此星座"})
        return

    system_prompt = build_system_prompt(constellation, trad)
    user_prompt = build_user_content(constellation, trad)

    from services.ai_provider import make_provider
    provider = make_provider()
    start = time.time()

    # 桥接：chat_stream 的同步 on_delta → async generator 的 yield
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

    accumulated = ""
    while True:
        kind, payload = await q.get()
        if kind == "end":
            break
        if kind == "delta" and isinstance(payload, str):
            accumulated += payload
            for ch in payload:
                yield _sse("char", {"char": ch})

    intro = _clean_markdown(accumulated)

    # 4. 失败 / 空输出 → reset + preset
    if chat_state["exc"] is not None or not intro:
        elapsed = time.time() - start
        reason = (
            "AI_PROVIDER_PARSE_ERROR" if not intro and chat_state["exc"] is None
            else "AI_PROVIDER_ERROR"
        )
        if isinstance(chat_state["exc"], Exception):
            try:
                # 复用 service 层的分类（超时 / DisabledProvider / 连接 / 其他）
                from services.atlas_nota import _classify_reason
                reason = _classify_reason(chat_state["exc"])
            except Exception:  # noqa: BLE001
                pass
        try:
            _BREAKER.record_failure()
        except Exception:  # noqa: BLE001
            pass
        yield _sse("reset", {})
        yield _preset_chars_sse(abbr, trad, reason, elapsed=elapsed)
        return

    # 成功
    _BREAKER.record_success()
    payload = {
        "ok": True,
        "abbr": abbr,
        "tradition": trad,
        "intro": intro,
        "degraded": False,
        "source": "agentarts",
        "model": AI_MODEL,
        "provider": provider.name,
        "latency_ms": int((time.time() - start) * 1000),
        "cached": False,
    }
    cache_put(trad, abbr, payload)
    yield _sse("done", payload)


@router.post("/stream")
async def post_atlas_nota_stream(
    body: AtlasNotaRequest,
    request: Request,
    cache_bust: int = Header(0, alias="Cache-Bust"),
):
    """SSE 字符级流（与 /api/atlas-story/stream 同协议）。

    事件流：char ×N → done（成功）；reset + char ×N + done（降级）。
    用于 AtlasNota 详情页「星座简介」段：边生成边显示。
    """
    check_rate_limit(request)  # P1-10
    abbr, requested_tradition = _check_request(body)
    bust = bool(body.cacheBust) or cache_bust == 1
    trad = _resolve_tradition(requested_tradition, abbr)

    return StreamingResponse(
        _events(abbr, trad, bust),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
