"""POST /api/story photo-level 端点测试（spec §3.1 / §6）。

覆盖：
- 入参 schema（PhotoStoryRequest）
- SSE 字符级协议（title → char ×N → done）
- 错误传播（AI 失败 → event:error，不发 title/char）
- 缓存命中（cache_bust=false 二次请求走 cache）
- 缓存旁路（cache_bust=true）
- 参数错（context 空 → 400 EMPTY_CONTEXT）
- 熔断器（AI_CIRCUIT_OPEN → event:error）

注：mock ai_provider.chat_stream，避免真 AI 依赖。

chat_stream mock 签名采用 3 参形式 `(system, user, on_delta)` 与
`server/services/ai_provider.py` 实际签名保持一致——photo-level 调用方
传入 `system=""`（AgentArts 后台已注入人设）。
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_module_state():
    """每个用例前后清 LRU + 重置熔断器，避免用例间状态泄漏。

    brief 的测试假设 fresh state（同 _BASE_REQ 时 cache_hit vs cache_bust vs error
    三类断言互不干扰）；autouse 是最小代价——既不改 brief 的断言，也不改 fixture 结构。
    """
    import routers.story as story_mod

    with story_mod._CACHE_LOCK:
        story_mod._STORY_CACHE.clear()
    story_mod._CIRCUIT.reset()
    yield
    with story_mod._CACHE_LOCK:
        story_mod._STORY_CACHE.clear()
    story_mod._CIRCUIT.reset()


def _post_story(payload: dict) -> tuple[int, list[tuple[str, dict]]]:
    """POST /api/story 拿 SSE 流；解析 (event, data) 列表。"""
    with client.stream("POST", "/api/story", json=payload) as r:
        assert r.status_code == 200
        frames: list[tuple[str, dict]] = []
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                ev_line = next((l for l in frame.splitlines() if l.startswith("event:")), "")
                data_line = next((l for l in frame.splitlines() if l.startswith("data:")), "")
                if not data_line:
                    continue
                ev = ev_line.split(":", 1)[1].strip()
                data = json.loads(data_line.split(":", 1)[1].strip())
                frames.append((ev, data))
        return r.status_code, frames


def _ctx(constellations=None, bright_stars=None, center=None, field=None) -> dict:
    return {
        "constellations": constellations if constellations is not None else [
            {"abbr": "ori", "tradition": "western", "name": "猎户座", "latin": "Orion", "confidence": 0.95},
        ],
        "bright_stars": bright_stars if bright_stars is not None else [
            {"bayer": "α Ori", "name": "Betelgeuse", "name_zh": "参宿四", "magnitude": 0.5, "constellations": ["ori"]},
        ],
        "center": center or {"ra": 84.0, "dec": -1.0},
        "field": field or {"width_deg": 12.5, "height_deg": 8.3},
    }


_BASE_REQ = {"lang": "zh", "style": "myth", "cache_bust": False, "context": _ctx()}


def test_story_accepts_photo_context_request():
    """最小请求合法。"""
    # 真实 ai_provider.health() 默认会调 AgentArts，monkeypatch 返回 False 表示 down
    with patch("services.ai_provider.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = False
        provider.chat_stream = AsyncMock(return_value=iter([]))  # 立刻空
        mp.return_value = provider
        status, frames = _post_story(_BASE_REQ)
        assert status == 200


def test_story_returns_400_on_empty_context():
    """context.constellations 空 → 400 EMPTY_CONTEXT。"""
    bad = {**_BASE_REQ, "context": _ctx(constellations=[])}
    r = client.post("/api/story", json=bad)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "EMPTY_CONTEXT"


def test_story_streams_title_event_then_chars():
    """AI 输出 '标题\\n段落' 应触发 title 事件，再 char 事件逐字。"""
    # 路由用 `from services.ai_provider import make_provider`，patch 路由模块的属性
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = True

        async def fake_chat_stream(system: str, user: str, on_delta):
            on_delta("猎户冬夜\n第一段开始")
        provider.chat_stream.side_effect = fake_chat_stream
        mp.return_value = provider

        _, frames = _post_story(_BASE_REQ)
        types = [t for t, _ in frames]
        assert types[0] == "title"
        assert any(t == "char" for t in types)


def test_story_emits_error_event_on_ai_disabled():
    """AI 未配置（health=False）→ event:error code=AI_DISABLED，不发 title/char。"""
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = False
        provider.chat_stream = AsyncMock(side_effect=Exception("not called"))
        mp.return_value = provider

        _, frames = _post_story(_BASE_REQ)
        types = [t for t, _ in frames]
        # 必须有 error，且无 title/char
        assert "error" in types
        assert "title" not in types
        assert "char" not in types


def test_story_emits_error_event_on_ai_exception():
    """AI 抛异常 → event:error。"""
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = True

        async def fake_chat_stream(system: str, user: str, on_delta):
            raise RuntimeError("upstream 500")
        provider.chat_stream.side_effect = fake_chat_stream
        mp.return_value = provider

        _, frames = _post_story(_BASE_REQ)
        types = [t for t, _ in frames]
        assert "error" in types
        assert "title" not in types


def test_story_cache_hit_returns_cached_content():
    """二次相同请求走 cache，无第二次 AI 调用。"""
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = True
        call_count = 0

        async def fake_chat_stream(system: str, user: str, on_delta):
            nonlocal call_count
            call_count += 1
            on_delta("缓存标题\n缓存段落")
        provider.chat_stream.side_effect = fake_chat_stream
        mp.return_value = provider

        _post_story(_BASE_REQ)
        _post_story(_BASE_REQ)
        # 第二次走 cache，不调 AI
        assert call_count == 1


def test_story_cache_bust_skips_cache():
    """cache_bust=true → 跳过 cache，每次都调 AI。"""
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = True
        call_count = 0

        async def fake_chat_stream(system: str, user: str, on_delta):
            nonlocal call_count
            call_count += 1
            on_delta("新故事\n新段落")
        provider.chat_stream.side_effect = fake_chat_stream
        mp.return_value = provider

        req = {**_BASE_REQ, "cache_bust": False}
        _post_story(req)
        req2 = {**_BASE_REQ, "cache_bust": True}
        _post_story(req2)
        # 第二次 cache_bust → 跳过 cache，调 AI
        assert call_count == 2


def test_story_emits_ai_parse_error_on_empty_output():
    """AI chat_stream 正常返回但 on_delta 从未被调用 → AI_PARSE_ERROR（spec §9）。

    关键：SSE 事件流必须包含 event:error 且 code == "AI_PARSE_ERROR"；
    不应出现 event:done、event:title、event:char。
    """
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = True

        async def fake_chat_stream_no_delta(system: str, user: str, on_delta):
            # 模拟 AI 完成但产空：协程正常返回，on_delta 从未被调用
            return None
        provider.chat_stream.side_effect = fake_chat_stream_no_delta
        mp.return_value = provider

        _, frames = _post_story(_BASE_REQ)
        types = [t for t, _ in frames]

        # 必有 error 且 code=AI_PARSE_ERROR
        assert "error" in types
        error_data = next(d for t, d in frames if t == "error")
        assert error_data["code"] == "AI_PARSE_ERROR"
        # 不能有 done / title / char
        assert "done" not in types
        assert "title" not in types
        assert "char" not in types


def test_story_classifies_timeout_exception():
    """AI 抛 httpx.TimeoutException → event:error code=AI_PROVIDER_TIMEOUT。"""
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = True

        async def fake_chat_stream_timeout(system: str, user: str, on_delta):
            raise httpx.TimeoutException("Request timed out")
        provider.chat_stream.side_effect = fake_chat_stream_timeout
        mp.return_value = provider

        _, frames = _post_story(_BASE_REQ)
        types = [t for t, _ in frames]
        assert "error" in types
        error_data = next(d for t, d in frames if t == "error")
        assert error_data["code"] == "AI_PROVIDER_TIMEOUT"


def test_story_classifies_json_decode_exception():
    """AI 抛 json.JSONDecodeError → event:error code=AI_PARSE_ERROR。"""
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = True

        async def fake_chat_stream_bad_json(system: str, user: str, on_delta):
            raise json.JSONDecodeError("Expecting value", "doc", 0)
        provider.chat_stream.side_effect = fake_chat_stream_bad_json
        mp.return_value = provider

        _, frames = _post_story(_BASE_REQ)
        types = [t for t, _ in frames]
        assert "error" in types
        error_data = next(d for t, d in frames if t == "error")
        assert error_data["code"] == "AI_PARSE_ERROR"


def test_story_truncates_body_to_3000_chars_per_spec_section_9():
    """spec §9：AI 返回超长 (>3000 字) → 截断到 3000 字。

    验证：
    - 流式返回的 char 事件总字符数 ≤ 3000
    - 缓存里的 body 长度也 ≤ 3000（截断后的版本写缓存）
    - done 事件正常发出（截断不是失败路径）
    """
    long_body = "星" * 3500  # 3500 个汉字（>3000）
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = True

        async def fake_chat_stream_long(system: str, user: str, on_delta):
            # 第一个 chunk 是 title 行，第二 chunk 是超长 body
            on_delta("超长标题\n")
            on_delta(long_body)
        provider.chat_stream.side_effect = fake_chat_stream_long
        mp.return_value = provider

        _, frames = _post_story(_BASE_REQ)
        types = [t for t, _ in frames]
        assert "done" in types
        assert "title" in types

        # 1. 流式收到的 char 累计 ≤ 3000
        char_text = "".join(d["char"] for t, d in frames if t == "char")
        assert len(char_text) == 3000

        # 2. 缓存版本也 ≤ 3000（截断后写入）
        import routers.story as story_mod
        with story_mod._CACHE_LOCK:
            cached = next(iter(story_mod._STORY_CACHE.values()), None)
        assert cached is not None
        assert len(cached["body"]) == 3000


def test_done_event_payload_includes_style_and_title_for_frontend_state():
    """回归：done 载荷必须含 StoryResponse 必填字段（style/title/paragraphs）。

    修前 bug：done 只发 bare meta（ok/degraded/provider/model/latency_ms/cached），
    前端 `state` computed 依赖 `current.style === scan.selectedStyle` 判 ready，
    跌回 loading，UI 显示「故事输出完后变空白」。
    """
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = True

        async def fake_chat_stream(system: str, user: str, on_delta):
            on_delta("古天文\n下客自起舞的古老回响。")
        provider.chat_stream.side_effect = fake_chat_stream
        mp.return_value = provider

        _, frames = _post_story({**_BASE_REQ, "style": "myth"})
        done_frames = [d for t, d in frames if t == "done"]
        assert len(done_frames) == 1
        payload = done_frames[0]
        # StoryResponse 必填字段（与 atlas 流 done 对齐）
        assert payload["style"] == "myth"
        assert payload["title"] == "古天文"
        assert payload["paragraphs"] == ["下客自起舞的古老回响。"]
        # abbr 在 photo 层级无意义，约定空字符串
        assert payload["abbr"] == ""
        # 元字段保留
        assert payload["ok"] is True
        assert payload["cached"] is False


def test_replay_cache_done_event_also_includes_style_and_title():
    """回归：缓存重放路径的 done 载荷也要含 style/title/paragraphs。"""
    with patch("routers.story.make_provider") as mp:
        provider = AsyncMock()
        provider.health.return_value = True

        async def fake_chat_stream(system: str, user: str, on_delta):
            on_delta("古天文\n下客自起舞的古老回响。")
        provider.chat_stream.side_effect = fake_chat_stream
        mp.return_value = provider

        # 第一次写缓存
        _post_story({**_BASE_REQ, "style": "myth"})

        # 第二次 cache hit 走 _replay_cache
        _, frames = _post_story({**_BASE_REQ, "style": "myth", "cache_bust": False})
        done_frames = [d for t, d in frames if t == "done"]
        assert len(done_frames) == 1
        payload = done_frames[0]
        assert payload["style"] == "myth"
        assert payload["title"] == "古天文"
        assert payload["paragraphs"] == ["下客自起舞的古老回响。"]
        assert payload["cached"] is True
