"""Constellation detail endpoint.

GET /api/constellation/{tradition}/{abbr} — 404 if not found.

支持 ``?include_stories=false`` 查询参数以跳过 stories 字段（节约 token 用），
默认 true 返回完整 stories（spec v4 任务 3）。
"""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from services.traditions import get_constellation

router = APIRouter(prefix="/api/constellation", tags=["constellation"])


@router.get("/{tradition}/{abbr}")
async def get_constellation_endpoint(
    tradition: str,
    abbr: str,
    include_stories: bool = Query(True, description="是否包含 stories 字段"),
):
    entry = get_constellation(tradition, abbr)
    if entry is None:
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "code": "CONSTELLATION_NOT_FOUND",
                "message": "未收录此星座",
                "advice": "请检查 tradition 与 abbr，或在后续版本加入",
            },
        )
    result = dict(entry)
    if not include_stories:
        result["stories"] = None
    return result
