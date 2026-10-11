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


# ---------- P2-13 同款星点截断（photo 路径此前漏接 STORY_PROMPT_MAX_STARS）----------


def _stars(*mags: float | None) -> list[dict]:
    out = []
    for i, m in enumerate(mags):
        s = {"bayer": f"star{i}", "name": f"S{i}", "name_zh": f"星{i}", "constellations": []}
        if m is not None:
            s["magnitude"] = m
        out.append(s)
    return out


def test_build_user_content_truncates_to_brightest_n():
    """max_stars>0 时按星等升序保留最亮 N 颗，暗星不出现。"""
    ctx = {**_CTX_A, "bright_stars": _stars(3.0, 0.2, 5.5, 1.1)}
    out = _build_user_content(ctx, "myth", "zh", max_stars=2)
    assert '"S1"' in out and '"S3"' in out      # 0.2 / 1.1 最亮两颗
    assert '"S0"' not in out and '"S2"' not in out
    assert "另有 2 颗较暗星未列出" in out


def test_build_user_content_no_truncation_by_default():
    """不传 max_stars（=0）保持旧行为：全量塞入、无省略提示。"""
    ctx = {**_CTX_A, "bright_stars": _stars(3.0, 0.2, 5.5, 1.1)}
    out = _build_user_content(ctx, "myth", "zh")
    assert all(f'"S{i}"' in out for i in range(4))
    assert "未列出" not in out


def test_build_user_content_max_stars_non_positive_keeps_all():
    """max_stars<=0 = 不截断（与 config 里 STORY_PROMPT_MAX_STARS 语义一致）。"""
    ctx = {**_CTX_A, "bright_stars": _stars(3.0, 0.2, 5.5)}
    for limit in (0, -1):
        out = _build_user_content(ctx, "myth", "zh", max_stars=limit)
        assert all(f'"S{i}"' in out for i in range(3))


def test_build_user_content_missing_magnitude_sorts_last():
    """缺 magnitude 的星排在末位，截断时先被丢弃而非抛错。"""
    ctx = {**_CTX_A, "bright_stars": _stars(None, 2.0, 1.0)}
    out = _build_user_content(ctx, "myth", "zh", max_stars=2)
    assert '"S1"' in out and '"S2"' in out
    assert '"S0"' not in out


def test_build_user_content_no_note_when_nothing_dropped():
    """星点数不超过上限时不出现省略提示。"""
    ctx = {**_CTX_A, "bright_stars": _stars(3.0, 0.2)}
    out = _build_user_content(ctx, "myth", "zh", max_stars=12)
    assert "未列出" not in out


# ---------- capture（EXIF 拍摄信息进 prompt）----------


def test_build_user_content_includes_capture_block():
    """有 capture 时拼出「# 拍摄信息」段，含时刻与地名。"""
    ctx = {**_CTX_A, "capture": {"captured_at": "2025-03-14 22:40", "place": "四川省成都市锦江区"}}
    out = _build_user_content(ctx, "myth", "zh")
    assert "# 拍摄信息" in out
    assert "captured_at: 2025-03-14 22:40" in out
    assert "place: 四川省成都市锦江区" in out
    assert "不要据此编造地方传说" in out


def test_build_user_content_capture_partial_fields():
    """只有地名没有时刻时，不输出空的 captured_at 行。"""
    ctx = {**_CTX_A, "capture": {"captured_at": None, "place": "青海省海西州"}}
    out = _build_user_content(ctx, "myth", "zh")
    assert "place: 青海省海西州" in out
    assert "captured_at" not in out


def test_build_user_content_no_capture_block_when_empty():
    """capture 为 None / {} / 全空字段 → 整段不出现。"""
    for cap in (None, {}, {"captured_at": None, "place": None}):
        out = _build_user_content({**_CTX_A, "capture": cap}, "myth", "zh")
        assert "拍摄信息" not in out


def test_build_user_content_capture_after_omitted_note():
    """顺序稳定：星点省略提示 → 拍摄信息 → center/field。"""
    ctx = {
        **_CTX_A,
        "bright_stars": _stars(3.0, 0.2, 5.5, 1.1),
        "capture": {"captured_at": "2025-06-01 21:05", "place": "云南省大理州"},
    }
    out = _build_user_content(ctx, "myth", "zh", max_stars=2)
    assert out.index("未列出") < out.index("# 拍摄信息") < out.index("center_ra")
