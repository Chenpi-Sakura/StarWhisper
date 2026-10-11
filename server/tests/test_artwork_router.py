"""routers/artwork.py 端点测试。

约定同项目其余路由：module 级 `client = TestClient(app)`，错误体形状
`{"detail": {"code", "message"}}`，provider 层用 monkeypatch 打桩。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from services import image_gen
from services.story_throttle import reset_rate_limit_buckets

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate():
    image_gen.reset_state()
    reset_rate_limit_buckets()
    yield
    image_gen.reset_state()
    reset_rate_limit_buckets()


async def _fake_generate(prompt: str, **kw):
    return ["https://x/1.jpg", "https://x/2.jpg"]


def _start(story: str = "北天那头巨大的铁熊探出脊背。") -> dict:
    r = client.post("/api/artwork", json={"story": story, "lang": "zh"})
    assert r.status_code == 200, r.text
    return r.json()


def _poll_until_settled(job_id: str, tries: int = 50) -> dict:
    """后台 job 在 TestClient 的 loop 上跑；每次 GET 都会让出控制权，轮几次即可收敛。"""
    body: dict = {}
    for _ in range(tries):
        body = client.get(f"/api/artwork/{job_id}").json()
        if body.get("status") != "pending":
            return body
    return body


def test_post_returns_job_id_immediately():
    with patch.object(image_gen, "generate", _fake_generate):
        body = _start()
    assert body["ok"] is True
    assert body["job_id"] and len(body["job_id"]) == 32
    assert body["status"] in ("pending", "ready")
    assert body["cached"] is False


def test_post_wraps_story_into_the_prompt_template():
    """路由必须把故事交给模板，而不是原样透传。"""
    seen = {}

    def spy_start(prompt: str, **kw):
        seen["prompt"] = prompt
        return image_gen.ArtworkJob(id="x" * 32, status="pending")

    with patch.object(image_gen, "start_job", spy_start):
        _start("铁熊与旅人的故事")
    p = seen["prompt"]
    assert "铁熊与旅人的故事" in p
    assert "【画风】" in p and "【严禁】" in p
    assert p.index("铁熊与旅人的故事") < p.index("【画风】")


def test_empty_story_is_400():
    for blank in ("", "   ", "\n\n"):
        r = client.post("/api/artwork", json={"story": blank})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "EMPTY_STORY"


def test_oversized_story_is_rejected_before_template():
    r = client.post("/api/artwork", json={"story": "星" * 5000})
    assert r.status_code == 422  # pydantic max_length，不进入生成


def test_get_unknown_job_is_404():
    r = client.get("/api/artwork/deadbeef")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "ARTWORK_JOB_NOT_FOUND"


def test_poll_ready_job_returns_images():
    with patch.object(image_gen, "generate", _fake_generate):
        job_id = _start()["job_id"]
    for _ in range(50):
        body = client.get(f"/api/artwork/{job_id}").json()
        if body["status"] != "pending":
            break
    assert body["status"] == "ready"
    assert body["ok"] is True
    assert body["images"] == ["https://x/1.jpg", "https://x/2.jpg"]
    assert body["latency_ms"] >= 0


def test_poll_error_job_reports_business_code():
    async def boom(prompt: str, **kw):
        raise image_gen.ImageGenError("IMAGE_NO_BALANCE", "账号余额不足")

    with patch.object(image_gen, "generate", boom):
        body = _poll_until_settled(_start()["job_id"])
    assert body["status"] == "error"
    assert body["ok"] is False
    assert body["error_code"] == "IMAGE_NO_BALANCE"
    assert body["images"] == []


def test_rate_limit_short_circuits():
    with patch("routers.artwork.check_rate_limit",
               side_effect=HTTPException(429, detail={"code": "RATE_LIMITED", "message": "too fast"})):
        r = client.post("/api/artwork", json={"story": "任意故事"})
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "RATE_LIMITED"


def test_cache_bust_skips_the_prompt_cache():
    """「换一张」必须绕过 prompt 缓存，否则重掷永远拿回同一批图。"""
    story = "北天那头巨大的铁熊探出脊背。"
    with patch.object(image_gen, "generate", _fake_generate):
        _poll_until_settled(_start(story)["job_id"])
        cached = client.post("/api/artwork", json={"story": story}).json()
        assert cached["cached"] is True
        reroll = client.post("/api/artwork", json={"story": story, "cache_bust": True}).json()
        assert reroll["cached"] is False


def test_mock_mode_end_to_end(monkeypatch):
    """IMAGE_GEN_MOCK=1 时整条链路不碰网络也能出图（离线演示路径）。"""
    monkeypatch.setattr(image_gen, "IMAGE_GEN_MOCK", True)
    body = _start()
    poll = client.get(f"/api/artwork/{body['job_id']}").json()
    assert poll["status"] == "ready"
    assert poll["images"] == image_gen._MOCK_IMAGES
