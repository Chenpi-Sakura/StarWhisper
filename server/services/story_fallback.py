"""预设故事 fallback（spec §5.3 / §16.4）。

T7 (atlas tradition): 改为从 traditions 数据取 story（每个 constellation JSON 已有 stories 内嵌）。
不再读 preset_stories.json（已删）。

每个 constellation 的 `stories.{style}` 是一段预设（仅 myth / science 两类视角）。
未填的走占位（空段落 + title="尚未撰写"）。

P2-12：get_preset 支持显式 tradition——传了只在该 tradition 内查；
不传保持向后兼容（跨 tradition 首命中）。
P2-15：删除 clear_cache()——它会误清 services.traditions._DATA 全局缓存，
生产误调即全量重载；测试需重置时直接操作 traditions 模块。
"""
from __future__ import annotations

from typing import Optional


def get_preset(abbr: str, style: str, tradition: str | None = None) -> Optional[dict]:
    """返回 (tradition, abbr, style) 对应的预设故事；不存在则 None。

    Args:
        abbr: 星座缩写（ori / cyg / sco / leo / and ...）。
        style: 视角（myth / science）。
        tradition: P2-12 可选 tradition key；缺省时跨 tradition 首命中。

    Returns:
        含 `title` 与 `paragraphs` 的 dict；缺失则 None。
    """
    from services.traditions import list_traditions, get_constellation

    if tradition:
        entry = get_constellation(tradition, abbr)
        if entry is not None:
            stories = entry.get("stories", {})
            view_entry = stories.get(style)
            if view_entry:
                return {
                    "title": view_entry.get("title", "尚未撰写"),
                    "paragraphs": view_entry.get("paragraphs", []),
                }
        return None

    for t in list_traditions():
        entry = get_constellation(t["key"], abbr)
        if entry is None:
            continue
        stories = entry.get("stories", {})
        view_entry = stories.get(style)
        if view_entry:
            return {
                "title": view_entry.get("title", "尚未撰写"),
                "paragraphs": view_entry.get("paragraphs", []),
            }
    return None
