"""FastAPI entry point for StarWhisper server.

M1 mounts the constellation router; T2 adds identify; T3 adds story +
constellations list; T5 adds health (spec §9.3 扁平字段).
T7 (atlas tradition) rewires list/detail endpoints by tradition + adds /api/traditions.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS
from routers import constellation, constellations, health, identify, index, story, traditions
from services.ai_provider import AgentArtsProvider, OpenAICompatibleProvider
from services import traditions as _trad_svc

logger = logging.getLogger(__name__)
# 确保在没有外部 logging 配置（如 uvicorn 默认）时也能输出
if not logger.handlers and not logger.parent.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

app = FastAPI(title="StarWhisper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(constellation.router)
app.include_router(identify.router)
app.include_router(constellations.router)
app.include_router(story.router)
app.include_router(health.router)
app.include_router(traditions.router)
app.include_router(index.router)


@app.on_event("startup")
def _load_traditions():
    """T7: 启动时显式加载 tradition 数据（double-check locking 内部处理）。

    spec v4 任务 5：加载后输出加载摘要，并提示 _load_all 是 idempotent。
    """
    from services.traditions import _load_all

    _load_all()

    # spec v4 任务 5：startup 日志输出加载摘要（模块引用访问以避免静态分析误判）
    if _trad_svc._DATA is None or _trad_svc._META is None:
        logger.error("traditions 加载失败：_DATA/_META 为空")
        return

    summary_lines = ["traditions 加载摘要:"]
    for key, meta in _trad_svc._META.items():
        entries = _trad_svc._DATA.get(key, {})
        summary_lines.append(
            f"  {key}: {len(entries)} stars, "
            f"label={meta.get('label')!r}, "
            f"star_count={meta.get('star_count')}"
        )
    logger.info("\n".join(summary_lines))

    logger.info(
        "注意：_load_all 是 idempotent，运行时坏 JSON 不会重试。"
        "修复后需重启服务。"
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    # 释放 AI httpx 连接池，避免连接数累积（spec §5.1）
    await OpenAICompatibleProvider.aclose()
    await AgentArtsProvider.aclose()
