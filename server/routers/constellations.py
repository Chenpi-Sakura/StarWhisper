"""Constellation list endpoint.

GET /api/constellations?tradition=western — required query param.

响应：{"tradition": X, "tradition_meta": {...}, "items": [...]}
tradition_meta 是字段白名单子集（不含 count / key），spec v4 任务 3。
"""
from fastapi import APIRouter, HTTPException, Query

from services.traditions import get_meta, list_constellations

router = APIRouter(prefix="/api/constellations", tags=["constellations"])

META_WHITELIST = (
    "label", "label_en", "description", "epoch", "source", "license",
    "coordinate_system",
)


@router.get("")
async def constellations(tradition: str = Query(..., min_length=1)):
    """列出指定 tradition 的所有星座。"""
    trad_key = tradition.lower()
    meta = get_meta(trad_key) or {}
    tradition_meta = {k: meta[k] for k in META_WHITELIST if k in meta}
    items = list_constellations(trad_key)
    return {
        "tradition": trad_key,
        "tradition_meta": tradition_meta,
        "items": items,
    }
