"""Server runtime configuration.

All upstream service endpoints and integration secrets are read from
environment variables. M1 consumes Astrometry base URL + CORS origins;
M2 adds ASTROMETRY_MOCK fixture-mode switch and AI story provider config.
M2.5 adds AgentArts runtime config (AK/SK / runtime name / base URL).
AI keys / upstream secrets must never be hard-coded.

本地不做任何智能处理（EXIF/race/crop/FOV 都交给上游，API.md §1）；
仅保留上游 URL + 超时 + mock 开关 + AI 故事 provider 配置。
"""

import os
from pathlib import Path

# 轻量 .env 加载（无需 python-dotenv）：根目录 .env 存在时读入 os.environ。
# 已存在的环境变量优先，不覆盖（便于部署环境直接注入）。
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.is_file():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
        if _k and _k not in os.environ:
            os.environ[_k] = _v

# M2: Astrometry 私有化服务（plan v0.2+）；M1 仅占位
ASTROMETRY_SERVICE_URL = os.getenv("ASTROMETRY_SERVICE_URL", "http://117.72.38.57:8010")

# M2: ASTROMETRY_MOCK=1 启用 fixture 离线回退路径（spec §16.5）。
# 仅作为启动期显式开关，运行时不再探测；缺省 False 走真实上游。
ASTROMETRY_MOCK = os.getenv("ASTROMETRY_MOCK", "0") == "1"

# 前端 dev server 地址（M1 默认 Vite 端口）
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

# M2: 上游 /solve 单次请求超时（秒）。前端 65s 兜底，
# 此处 60s 让服务端能在前端 timeout 前返回 TIMEOUT 业务码（spec §3.1）。
ASTROMETRY_TIMEOUT = int(os.getenv("ASTROMETRY_TIMEOUT", "60"))

# M2: AI Provider 抽象层配置（spec §5.1 / §5.5）。
# AI_API_KEY 留空时 providers.ai_provider.make_provider() 返回 DisabledProvider，
# 路由层降级到 traditions/{key}/{abbr}.json 内嵌 stories 预设（P2-17：原
# preset_stories.json 已删除）。
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_BASE = os.getenv("AI_API_BASE", "https://api.deepseek.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")

# P2-13：故事 prompt 中星点截断上限（按星等取最亮 N 颗；
# 轩辕 70 星全塞会明显膨胀 token）。<=0 表示不截断。
STORY_PROMPT_MAX_STARS = int(os.getenv("STORY_PROMPT_MAX_STARS", "12"))

# M2.5: AgentArts 智能体运行时（spec 2026-08-24-starwhisper-agentarts.md）。
# 四项全非空时 make_provider() 优先返回 AgentArtsProvider（工作负载身份 AK/SK 签名）。
# M4: 观星指数——Open-Meteo 免费天气源（免 key）。仅环境变量可覆盖，
# 缺省即公开端点；失败由 services/weather.py 抛 WeatherUnavailable。
OPEN_METEO_URL = os.getenv(
    "OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast"
)
OPEN_METEO_TIMEOUT = float(os.getenv("OPEN_METEO_TIMEOUT", "10"))

AGENTARTS_API_KEY = os.getenv("AGENTARTS_API_KEY", "")
AGENTARTS_RUNTIME_NAME = os.getenv("AGENTARTS_RUNTIME_NAME", "")
AGENTARTS_BASE_URL = os.getenv("AGENTARTS_BASE_URL", "")

# AgentArts 智能体调用只有一个 `inputs.query` 入参，没有 system/developer 角色位。
# 平台侧若未配置人设，后端需把 system prompt 拼进 query 才会生效
# （myth_pool_rule 等按 tradition 分流的约束只存在于 system prompt 里）。
# 置 0 表示「人设已在平台侧配置」，后端只发 user prompt。
AGENTARTS_SYSTEM_IN_QUERY = os.getenv("AGENTARTS_SYSTEM_IN_QUERY", "1") == "1"

# 故事生成总时长预算（秒）。注意区分：
# provider 层的 30s 是 httpx **每 chunk 读超时**，上游持续推心跳时可以无限拖；
# 这里是端到端总预算，超时即熔断到 preset。
STORY_TOTAL_TIMEOUT = float(os.getenv("STORY_TOTAL_TIMEOUT", "45"))
# AI 故障熔断：连续失败 threshold 次后开启 cooldown 秒的冷却窗口，
# 冷却期内直接走 preset，不再让每个请求干等满超时（spec §5.4 degraded 不缓存）。
STORY_CB_THRESHOLD = int(os.getenv("STORY_CB_THRESHOLD", "3"))
STORY_CB_COOLDOWN = float(os.getenv("STORY_CB_COOLDOWN", "60"))

# 故事接口限流（按客户端 IP 固定窗口）。STORY_RATE_LIMIT<=0 表示不限流。
STORY_RATE_LIMIT = int(os.getenv("STORY_RATE_LIMIT", "60"))
STORY_RATE_WINDOW = float(os.getenv("STORY_RATE_WINDOW", "60"))

# ---------- 星纹配图（MiniMax 文生图）----------
# 上游只有 POST /v1/image_generation 一个同步端点（无异步任务查询接口），
# 实测单次 15–40s；key 仅国内站 api.minimax.cn 有效（打 .io 返 2049）。

IMAGE_GEN_API_BASE = os.getenv("IMAGE_GEN_API_BASE", "https://api.minimax.cn")
IMAGE_GEN_API_KEY = os.getenv("IMAGE_GEN_API_KEY", "")
# image-01：构图可控、支持 width/height；image-01-live：快一倍但 style 预设会
# 压过提示词里的叙事结构（实测会把"勺形"画丢），故定 image-01。
IMAGE_GEN_MODEL = os.getenv("IMAGE_GEN_MODEL", "image-01")
# 出图尺寸。aspect_ratio 预设最高只给 1280x720（16:9 实测），铺满整页当底纹会发糊；
# image-01 支持显式 width/height（[512,2048] 且 8 的倍数）。1920x1080 的 n=4 实测
# 34–37s，与旧的 1024x1024（~33s）持平，却同时拿到 16:9 和翻倍的像素。
# 两者二选一：width+height 都非 0 就发显式尺寸，否则退回 aspect_ratio 预设。
IMAGE_GEN_ASPECT = os.getenv("IMAGE_GEN_ASPECT", "16:9")
IMAGE_GEN_WIDTH = int(os.getenv("IMAGE_GEN_WIDTH", "1920"))
IMAGE_GEN_HEIGHT = int(os.getenv("IMAGE_GEN_HEIGHT", "1080"))
# 单次生成超时（秒）。实测 32–38s，留足余量。
IMAGE_GEN_TIMEOUT = float(os.getenv("IMAGE_GEN_TIMEOUT", "90"))
# 每次 job 出几张候选做拒绝采样：提示词再怎么调，单张仍有约 1/3 概率画出
# 星座连线/伪文字，n=4 时至少一张干净的概率约 98%。
IMAGE_GEN_N = int(os.getenv("IMAGE_GEN_N", "4"))
# 全局并发闸门（backlog 里那条唯一 P0「spec 写了代码没跟上」）。
# 单机 uvicorn 只有 1 个事件循环，占满即 429 BUSY 而不是排队拖垮故事接口。
IMAGE_GEN_CONCURRENCY = int(os.getenv("IMAGE_GEN_CONCURRENCY", "3"))
# 端到端预算：job 从提交到出图最多允许多久，超时置 error 并计一次熔断失败。
IMAGE_GEN_JOB_TIMEOUT = float(os.getenv("IMAGE_GEN_JOB_TIMEOUT", "120"))
# 已完成 job 在内存里的保留时长（秒）。前端轮询窗口远小于此。
IMAGE_GEN_JOB_TTL = float(os.getenv("IMAGE_GEN_JOB_TTL", "600"))
# 故事正文进 prompt 的字符预算（模板固定部分约 420 字，接口上限 1500）。
IMAGE_STORY_MAX_CHARS = int(os.getenv("IMAGE_STORY_MAX_CHARS", "900"))
# =1 走 fixture，不打真实上游（离线演示 / 单测）。
IMAGE_GEN_MOCK = os.getenv("IMAGE_GEN_MOCK", "0") == "1"