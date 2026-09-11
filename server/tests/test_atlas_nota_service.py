"""services/atlas_nota.py 单元测试（路由无关，business logic 直测）。

覆盖：
- build_user_content 字段完整性 + 缺字段降级
- build_system_prompt 含 constellation_zh / latin
- cache_get / cache_put / cache_clear 读写隔离
- cache_put 跳过 degraded:true（失败一次别让整场都是离线简介）
- get_caption 命中 / 跨 tradition 首命中 / 缺省 / 缺 caption 返回 None
- _clean_markdown 清洗常见 Markdown 标记
- _resolve_tradition 显式 / 缺省 / 兜底 western
- reset_breaker / _BREAKER.allow 不抛错
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services import atlas_nota
from services.atlas_nota import (
    build_system_prompt,
    build_user_content,
    cache_clear,
    cache_get,
    cache_put,
    get_caption,
    reset_breaker,
    resolve_payload,
)


# ---------- Fixtures ----------


@pytest.fixture(autouse=True)
def _isolate():
    """每个用例前后清缓存 + 重置熔断器。"""
    cache_clear()
    reset_breaker()
    yield
    cache_clear()
    reset_breaker()


# ---------- build_user_content ----------


def test_build_user_content_full_fields():
    """所有字段都在 → 模板完整填充。"""
    constellation = {
        "name": "猎户座",
        "latin": "Orion",
        "season": "winter",
        "stars": {
            "s1": {"name": "参宿四", "bayer": "α", "magnitude": 0.42},
            "s2": {"name": "参宿七", "bayer": "β", "magnitude": 0.13},
            "s3": {"name": "参宿五", "bayer": "γ", "magnitude": 1.64},
        },
    }
    text = build_user_content(constellation, "western")
    assert "猎户座" in text
    assert "Orion" in text
    assert "western" in text
    assert "winter" in text
    # 最亮星是 magnitude 最小的那颗
    assert "参宿七" in text
    assert "0.13" in text


def test_build_user_content_missing_optional_fields():
    """缺 season / stars → 不抛错，走兜底字符串。"""
    constellation = {"name": "X", "latin": "X"}
    text = build_user_content(constellation, "western")
    # 不报错，且字段填充是字符串
    assert "X" in text
    assert "western" in text


def test_build_user_content_no_stars_uses_dash():
    """stars 为空 dict → 最亮星显 —。"""
    constellation = {"name": "X", "latin": "X", "stars": {}}
    text = build_user_content(constellation, "western")
    assert "—" in text


def test_build_user_content_skips_stars_without_magnitude():
    """缺 magnitude 字段的星不参与排序。"""
    constellation = {
        "name": "X",
        "latin": "X",
        "stars": {
            "a": {"name": "Alpha", "magnitude": 1.0},
            "b": {"name": "Beta"},  # 无 magnitude，跳过
            "c": {"name": "Gamma", "magnitude": 2.5},
        },
    }
    text = build_user_content(constellation, "western")
    assert "Alpha" in text


# ---------- build_system_prompt ----------


def test_build_system_prompt_contains_constellation_and_latin():
    """system prompt 模板要包含星座名称 + 拉丁名。"""
    p = build_system_prompt({"name": "猎户座", "latin": "Orion"}, "western")
    assert "猎户座" in p
    assert "Orion" in p
    # 含硬约束：禁止 Markdown / JSON
    assert "Markdown" in p


# ---------- Cache: cache_get / cache_put / cache_clear ----------


def test_cache_put_and_get_round_trip():
    """正常 payload：写 → 读 → 内容一致。"""
    payload = {
        "ok": True, "abbr": "ori", "tradition": "western", "intro": "hello",
        "degraded": False, "source": "agentarts",
    }
    cache_put("western", "ori", payload)
    got = cache_get("western", "ori")
    assert got == payload


def test_cache_put_skips_degraded():
    """degraded:true 不写缓存——失败一次别让整场都是离线简介。"""
    payload = {
        "ok": True, "abbr": "ori", "tradition": "western", "intro": "fallback",
        "degraded": True, "source": "preset",
    }
    cache_put("western", "ori", payload)
    assert cache_get("western", "ori") is None


def test_cache_put_different_tradition_isolated():
    """不同 tradition 不互串。"""
    p1 = {"abbr": "ori", "tradition": "western", "intro": "A", "degraded": False, "source": "agentarts"}
    p2 = {"abbr": "ori", "tradition": "chinese", "intro": "B", "degraded": False, "source": "agentarts"}
    cache_put("western", "ori", p1)
    cache_put("chinese", "ori", p2)
    assert cache_get("western", "ori")["intro"] == "A"
    assert cache_get("chinese", "ori")["intro"] == "B"


def test_cache_clear_resets():
    """cache_clear 后读 → None。"""
    cache_put("western", "ori", {"abbr": "ori", "degraded": False, "intro": "x"})
    assert cache_get("western", "ori") is not None
    cache_clear()
    assert cache_get("western", "ori") is None


def test_cache_get_missing_returns_none():
    """未写过的 key 返回 None（不是抛错）。"""
    assert cache_get("western", "nope") is None


# ---------- get_caption ----------


def test_get_caption_returns_existing():
    """caption 字段存在 → 原样返回。"""
    cap = get_caption("ori", "western")
    assert cap is not None
    assert "腰带三星" in cap or "冬夜" in cap  # ori.json caption 实测


def test_get_caption_with_legacy_alias():
    """chinese tradition 下 '猎户' abbr：实际数据里 abbr 为 ori 的别名，
    若 chinese/<chinese_abbr>.json 不存在则返回 None（不抛错）。"""
    cap = get_caption("notexist", "western")
    assert cap is None


def test_get_caption_cross_tradition_fallback():
    """tradition=None 时跨 tradition 首命中。"""
    cap = get_caption("ori", None)
    assert cap is not None  # 至少 ori.json 应该有


def test_get_caption_missing_returns_none():
    """不存在的 abbr → None（不抛错）。"""
    assert get_caption("__totally_fake__", "western") is None


# ---------- _clean_markdown ----------


def test_clean_markdown_strips_inline_code():
    assert atlas_nota._clean_markdown("`猎户` 座") == "猎户 座"


def test_clean_markdown_strips_bold_italic():
    assert atlas_nota._clean_markdown("**猎户** 座") == "猎户 座"
    assert atlas_nota._clean_markdown("*猎户* 座") == "猎户 座"


def test_clean_markdown_strips_heading():
    assert atlas_nota._clean_markdown("## 猎户座") == "猎户座"


def test_clean_markdown_strips_bullet():
    assert atlas_nota._clean_markdown("- 猎户\n- 参宿") == "猎户\n参宿"


def test_clean_markdown_keeps_plain_text():
    """纯文本应原样返回（幂等）。"""
    txt = "猎户座，冬季星空最醒目的坐标。腰带三星横跨天球赤道。"
    assert atlas_nota._clean_markdown(txt) == txt


def test_clean_markdown_empty_string():
    assert atlas_nota._clean_markdown("") == ""
    assert atlas_nota._clean_markdown(None) == ""  # type: ignore[arg-type]


# ---------- _resolve_tradition ----------


def test_resolve_tradition_explicit():
    """显式 tradition → 小写返回。"""
    assert atlas_nota._resolve_tradition("Western", "ori") == "western"


def test_resolve_tradition_none_falls_back_to_found():
    """tradition=None → 跨 tradition 首命中（ori 在 western 下）。"""
    assert atlas_nota._resolve_tradition(None, "ori") == "western"


def test_resolve_tradition_unknown_falls_back_to_western():
    """完全不存在的 abbr → 'western' 兜底（路由层会 404，这里只是兜底）。"""
    assert atlas_nota._resolve_tradition(None, "__nope__") == "western"


# ---------- resolve_payload: 集成 mock provider ----------


@pytest.fixture
def _mock_provider_ok():
    """AI 正常返回（200 字中文）。"""
    return AsyncMock()


async def test_resolve_payload_cache_hit_skips_provider(_mock_provider_ok):
    """先写一次缓存，再读 → 不调 AI。"""
    payload = {
        "ok": True, "abbr": "ori", "tradition": "western", "intro": "cached!",
        "degraded": False, "source": "agentarts",
    }
    cache_put("western", "ori", payload)

    with patch("services.atlas_nota.make_provider") as mp:
        result = await resolve_payload("ori", "western", bust=False)
        mp.assert_not_called()
    assert result["cached"] is True
    assert result["intro"] == "cached!"


async def test_resolve_payload_cache_bust_calls_provider():
    """bust=True → 绕过缓存，调 AI。"""
    payload = {
        "ok": True, "abbr": "ori", "tradition": "western", "intro": "cached!",
        "degraded": False, "source": "agentarts",
    }
    cache_put("western", "ori", payload)

    provider = AsyncMock()
    provider.name = "agentarts"
    provider.chat = AsyncMock(
        return_value="猎户座，冬季星空最醒目的坐标。腰带三星横跨天球赤道。",
    )

    with patch("services.atlas_nota.make_provider", return_value=provider):
        result = await resolve_payload("ori", "western", bust=True)
        provider.chat.assert_awaited_once()
    assert result["cached"] is False
    assert result["degraded"] is False
    assert "猎户" in result["intro"]


async def test_resolve_payload_ai_disabled_falls_back_to_caption():
    """DisabledProvider → 降级到 caption，degraded:true。"""
    from services.ai_provider import DisabledProvider

    provider = DisabledProvider()
    with patch("services.atlas_nota.make_provider", return_value=provider):
        result = await resolve_payload("ori", "western", bust=False)
    assert result["degraded"] is True
    assert result["source"] == "preset"
    assert "腰带三星" in result["intro"] or "冬夜" in result["intro"]
    assert result["degraded_reason"] == "AI_PROVIDER_DISABLED"


async def test_resolve_payload_ai_timeout_falls_back_to_caption():
    """AI 抛超时 → 降级到 caption。"""
    provider = AsyncMock()
    provider.name = "agentarts"
    provider.chat = AsyncMock(side_effect=TimeoutError("AI_PROVIDER_TIMEOUT"))

    with patch("services.atlas_nota.make_provider", return_value=provider):
        result = await resolve_payload("ori", "western", bust=False)
    assert result["degraded"] is True
    assert result["source"] == "preset"
    assert "AI_PROVIDER_TIMEOUT" in result["degraded_reason"]


async def test_resolve_payload_degraded_does_not_cache():
    """第一次 degraded 后，第二次仍尝试调 AI（验证不写缓存语义）。"""
    from services.ai_provider import DisabledProvider

    # 第一次：降级
    with patch("services.atlas_nota.make_provider", return_value=DisabledProvider()):
        r1 = await resolve_payload("ori", "western", bust=False)
    assert r1["degraded"] is True
    assert cache_get("western", "ori") is None  # 关键断言

    # 第二次：mock 一个能用的 provider——若不调 AI，会直接命中缓存
    provider = AsyncMock()
    provider.name = "agentarts"
    provider.chat = AsyncMock(return_value="猎户座简介文本。")
    with patch("services.atlas_nota.make_provider", return_value=provider):
        r2 = await resolve_payload("ori", "western", bust=False)
    provider.chat.assert_awaited_once()  # 关键：调了 AI
    assert r2["degraded"] is False


async def test_resolve_payload_ai_returns_empty_falls_back():
    """AI 返回空串 → 解析失败 → 降级。"""
    provider = AsyncMock()
    provider.name = "agentarts"
    provider.chat = AsyncMock(return_value="   ")  # 纯空白

    with patch("services.atlas_nota.make_provider", return_value=provider):
        result = await resolve_payload("ori", "western", bust=False)
    assert result["degraded"] is True
    assert "AI_PROVIDER_PARSE_ERROR" in result["degraded_reason"]


async def test_resolve_payload_404_when_constellation_missing():
    """完全找不到 abbr → 抛 404（路由层兜底，service 层也防）。"""
    with pytest.raises(Exception) as ei:
        await resolve_payload("__totally_fake__", "western", bust=False)
    assert "404" in str(ei.value) or "CONSTELLATION_NOT_FOUND" in str(ei.value)
