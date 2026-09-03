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


def _build_user_content(context: dict, style: str, lang: str) -> str:
    """拼 AgentArts user_content（spec §7.3 骨架）。

    字段顺序：
      1. style / lang 元信息
      2. constellations / bright_stars JSON dump（constellations 含 mansion 字段以告知中文星官归属）
      3. 可选 center / field
      4. 末尾引导句

    Args:
        context: 含 constellations / bright_stars / center? / field? 的 dict。
        style: "myth" | "science"。
        lang: "zh"。

    Returns:
        多行字符串，发给 AgentArts 作为 user_content。
    """
    parts: list[str] = [
        f"style: {style}",
        f"lang: {lang}",
        "",
        "# 这张照片命中的元素",
        f"constellations: {json.dumps(context.get('constellations', []), ensure_ascii=False)}",
        f"bright_stars: {json.dumps(context.get('bright_stars', []), ensure_ascii=False)}",
    ]
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
