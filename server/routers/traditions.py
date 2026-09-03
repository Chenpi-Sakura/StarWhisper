"""Traditions list endpoint.

GET /api/traditions — returns [{key, label, label_en?, description?, ..., count}, ...]

count 是 len(_DATA[key]) 实时计算；_meta 由 _meta.json 提供（spec v4 任务 2）。
"""
from fastapi import APIRouter

from services import traditions as _trad_svc
from services.traditions import _load_all

router = APIRouter(prefix="/api/traditions", tags=["traditions"])


@router.get("")
async def traditions_endpoint():
    """列出所有 tradition + 元数据。

    响应：[{key, label, label_en?, description?, ..., count}, ...]
    count 是 len(_DATA[key]) 实时计算。

    **注意**：必须通过 ``_trad_svc._DATA`` / ``_trad_svc._META`` 访问，
    不能 ``from services.traditions import _DATA``——那是 import-time 拷贝，
    后续 _load_all() 通过 global 赋的值不可见。
    """
    _load_all()
    meta_map = _trad_svc._META
    data_map = _trad_svc._DATA
    if meta_map is None or data_map is None:
        return []

    result = []
    for key, meta in meta_map.items():
        item = {**meta, "count": len(data_map.get(key, {}))}
        result.append(item)
    return result
