"""星纹配图端点：POST 起 job、GET 轮询取图。

链路：故事流结束 → 前端 POST /api/artwork（带故事正文）→ 立即拿 job_id →
轮询 GET /api/artwork/{job_id} 直到 status=ready/error。

不在 HTTP 请求里等生成：上游同步接口实测 32–38s，占住 worker 会连带拖慢
故事与观星指数（单机只有 1 个事件循环）。生成侧另有并发闸门与熔断，
见 services/image_gen.py。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services import image_gen
from services.image_prompt import build_prompt
from services.story_throttle import check_rate_limit

router = APIRouter(prefix="/api/artwork", tags=["artwork"])

# 故事正文上限：模板本身会按 IMAGE_STORY_MAX_CHARS 截断，这里只是拒绝异常大的请求
STORY_INPUT_MAX = 4000


class ArtworkRequest(BaseModel):
    story: str = Field(default="", max_length=STORY_INPUT_MAX)
    lang: str = "zh"
    # 「换一张」置 true：跳过 prompt 缓存，重新向上游要一批候选
    cache_bust: bool = False


@router.post("")
async def start_artwork(request: Request, body: ArtworkRequest) -> dict:
    """登记一次生成任务。同故事重复请求命中缓存时直接返回 ready。"""
    check_rate_limit(request)
    story = body.story.strip()
    if not story:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_STORY", "message": "缺少故事正文"},
        )

    job = image_gen.start_job(build_prompt(story), use_cache=not body.cache_bust)
    return {
        "ok": True,
        "job_id": job.id,
        "status": job.status,
        "cached": job.cached,
        "model": job.model,
    }


@router.get("/{job_id}")
async def poll_artwork(job_id: str) -> dict:
    """轮询 job。生成失败也以 200 + status=error 返回，让前端统一处理。"""
    job = image_gen.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTWORK_JOB_NOT_FOUND", "message": "任务不存在或已过期"},
        )
    payload = {
        "ok": job.status == "ready",
        "job_id": job.id,
        "status": job.status,
        "model": job.model,
        "cached": job.cached,
        "images": job.images,
    }
    if job.status == "error":
        payload.update(error_code=job.error_code, error_message=job.error_message)
    if job.latency_ms is not None:
        payload["latency_ms"] = job.latency_ms
    return payload
