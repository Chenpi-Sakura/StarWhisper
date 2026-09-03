"""Constellation data lookup.

The single source of truth for atlas data is `server/data/constellations.json`.
Lookup is case-insensitive on the `abbr` field (both sides lowercased).
The file path is resolved relative to this module so that pytest,
uvicorn --reload and the bundled `pyinstaller` build all see the same file.
"""

import json
from pathlib import Path

_DATA_PATH = Path(__file__).parent.parent / "data" / "constellations.json"
_data: dict = {}


def _load() -> None:
    """Lazy load the JSON file into the module-level cache."""
    global _data
    if not _data:
        _data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def get_constellation(abbr: str) -> dict | None:
    """Return the atlas entry for `abbr`, or None if not present.

    Matching is case-insensitive: callers may pass `ori` or `ORI`. The returned
    dict always includes an `ok: True` flag for the unified success envelope.
    """
    _load()
    target = abbr.lower()
    for entry in _data.values():
        if entry["abbr"].lower() == target:
            return {**entry, "ok": True}
    return None


def all_constellations() -> list[dict]:
    """Return every constellation entry (for diagnostics / listing)."""
    _load()
    return list(_data.values())


def list_constellations() -> list[dict]:
    """返回 5 星座 summary 列表（spec §3.4，复用 constellations.json，**不新建 JSON**）。

    字段缺失用 `.get(...) + 缺省值` 兜底（Ruling 3）；前端对应字段标 optional。
    返回每项含：
    - abbr / name / latin：必填
    - glyph / season / caption：可选，缺省空串
    - bright_stars：可选，缺省回退为 stars 字典长度（亮星总数）
    """
    _load()
    out: list[dict] = []
    for c in _data.values():
        out.append({
            "abbr": c.get("abbr", ""),
            "name": c.get("name", ""),
            "latin": c.get("latin", ""),
            "glyph": c.get("glyph", ""),
            "season": c.get("season", ""),
            "caption": c.get("caption", ""),
            "bright_stars": c.get(
                "bright_stars_mag_lt_35",
                len(c.get("stars", {})),
            ),
        })
    return out