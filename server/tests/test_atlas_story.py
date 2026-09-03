"""POST /api/atlas-story 与 /api/atlas-story/stream 端点测试（spec §3.2）。

保留原 /api/story atlas 语义：单 (tradition, abbr, style) 输入；preset fallback。
Task 3 (2026-09-03)：从 routers/story.py 拆分出来的 atlas 路径。
"""
from __future__ import annotations

import json as _json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


# ---------- 来自 task-3 brief 的 3 个基本测试 ----------


def test_atlas_story_basic():
    """最小 atlas 请求合法。"""
    with patch("services.ai_provider.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = False  # 走 preset fallback
        provider.chat_stream = AsyncMock(side_effect=Exception("not called"))
        mp.return_value = provider

        r = client.post(
            "/api/atlas-story",
            json={"abbr": "ori", "style": "myth", "lang": "zh"},
        )
        # 即使走 fallback，HTTP 200
        assert r.status_code == 200


def test_atlas_story_invalid_style_returns_400():
    """非法 style → 400。"""
    r = client.post(
        "/api/atlas-story",
        json={"abbr": "ori", "style": "invalid", "lang": "zh"},
    )
    assert r.status_code in (400, 422)
    body = r.json()
    assert "INVALID_STYLE" in str(body)


def test_atlas_story_sse_has_at_least_one_event():
    """SSE 流至少含 title 或 error 事件。"""
    with patch("services.ai_provider.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = False
        provider.chat_stream = AsyncMock(side_effect=Exception("not called"))
        mp.return_value = provider

        with client.stream(
            "POST", "/api/atlas-story",
            json={"abbr": "ori", "style": "myth", "lang": "zh"},
        ) as r:
            assert r.status_code == 200
            text = ""
            for chunk in r.iter_text():
                text += chunk
            # 必须含 SSE 帧
            assert "event:" in text


# ---------- 从 test_agentarts.py 迁移来的 SSE 端点测试 ----------
# Task 2 (commit 18dc2c9) 把 /api/story/stream 删除，Task 3 在
# /api/atlas-story/stream 上恢复这条 P2-16 字符级协议；
# 下面这两个测试在原文件里被标 integration，本任务迁到 atlas_story.py 并解除标记。


class _MockSuccessProvider:
    name = "mock-success"

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        return "测试标题：猎户永不相见\n\n这是真实 AI 返回的第一段文字。\n\n这是真实 AI 返回的第二段文字。"

    async def health(self) -> bool:
        return True


def _clear_cache() -> None:
    from routers.atlas_story import _CACHE_LOCK, _STORY_CACHE

    with _CACHE_LOCK:
        _STORY_CACHE.clear()


@pytest.fixture(autouse=True)
def _reset_atlas_cache():
    _clear_cache()
    yield
    _clear_cache()


def test_stream_sse_title_char_done(monkeypatch):
    """P2-16 字符级 SSE 流：title → char ×N → done。

    Task 3 (2026-09-03)：路径由 /api/story/stream 迁到 /api/atlas-story/stream。
    """
    import routers.atlas_story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockSuccessProvider())
    _clear_cache()
    c = TestClient(app)
    with c.stream(
        "POST", "/api/atlas-story/stream",
        json={"abbr": "ori", "style": "myth"},
    ) as r:
        assert r.status_code == 200
        text = r.read().decode("utf-8")
    assert "event: title" in text
    assert "event: char" in text
    assert "event: done" in text
    # P2-16：字符级协议下 char 事件单个字符一个 JSON 帧；
    # 把所有 char 事件的 data 解析出来再断言内容（preset 含"永不相见"典故）
    char_text_parts: list[str] = []
    for frame in text.split("\n\n"):
        for line in frame.split("\n"):
            if line.startswith("data:"):
                try:
                    obj = _json.loads(line[len("data:"):].strip())
                    if "char" in obj:
                        char_text_parts.append(obj["char"])
                except _json.JSONDecodeError:
                    pass
    body_text = "".join(char_text_parts)
    # T7: preset 来源改为 traditions 内嵌 brief；内容含"永不相见"典故
    assert "永不相见" in body_text


def test_stream_sse_invalid_abbr_returns_404(monkeypatch):
    """未知星座 → 404 HTTP（校验在端点入口，未进 SSE 流）。

    Task 3 (2026-09-03)：路径由 /api/story/stream 迁到 /api/atlas-story/stream。
    """
    import routers.atlas_story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockSuccessProvider())
    _clear_cache()
    c = TestClient(app)
    r = c.post("/api/atlas-story/stream", json={"abbr": "draco", "style": "myth"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CONSTELLATION_NOT_FOUND"