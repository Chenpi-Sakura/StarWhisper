from fastapi import APIRouter

from config import (
    AGENTARTS_API_KEY,
    AGENTARTS_BASE_URL,
    AGENTARTS_RUNTIME_NAME,
    AI_API_KEY,
    AI_MODEL,
    ASTROMETRY_MOCK,
)

router = APIRouter()


@router.get('/api/health')
async def health():
    """M2 §9.3 扁平字段 + AgentArts v0.3。

    - astrometry: ``mock``（ASTROMETRY_MOCK=True）/ ``up``（走真实上游）
    - ai_provider: ``disabled``（无任何 AI 配置）/ ``up``（provider.health 通过）/
      ``down``（provider.health 失败）
    - ai_model: 当前模型/运行时名（无配置时为 ``none``）

    上游真实可达性探测交给调用方按需做（这里仅看启动期配置。
    AgentArts 已配置（API Key + runtime）时优先展示 agentarts 运行时。
    """
    has_any_ai = bool(AI_API_KEY or (AGENTARTS_API_KEY and AGENTARTS_BASE_URL and AGENTARTS_RUNTIME_NAME))
    if not has_any_ai:
        ai_state = 'disabled'
        ai_model = 'none'
    else:
        from services.ai_provider import make_provider
        provider = make_provider()
        ai_ok = await provider.health()
        ai_state = 'up' if ai_ok else 'down'
        if AGENTARTS_API_KEY and AGENTARTS_RUNTIME_NAME:
            ai_model = AGENTARTS_RUNTIME_NAME
        else:
            ai_model = AI_MODEL if AI_API_KEY else 'none'
    return {
        'ok': True,
        'astrometry': 'mock' if ASTROMETRY_MOCK else 'up',
        'ai_provider': ai_state,
        'ai_model': ai_model,
    }