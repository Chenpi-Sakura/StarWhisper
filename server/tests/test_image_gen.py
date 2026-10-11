"""services/image_gen.py 单测：上游响应映射 + job 生命周期 + 缓存 + 熔断。

不碰真实网络：底层 HTTP 一律 httpx.MockTransport，job 路径直接 monkeypatch
`image_gen.generate`。asyncio_mode=auto（pytest.ini），所以 async 用例无需装饰器。
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from services import image_gen
from services.story_throttle import reset_all_circuits, reset_rate_limit_buckets


@pytest.fixture(autouse=True)
def _isolate():
    image_gen.reset_state()
    reset_rate_limit_buckets()
    reset_all_circuits()
    yield
    image_gen.reset_state()
    reset_rate_limit_buckets()
    reset_all_circuits()


def _mock_client(payload: dict, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/image_generation"
        assert request.headers["authorization"].startswith("Bearer ")
        body = json.loads(request.content.decode())
        assert body["model"] and body["prompt"] and 1 <= body["n"] <= 9
        return httpx.Response(status_code=status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _drain() -> None:
    if image_gen._TASKS:
        await asyncio.gather(*list(image_gen._TASKS))


# ---------- generate(): 上游响应映射 ----------


async def test_generate_returns_image_urls():
    async with _mock_client({
        "data": {"image_urls": ["https://x/1.jpg", "https://x/2.jpg"]},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }) as cli:
        assert await image_gen.generate("p", client=cli) == ["https://x/1.jpg", "https://x/2.jpg"]


async def test_generate_maps_balance_code():
    async with _mock_client({"base_resp": {"status_code": 1008, "status_msg": "insufficient balance"}}) as cli:
        with pytest.raises(image_gen.ImageGenError) as e:
            await image_gen.generate("p", client=cli)
    assert e.value.code == "IMAGE_NO_BALANCE"


async def test_generate_maps_unsafe_content():
    async with _mock_client({"base_resp": {"status_code": 1026, "status_msg": "sensitive"}}) as cli:
        with pytest.raises(image_gen.ImageGenError) as e:
            await image_gen.generate("p", client=cli)
    assert e.value.code == "IMAGE_UNSAFE_CONTENT"


async def test_generate_maps_unknown_code_to_upstream_error():
    async with _mock_client({"base_resp": {"status_code": 9999, "status_msg": "weird"}}) as cli:
        with pytest.raises(image_gen.ImageGenError) as e:
            await image_gen.generate("p", client=cli)
    assert e.value.code == "IMAGE_UPSTREAM_ERROR"


async def test_generate_rejects_non_200():
    async with _mock_client({}, status=503) as cli:
        with pytest.raises(image_gen.ImageGenError) as e:
            await image_gen.generate("p", client=cli)
    assert e.value.code == "IMAGE_UPSTREAM_ERROR"


async def test_generate_rejects_non_json_body():
    cli = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    async with cli:
        with pytest.raises(image_gen.ImageGenError) as e:
            await image_gen.generate("p", client=cli)
    assert e.value.code == "IMAGE_PARSE_ERROR"


# ---------- 出图尺寸：16:9 ----------


def _capturing_client(seen: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content.decode()))
        return httpx.Response(200, json={
            "data": {"image_urls": ["https://x/1.jpg"]},
            "base_resp": {"status_code": 0},
        })

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_generate_sends_explicit_width_height_when_configured():
    """aspect_ratio=16:9 预设只给 1280x720，铺整页底纹会糊，所以默认发显式尺寸。"""
    seen: dict = {}
    async with _capturing_client(seen) as cli:
        await image_gen.generate("p", client=cli)
    assert seen["width"] == image_gen.IMAGE_GEN_WIDTH
    assert seen["height"] == image_gen.IMAGE_GEN_HEIGHT
    assert "aspect_ratio" not in seen


async def test_generate_falls_back_to_aspect_preset(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(image_gen, "IMAGE_GEN_WIDTH", 0)
    monkeypatch.setattr(image_gen, "IMAGE_GEN_HEIGHT", 0)
    async with _capturing_client(seen) as cli:
        await image_gen.generate("p", client=cli)
    assert seen["aspect_ratio"] == image_gen.IMAGE_GEN_ASPECT
    assert "width" not in seen


def test_default_aspect_is_widescreen_not_square():
    """回归护栏：曾经硬编码 1:1，铺成整页背景后观感很差。"""
    assert image_gen.IMAGE_GEN_ASPECT == "16:9"
    assert (image_gen.IMAGE_GEN_WIDTH, image_gen.IMAGE_GEN_HEIGHT) == (1920, 1080)


async def test_generate_rejects_empty_urls():
    async with _mock_client({"data": {"image_urls": []}, "base_resp": {"status_code": 0}}) as cli:
        with pytest.raises(image_gen.ImageGenError) as e:
            await image_gen.generate("p", client=cli)
    assert e.value.code == "IMAGE_EMPTY"


async def test_generate_without_key_is_disabled(monkeypatch):
    monkeypatch.setattr(image_gen, "IMAGE_GEN_MOCK", False)
    monkeypatch.setattr(image_gen, "IMAGE_GEN_API_KEY", "")
    with pytest.raises(image_gen.ImageGenError) as e:
        await image_gen.generate("p")
    assert e.value.code == "IMAGE_DISABLED"


async def test_mock_mode_returns_fixture_without_network(monkeypatch):
    monkeypatch.setattr(image_gen, "IMAGE_GEN_MOCK", True)
    assert await image_gen.generate("p") == image_gen._MOCK_IMAGES


# ---------- job 生命周期 ----------


async def test_start_job_pending_then_ready(monkeypatch):
    calls = []

    async def fake_generate(prompt, **kw):
        calls.append(prompt)
        return ["https://x/a.jpg"]

    monkeypatch.setattr(image_gen, "generate", fake_generate)
    job = image_gen.start_job("PROMPT")
    assert job.status == "pending"
    await _drain()
    assert job.status == "ready"
    assert job.images == ["https://x/a.jpg"]
    assert job.latency_ms is not None and calls == ["PROMPT"]


async def test_same_prompt_hits_cache_and_skips_upstream(monkeypatch):
    n = {"c": 0}

    async def fake_generate(prompt, **kw):
        n["c"] += 1
        return ["https://x/a.jpg"]

    monkeypatch.setattr(image_gen, "generate", fake_generate)
    first = image_gen.start_job("SAME")
    await _drain()
    assert first.status == "ready" and not first.cached

    second = image_gen.start_job("SAME")
    assert second.status == "ready"
    assert second.cached is True
    assert second.images == ["https://x/a.jpg"]
    await _drain()
    assert n["c"] == 1  # 第二次没再花钱


async def test_job_error_records_business_code(monkeypatch):
    async def boom(prompt, **kw):
        raise image_gen.ImageGenError("IMAGE_NO_BALANCE", "余额不足")

    monkeypatch.setattr(image_gen, "generate", boom)
    job = image_gen.start_job("P")
    await _drain()
    assert job.status == "error"
    assert job.error_code == "IMAGE_NO_BALANCE"
    assert job.images == []


async def test_unexpected_exception_becomes_upstream_down(monkeypatch):
    async def boom(prompt, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(image_gen, "generate", boom)
    job = image_gen.start_job("P")
    await _drain()
    assert job.status == "error"
    assert job.error_code == "IMAGE_UPSTREAM_DOWN"


async def test_breaker_opens_after_threshold_failures(monkeypatch):
    async def boom(prompt, **kw):
        raise image_gen.ImageGenError("IMAGE_UPSTREAM_ERROR", "x")

    monkeypatch.setattr(image_gen, "generate", boom)
    for i in range(image_gen._BREAKER._threshold):
        job = image_gen.start_job(f"P{i}")
        await _drain()
        assert job.status == "error"

    opened = image_gen.start_job("P-after-open")
    await _drain()
    assert opened.error_code == "IMAGE_CIRCUIT_OPEN"


async def test_success_closes_the_breaker(monkeypatch):
    async def ok(prompt, **kw):
        return ["https://x/a.jpg"]

    monkeypatch.setattr(image_gen, "generate", ok)
    image_gen._BREAKER.record_failure()
    image_gen._BREAKER.record_failure()
    job = image_gen.start_job("P")
    await _drain()
    assert job.status == "ready"
    assert image_gen._BREAKER.allow() is True


async def test_get_job_unknown_returns_none():
    assert image_gen.get_job("nope") is None


# ---------- 1026 审核误判：静默重投 + 不进熔断 ----------


async def test_unsafe_content_retries_once_and_recovers(monkeypatch):
    """上游审核是偶发误判：第一次被拒应静默重投，第二次成功就不该惊动前端。"""
    calls = {"n": 0}

    async def flaky(prompt, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise image_gen.ImageGenError("IMAGE_UNSAFE_CONTENT", "画面描述涉及敏感内容")
        return ["https://x/a.jpg"]

    monkeypatch.setattr(image_gen, "generate", flaky)
    job = image_gen.start_job("P")
    await _drain()
    assert calls["n"] == image_gen._UNSAFE_TRIES
    assert job.status == "ready"
    assert job.images == ["https://x/a.jpg"]


async def test_persistent_unsafe_content_keeps_breaker_shut(monkeypatch):
    """重投仍被拒才报错；但内容被拒不是服务故障，不该推进熔断计数。"""
    calls = {"n": 0}

    async def always_unsafe(prompt, **kw):
        calls["n"] += 1
        raise image_gen.ImageGenError("IMAGE_UNSAFE_CONTENT", "画面描述涉及敏感内容")

    monkeypatch.setattr(image_gen, "generate", always_unsafe)
    for i in range(image_gen._BREAKER._threshold + 1):
        job = image_gen.start_job(f"P{i}")
        await _drain()
        assert job.status == "error"
        assert job.error_code == "IMAGE_UNSAFE_CONTENT"

    assert calls["n"] == image_gen._UNSAFE_TRIES * (image_gen._BREAKER._threshold + 1)
    assert image_gen._BREAKER._consecutive_failures == 0
    assert image_gen._BREAKER.allow() is True


async def test_upstream_status_msg_is_not_leaked_to_caller():
    """上游原文（会点名被拒内容）只进 error.upstream 供日志，不进给前端的 message。"""
    async with _mock_client({"base_resp": {"status_code": 1026, "status_msg": "命中词：冥河"}}) as cli:
        with pytest.raises(image_gen.ImageGenError) as e:
            await image_gen.generate("p", client=cli)
    assert e.value.upstream == "命中词：冥河"
    assert "冥河" not in e.value.message


async def test_provider_summary_reflects_config():
    s = image_gen.provider_summary()
    assert s["model"] == image_gen.IMAGE_GEN_MODEL
    assert s["n"] >= 1 and s["concurrency"] >= 1
