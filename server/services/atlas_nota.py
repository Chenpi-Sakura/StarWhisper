"""POST /api/atlas-nota 业务逻辑（图鉴详情页“星座简介”段）。

- 单档“星图导读” 风格，不复用 myth/science 二档
- 100-200 字中文一段，不含 Markdown / 列表 / JSON
- 10 分钟 LRU（cachetools.TTLCache），key = (tradition, abbr) 二维
- 熔断 / 限流 与 atlas-story 独立（窗口名 "atlas-nota"），避免一处故障波及其它端点
- 降级：AI 抛任何异常 → traditions/<tradition>/<abbr>.json 的 caption 字段
- degraded:true **不写缓存**（失败一次别让整场都是离线简介）
- 降级源也缺失 → 抛 503 NOTE_FALLBACK_MISSING
- 总时长预算复用 STORY_TOTAL_TIMEOUT（默认 45s）
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from threading import Lock

from cachetools import TTLCache
from fastapi import HTTPException

from config import AI_MODEL, STORY_TOTAL_TIMEOUT
from services.ai_provider import (
    ATLAS_NOTA_SYSTEM_PROMPT,
    ATLAS_NOTA_USER_TEMPLATE,
    make_provider,
)
from services.story_fallback import get_caption
from services.story_throttle import get_circuit


logger = logging.getLogger(__name__)

# 缓存：maxsize=96 / ttl=600s；key=(tradition, abbr)；value=dict（含 degraded 字段）
_NOTA_CACHE: TTLCache = TTLCache(maxsize=96, ttl=600)
_CACHE_LOCK = Lock()

# I5：atlas-nota 独立熔断窗口——不复用 atlas-story 的 "atlas"。
_BREAKER = get_circuit("atlas-nota")

# 与 atlas-story 同款 Markdown 清洗（ai_provider.py clean_markdown 在路由里
# 持有，这里复刻一份避免循环依赖）。幂等；纯文本返回原值。
_MD_CODE = re.compile(r"`([^`]*)`")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_MD_HEADING = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_BULLET = re.compile(r"^[-*•]\s+", re.MULTILINE)
_MD_NUM_LIST = re.compile(r"^\d+[.、）)]\s*", re.MULTILINE)


def _clean_markdown(text: str) -> str:
    """剥离 LLM 输出中常见 Markdown 标记，保留纯文本段落。"""
    s = (text or "").strip()
    if not s:
        return ""
    s = _MD_CODE.sub(r"\1", s)
    s = _MD_BOLD.sub(r"\1", s)
    s = _MD_ITALIC.sub(r"\1", s)
    s = _MD_HEADING.sub("", s)
    s = _MD_BULLET.sub("", s)
    s = _MD_NUM_LIST.sub("", s)
    return s.strip()


def _cache_key(tradition: str, abbr: str) -> tuple[str, str]:
    return (tradition, abbr)


def cache_get(tradition: str, abbr: str) -> dict | None:
    """读取缓存（命中或 None）。degraded 条目不在缓存中（写入时已跳过）。"""
    with _CACHE_LOCK:
        return _NOTA_CACHE.get(_cache_key(tradition, abbr))


def cache_put(tradition: str, abbr: str, payload: dict) -> None:
    """degraded:true 不写缓存。"""
    if payload.get("degraded"):
        return
    with _CACHE_LOCK:
        _NOTA_CACHE[_cache_key(tradition, abbr)] = payload


def cache_clear() -> None:
    """测试夹具：清空缓存。"""
    with _CACHE_LOCK:
        _NOTA_CACHE.clear()


def reset_breaker() -> None:
    """测试夹具：重置熔断器。"""
    _BREAKER.reset()


def _classify_reason(exc: Exception) -> str:
    """根据异常 message 推断失败原因分类。"""
    msg = str(exc).lower()
    if "disabled" in msg:
        return "AI_PROVIDER_DISABLED"
    if "timeout" in msg or "timed out" in msg:
        return "AI_PROVIDER_TIMEOUT"
    if "parse" in msg or "json" in msg:
        return "AI_PROVIDER_PARSE_ERROR"
    return "AI_PROVIDER_5XX"


def _resolve_tradition(tradition: str | None, abbr: str) -> str:
    """tradition → 缓存/降级用的具体 key。

    请求带 tradition → 路由层已校验非空 + 命中此 abbr，直接用；
    否则回退跨 tradition 首命中（与 atlas-story P2-12 行为对齐）。
    """
    if tradition:
        return tradition.lower()
    from services.traditions import list_traditions, get_constellation

    for t in list_traditions():
        entry = get_constellation(t["key"], abbr)
        if entry is not None:
            return t["key"]
    return "western"


def build_user_content(constellation: dict, tradition: str) -> str:
    """组装 user_content（不含 system prompt）—— 给 AI 喂的事实素材。

    字段全部 .get() 访问：缺键 → 兜底字符串，避免 prompt 报错。
    """
    name_zh = constellation.get("name", "")
    latin = constellation.get("latin", "")
    season = constellation.get("season") or "四季可见"
    brightest_name = "—"
    brightest_mag = "—"
    stars = constellation.get("stars") or {}
    if isinstance(stars, dict) and stars:
        # 取 magnitude 最小（最亮）的一颗
        try:
            star_items = [
                (s.get("name") or s.get("bayer") or "—", s.get("magnitude"))
                for s in stars.values()
                if isinstance(s.get("magnitude"), (int, float))
            ]
            if star_items:
                star_items.sort(key=lambda x: x[1])
                brightest_name, brightest_mag = star_items[0]
                brightest_mag = f"{float(brightest_mag):.2f}"
        except Exception:  # noqa: BLE001
            pass
    return ATLAS_NOTA_USER_TEMPLATE.format(
        constellation_zh=name_zh,
        latin=latin,
        tradition=tradition,
        season=season,
        brightest_name=brightest_name,
        brightest_mag=brightest_mag,
    )


def build_system_prompt(constellation: dict, tradition: str) -> str:
    """组装 system prompt（star-atlas 「星图导读」 专用）。"""
    name_zh = constellation.get("name", "")
    latin = constellation.get("latin", "")
    return ATLAS_NOTA_SYSTEM_PROMPT.format(
        constellation_zh=name_zh, latin=latin, tradition=tradition,
    )


def _preset_payload(
    abbr: str, tradition: str, reason: str, *, elapsed: float = 0.0,
) -> dict:
    """构造 caption 降级 payload；caption 缺失时抛 503 NOTE_FALLBACK_MISSING。"""
    caption = get_caption(abbr, tradition)
    if not caption:
        # 跨 tradition 再找一次（兼容缺省 tradition 的情况）
        caption = get_caption(abbr, None)
        if not caption:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "NOTE_FALLBACK_MISSING",
                    "message": "AI 不可用且 caption 缺失",
                },
            )
    return {
        "ok": True,
        "abbr": abbr,
        "tradition": tradition,
        "intro": caption.strip(),
        "degraded": True,
        "source": "preset",
        "degraded_reason": reason,
        "model": "preset",
        "provider": "fallback",
        "latency_ms": int(elapsed * 1000),
        "cached": False,
    }


async def resolve_payload(
    abbr: str,
    tradition: str | None,
    bust: bool,
) -> dict:
    """生成/取 intro 完整 payload（缓存命中 / AI / caption 降级）。

    返回 dict 即路由层直接 jsonify 的内容；任何 HTTPException（503 兜底缺失 /
    4xx）由调用方上抛到 FastAPI 异常处理。
    """
    trad = _resolve_tradition(tradition, abbr)

    # 缓存命中（bust 时跳过）
    if not bust:
        cached = cache_get(trad, abbr)
        if cached is not None:
            return {
                **cached,
                "cached": True,
                "latency_ms": 0,
                "origin_latency_ms": cached.get("latency_ms", 0),
            }

    # 熔断冷却中 → 直接降级 caption，不让请求干等超时
    if not _BREAKER.allow():
        return _preset_payload(abbr, trad, "AI_CIRCUIT_OPEN")

    # 找星座条目（找不到说明校验漏了，路由层兜底，这里再防一次）
    from services.traditions import get_constellation

    constellation = get_constellation(trad, abbr)
    if constellation is None:
        # 跨 tradition 再试一次
        from services.traditions import list_traditions

        for t in list_traditions():
            entry = get_constellation(t["key"], abbr)
            if entry is not None:
                constellation = entry
                break
    if constellation is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "CONSTELLATION_NOT_FOUND", "message": "未收录此星座"},
        )

    system_prompt = build_system_prompt(constellation, trad)
    user_prompt = build_user_content(constellation, trad)

    provider = make_provider()
    start = time.time()
    try:
        text = await asyncio.wait_for(
            provider.chat(system_prompt, user_prompt, timeout=30.0),
            timeout=STORY_TOTAL_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        _BREAKER.record_failure()
        return _preset_payload(
            abbr, trad, _classify_reason(exc), elapsed=time.time() - start,
        )

    intro = _clean_markdown(text)

    # 字数软校验（目标 100-200 字；不足或过多都允许通过但记日志）
    chars = len(intro)
    if chars < 50 or chars > 400:
        logger.warning(
            "atlas-nota output length off-target: abbr=%s trad=%s chars=%d",
            abbr, trad, chars,
        )

    if not intro:
        _BREAKER.record_failure()
        return _preset_payload(
            abbr, trad, "AI_PROVIDER_PARSE_ERROR", elapsed=time.time() - start,
        )

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
    return payload
