"""预设故事 fallback（spec §5.3 / §16.4）。

T7 (atlas tradition): 改为从 traditions 数据取 story（每个 constellation JSON 已有 stories 内嵌）。
不再读 preset_stories.json（已删）。

每个 constellation 的 `stories.{style}` 是一段预设（仅 myth / science 两类视角）。
未填的走占位（空段落 + title="尚未撰写"）。
"""
from __future__ import annotations

from typing import Optional


def get_preset(abbr: str, style: str) -> Optional[dict]:
    """返回 (abbr, style) 对应的预设故事；不存在则 None。

    Args:
        abbr: 星座缩写（ori / cyg / sco / leo / and），跨 tradition 查找。
        style: 视角（myth / science）。

    Returns:
        含 `title` 与 `paragraphs` 的 dict；缺失则 None。
    """
    from services.traditions import list_traditions, get_constellation
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


def clear_cache() -> None:
    """清空 traditions 缓存（测试用；通过调用 _load_all 重置）。"""
    from services.traditions import _DATA, _LOCK
    with _LOCK:
        _DATA.clear()
