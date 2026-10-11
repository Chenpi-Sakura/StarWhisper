"""photo-level 故事组装（spec §5.1 / §7.3）。

`_signature`：photo 上下文 → 稳定 cache key。
`_build_user_content`：photo 上下文 → AgentArts user_content（不含 system prompt，由 AgentArts 后台管）。
"""
from __future__ import annotations

import hashlib
import json


def _signature(context: dict, style: str, lang: str) -> str:
    """稳定缓存 key：sha1(canonical_json({context, style, lang}))[:16]。

    sort_keys=True 保证字段顺序无关；ensure_ascii=False 保证中文 star/星官名编码一致。
    16 hex chars (64 bit) 足够 LRU 容量（maxsize=96），冲突概率可忽略。
    """
    payload = {
        "context": context,
        "style": style,
        "lang": lang,
    }
    canon = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]


def _magnitude_key(star: dict) -> float:
    """缺 magnitude / 非数值一律 99.0 沉到末位（与 atlas 路径同防护）。"""
    mag = star.get("magnitude")
    return float(mag) if isinstance(mag, (int, float)) else 99.0


def _build_user_content(context: dict, style: str, lang: str, max_stars: int = 0) -> str:
    """拼 AgentArts user_content（spec §7.3 骨架）。

    字段顺序：
      1. style / lang 元信息
      2. constellations / bright_stars JSON dump（+ 星点截断时的省略提示）
      3. 可选 capture（拍摄时刻 / 区县级地名，来自 EXIF）
      4. 可选 center / field
      5. 末尾引导句

    Args:
        context: 含 constellations / bright_stars / capture? / center? / field? 的 dict。
            注意 constellations 目前**不含** mansion（二十八宿归属）——前端
            StoryPanel.buildContext 只映射 abbr/tradition/name/latin/confidence。
        style: "myth" | "science"。
        lang: "zh"。
        max_stars: 星等升序取最亮 N 颗；<=0 = 不截断。上游投影出的 stars_overlay
            随视场增大而膨胀（实测 79°×59° 广域图 1709 颗 → user_content 174KB），
            photo 路径必须与 atlas 一样受 STORY_PROMPT_MAX_STARS 约束。

    Returns:
        多行字符串，发给 AgentArts 作为 user_content。
    """
    all_stars = context.get("bright_stars") or []
    stars = all_stars
    omitted = 0
    if max_stars > 0 and len(all_stars) > max_stars:
        stars = sorted(all_stars, key=_magnitude_key)[:max_stars]
        omitted = len(all_stars) - max_stars

    parts: list[str] = [
        f"style: {style}",
        f"lang: {lang}",
        "",
        "# 这张照片命中的元素",
        f"constellations: {json.dumps(context.get('constellations', []), ensure_ascii=False)}",
        f"bright_stars: {json.dumps(stars, ensure_ascii=False)}",
    ]
    if omitted:
        parts.append(f"（画面内另有 {omitted} 颗较暗星未列出，不必逐一提及）")

    capture = context.get("capture") or {}
    captured_at = capture.get("captured_at")
    place = capture.get("place")
    if captured_at or place:
        parts.extend(["", "# 拍摄信息"])
        if captured_at:
            parts.append(f"captured_at: {captured_at}")
        if place:
            parts.append(f"place: {place}")
        # 模型拿到地名/月份就爱现编"当地传说"，这里显式压一句（人设在 AgentArts 侧，改不动）
        parts.append("（拍摄信息只用于判断季节与方位，不要据此编造地方传说或额外地名。）")

    center = context.get("center")
    if center:
        parts.append(f"center_ra: {center.get('ra')}, dec: {center.get('dec')}")
    field = context.get("field")
    if field:
        parts.append(f"field: {field.get('width_deg')}x{field.get('height_deg')} deg")
    parts.extend([
        "",
        "请按系统提示词的要求，讲一个 3 段的星空故事。",
    ])
    return "\n".join(parts)
