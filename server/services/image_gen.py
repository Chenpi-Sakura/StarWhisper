"""MiniMax 文生图 client + 内存 job 表。

为什么是 job 轮询而不是同步返回：上游 `/v1/image_generation` 是**同步**接口，
实测单次 32–38s，而且没有异步任务查询端点。把它挂在 HTTP 请求上会占住 worker
几十秒，所以这里用 `asyncio.create_task` + 进程内 job 表，前端拿 job_id 轮询。

`n` 不影响耗时：实测 n=1 与 n=4 都是 ~33s（上游内部并行出图），所以多要几张
只多花钱、不多等时间——这是本服务敢一次出 4 张的原因。

进程内、无落盘：与项目其余部分一致（没有任何数据库，照片也只走内存）。
job 与图片 URL 都有 TTL——上游 URL 本身 24 小时过期，所以生成的图只适合
"当场看、当场存"，不能当持久素材地址。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field

import httpx
from cachetools import TTLCache

from config import (
    IMAGE_GEN_API_BASE,
    IMAGE_GEN_API_KEY,
    IMAGE_GEN_ASPECT,
    IMAGE_GEN_CONCURRENCY,
    IMAGE_GEN_HEIGHT,
    IMAGE_GEN_JOB_TIMEOUT,
    IMAGE_GEN_JOB_TTL,
    IMAGE_GEN_MOCK,
    IMAGE_GEN_MODEL,
    IMAGE_GEN_N,
    IMAGE_GEN_TIMEOUT,
    IMAGE_GEN_WIDTH,
)
from services.story_throttle import get_circuit

logger = logging.getLogger(__name__)

# 上游 base_resp.status_code → 本服务业务码（spec §9 风格：调用方只看 code）
_UPSTREAM_CODES = {
    1002: ("IMAGE_RATE_LIMITED", "上游限流，请稍后再试"),
    1004: ("IMAGE_AUTH_FAILED", "接口鉴权失败"),
    1008: ("IMAGE_NO_BALANCE", "账号余额不足"),
    1026: ("IMAGE_UNSAFE_CONTENT", "画面描述涉及敏感内容"),
    2013: ("IMAGE_BAD_REQUEST", "生成参数不合法"),
    2049: ("IMAGE_AUTH_FAILED", "无效的 api key"),
}

# 上游文本安全分类器的误判码。实测一条完全干净的七夕故事 prompt 连打 10 次全
# 部通过，说明 1026 是偶发的、与文本无确定映射的误杀——所以它既不算服务故障
# （不进熔断），也值得静默重投一次。
_UNSAFE = "IMAGE_UNSAFE_CONTENT"
_UNSAFE_TRIES = 2

# mock 模式复用的本地静态样张（前端 /samples 下已存在，离线演示可直出）
_MOCK_IMAGES = ["/samples/orion.jpg"]


class ImageGenError(Exception):
    """上游或配置层面的失败，携带业务码与用户可读信息。

    `upstream` 只用于服务端日志：上游 1026 的 `status_msg` 会点名被拒的内容，
    但它不该出现在给前端的响应里。
    """

    def __init__(self, code: str, message: str, *, upstream: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.upstream = upstream


@dataclass
class ArtworkJob:
    id: str
    status: str = "pending"  # pending | ready | error
    images: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    model: str = IMAGE_GEN_MODEL
    cached: bool = False
    latency_ms: int | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()


_JOBS: dict[str, ArtworkJob] = {}
# 同一 prompt（=同一故事）重复请求直接复用已生成的图，避免反复烧钱
_CACHE: TTLCache = TTLCache(maxsize=32, ttl=IMAGE_GEN_JOB_TTL)
_SEM: asyncio.Semaphore | None = None
_TASKS: set[asyncio.Task] = set()


def _semaphore() -> asyncio.Semaphore:
    """懒建：模块导入时可能还没有事件循环（TestClient / pytest）。"""
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(max(1, IMAGE_GEN_CONCURRENCY))
    return _SEM


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(IMAGE_GEN_TIMEOUT, connect=10.0))


def prompt_key(prompt: str) -> str:
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16]


async def generate(prompt: str, *, client: httpx.AsyncClient | None = None) -> list[str]:
    """打一次上游，返回图片 URL 列表。失败一律抛 ImageGenError。"""
    if IMAGE_GEN_MOCK:
        return list(_MOCK_IMAGES)
    if not IMAGE_GEN_API_KEY:
        raise ImageGenError("IMAGE_DISABLED", "未配置图片生成密钥")

    body = {
        "model": IMAGE_GEN_MODEL,
        "prompt": prompt,
        "response_format": "url",
        "n": max(1, min(9, IMAGE_GEN_N)),
        "prompt_optimizer": False,
        # 画面里不烧水印：UI 侧另有"AI 生成"标识，避免双重标记破坏版式
        "aigc_watermark": False,
    }
    if IMAGE_GEN_WIDTH and IMAGE_GEN_HEIGHT:
        body["width"] = IMAGE_GEN_WIDTH
        body["height"] = IMAGE_GEN_HEIGHT
    else:
        body["aspect_ratio"] = IMAGE_GEN_ASPECT
    owns = client is None
    cli = client or _client()
    try:
        r = await cli.post(
            f"{IMAGE_GEN_API_BASE}/v1/image_generation",
            json=body,
            headers={"Authorization": f"Bearer {IMAGE_GEN_API_KEY}"},
        )
    finally:
        if owns:
            await cli.aclose()
    if r.status_code != 200:
        raise ImageGenError("IMAGE_UPSTREAM_ERROR", f"上游 HTTP {r.status_code}")
    try:
        out = r.json()
    except ValueError:
        raise ImageGenError("IMAGE_PARSE_ERROR", "上游响应不是 JSON") from None

    base = out.get("base_resp") or {}
    code = base.get("status_code", 0)
    if code != 0:
        upstream = str(base.get("status_msg") or "")
        biz, msg = _UPSTREAM_CODES.get(code, ("IMAGE_UPSTREAM_ERROR", upstream or "上游返回错误"))
        # 前端只看业务码；上游原文只落日志，否则 1026 这类误判无法回溯到具体措辞
        logger.warning("image_gen upstream code=%s biz=%s msg=%s prompt=%s",
                       code, biz, upstream, prompt_key(prompt))
        if biz == _UNSAFE:
            logger.warning("image_gen rejected prompt: %s", prompt)
        raise ImageGenError(biz, msg, upstream=upstream)
    urls = (out.get("data") or {}).get("image_urls") or []
    if not urls:
        raise ImageGenError("IMAGE_EMPTY", "上游未返回图片")
    return urls


_BREAKER = get_circuit("image")


def _fail(job: ArtworkJob, code: str, message: str) -> None:
    job.status = "error"
    job.error_code = code
    job.error_message = message
    job.touch()


async def _run(job: ArtworkJob, prompt: str) -> None:
    """后台执行一次生成：闸门 → 熔断 → 上游 → 写回 job。"""
    started = time.time()
    async with _semaphore():
        if time.time() - started > IMAGE_GEN_JOB_TIMEOUT:
            _fail(job, "IMAGE_TIMEOUT", "排队超时，请稍后再试")
            return
        if not _BREAKER.allow():
            _fail(job, "IMAGE_CIRCUIT_OPEN", "图片服务暂时不可用")
            return

        urls: list[str] | None = None
        for attempt in range(1, _UNSAFE_TRIES + 1):
            try:
                urls = await generate(prompt)
                break
            except ImageGenError as e:
                if e.code == _UNSAFE:
                    # 审核误判是偶发的：静默重投一次，仍被拒才把错误抛给前端
                    if attempt < _UNSAFE_TRIES:
                        logger.info("image_gen unsafe, retrying (attempt %s)", attempt + 1)
                        continue
                    _fail(job, e.code, e.message)
                    return
                _BREAKER.record_failure()
                _fail(job, e.code, e.message)
                return
            except Exception as e:  # 网络层异常（httpx.TimeoutException 等）
                _BREAKER.record_failure()
                _fail(job, "IMAGE_UPSTREAM_DOWN", f"图片服务不可达：{type(e).__name__}")
                return

        if urls is None:
            return
        _BREAKER.record_success()
        _CACHE[prompt_key(prompt)] = urls
        job.status = "ready"
        job.images = urls
        job.latency_ms = int((time.time() - started) * 1000)
        job.touch()


def _sweep() -> None:
    """回收过期 job（每次入口调用顺手做一次，不额外起定时器）。"""
    now = time.time()
    for jid in [k for k, v in _JOBS.items() if now - v.updated_at > IMAGE_GEN_JOB_TTL]:
        _JOBS.pop(jid, None)


def start_job(prompt: str, use_cache: bool = True) -> ArtworkJob:
    """登记一个 job 并（必要时）拉起后台任务；立即返回，不阻塞请求。

    `use_cache=False` 供前端「换一张」用：同一 prompt 直接回缓存会让重掷失效，
    而方差恰恰是这个功能的主要成本来源——prompt 约束压不住上游画星图连线/伪文字的
    倾向，单张干净率实测约 1/4，只能靠一次出 4 张让用户挑（至少一张干净 ≈ 99%）。
    """
    _sweep()
    cached = _CACHE.get(prompt_key(prompt)) if use_cache else None
    if cached:
        job = ArtworkJob(id=uuid.uuid4().hex, status="ready", images=list(cached), cached=True,
                         latency_ms=0)
        _JOBS[job.id] = job
        return job

    job = ArtworkJob(id=uuid.uuid4().hex)
    _JOBS[job.id] = job
    task = asyncio.create_task(_run(job, prompt))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return job


def get_job(job_id: str) -> ArtworkJob | None:
    _sweep()
    return _JOBS.get(job_id)


def reset_state() -> None:
    """测试夹具用：清空 job / 缓存 / 熔断器。"""
    _JOBS.clear()
    _CACHE.clear()
    _BREAKER.reset()


def provider_summary() -> dict:
    """给 /api/health 之类的诊断用（不发探测请求，避免白烧一次生成）。"""
    return {
        "enabled": bool(IMAGE_GEN_API_KEY) or IMAGE_GEN_MOCK,
        "model": IMAGE_GEN_MODEL,
        "mock": IMAGE_GEN_MOCK,
        "n": IMAGE_GEN_N,
        "concurrency": IMAGE_GEN_CONCURRENCY,
    }
