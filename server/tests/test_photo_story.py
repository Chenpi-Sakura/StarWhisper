"""services/photo_story.py 单测（spec §5.1 / §7.3）。

_signature：序列化稳定性（字段顺序无关、中文 ensure_ascii=False）
_build_user_content：拼 user_content，含 style/lang/constellations/stars，可选 center/field。
"""
from __future__ import annotations

from services.photo_story import _build_user_content, _signature


_CTX_A = {
    "constellations": [
        {"abbr": "ori", "tradition": "western", "name": "猎户座", "latin": "Orion", "confidence": 0.95},
    ],
    "bright_stars": [
        {"bayer": "α Ori", "name": "Betelgeuse", "name_zh": "参宿四", "magnitude": 0.5,
         "constellations": ["ori"]},
    ],
    "center": {"ra": 84.0, "dec": -1.0},
    "field": {"width_deg": 12.5, "height_deg": 8.3},
}


def test_signature_canonical_order_irrelevant():
    """_signature 对 context 字段顺序无关（sort_keys=True 保证）。"""
    ctx_reordered = {
        "bright_stars": _CTX_A["bright_stars"],
        "field": _CTX_A["field"],
        "center": _CTX_A["center"],
        "constellations": _CTX_A["constellations"],
    }
    assert _signature(_CTX_A, "myth", "zh") == _signature(ctx_reordered, "myth", "zh")


def test_signature_differs_on_style():
    """style 变化 → key 变化。"""
    assert _signature(_CTX_A, "myth", "zh") != _signature(_CTX_A, "science", "zh")


def test_signature_differs_on_constellation_set():
    """constellations 内容变化 → key 变化。"""
    ctx_b = {
        **_CTX_A,
        "constellations": [
            {"abbr": "cyg", "tradition": "western", "name": "天鹅座", "latin": "Cygnus", "confidence": 0.9},
        ],
    }
    assert _signature(_CTX_A, "myth", "zh") != _signature(ctx_b, "myth", "zh")


def test_signature_returns_sixteen_hex_chars():
    """key 长度 = 16 hex（sha1 前 16 字符）。"""
    key = _signature(_CTX_A, "myth", "zh")
    assert len(key) == 16
    assert all(c in "0123456789abcdef" for c in key)


def test_build_user_content_includes_style_and_lang():
    """user_content 必须包含 style 与 lang 行（spec §7.3 骨架）。"""
    out = _build_user_content(_CTX_A, "myth", "zh")
    assert "style: myth" in out
    assert "lang: zh" in out


def test_build_user_content_includes_constellations_json():
    """constellations JSON 必须内嵌（中文 ensure_ascii=False）。"""
    out = _build_user_content(_CTX_A, "myth", "zh")
    assert "猎户座" in out
    assert "Orion" in out
    assert "constellations:" in out


def test_build_user_content_includes_bright_stars_json():
    """bright_stars JSON 必须内嵌（中文 star 名保留）。"""
    out = _build_user_content(_CTX_A, "myth", "zh")
    assert "参宿四" in out
    assert "Betelgeuse" in out
    assert "bright_stars:" in out


def test_build_user_content_includes_center_and_field():
    """center 与 field 同时提供时拼接对应行。"""
    out = _build_user_content(_CTX_A, "myth", "zh")
    assert "center_ra: 84.0, dec: -1.0" in out
    assert "field: 12.5x8.3 deg" in out


def test_build_user_content_omits_center_when_missing():
    """center 缺省时 user_content 不含 center 行。"""
    ctx = {**_CTX_A}
    ctx.pop("center")
    out = _build_user_content(ctx, "myth", "zh")
    assert "center_ra" not in out
    assert "center_dec" not in out


def test_build_user_content_omits_field_when_missing():
    """field 缺省时 user_content 不含 field 行。"""
    ctx = {**_CTX_A}
    ctx.pop("field")
    out = _build_user_content(ctx, "myth", "zh")
    assert "field:" not in out


def test_build_user_content_ends_with_instruction():
    """user_content 末尾引导句告诉 AI 按系统提示词要求讲 3 段。"""
    out = _build_user_content(_CTX_A, "myth", "zh")
    assert "3 段" in out or "三段" in out
