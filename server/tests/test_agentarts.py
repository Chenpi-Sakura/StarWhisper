"""AgentArts Provider 单元测试（spec 2026-08-24-starwhisper-agentarts.md v0.3 §5）。

覆盖：
- _extract_text / _parse_event 纯静态解析（官方 data.text + 兼容 content）
- chat 流式聚合（httpx.MockTransport 桩）
- chat body 回退（inputs.query 返 400 → 顶层 query 返 200）
- chat 终止事件（event=end / data.node_type=End）
- health 配置态
- make_provider 工厂三优先级
"""
from __future__ import annotations

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from main import app
from services.ai_provider import (
    AgentArtsProvider,
    DisabledProvider,
    OpenAICompatibleProvider,
    make_provider,
)


# ---- 静态解析：_extract_text ----


class TestExtractText:
    def test_message_content_string(self):
        """event=='message' + content 字符串 → 返回 content。"""
        assert AgentArtsProvider._extract_text({"event": "message", "content": "你好"}) == "你好"

    def test_other_event_content_string_kept(self):
        """chat 内部仅对 event=='message' 调用；_extract_text 对其他事件 content 仍返文本。"""
        assert AgentArtsProvider._extract_text({"event": "summary_response", "content": "x"}) == "x"

    def test_empty_event(self):
        assert AgentArtsProvider._extract_text({}) == ""

    def test_content_non_string_skipped(self):
        """content 是 null 或 dict → 返空串。"""
        assert AgentArtsProvider._extract_text({"event": "message", "content": None}) == ""
        assert AgentArtsProvider._extract_text({"event": "message", "content": {"x": 1}}) == ""


# ---- 静态解析：_parse_event ----


class TestParseEvent:
    def test_data_prefix_json(self):
        ev = AgentArtsProvider._parse_event('data: {"data":{"text":"x"}}')
        assert ev == {"data": {"text": "x"}}

    def test_done_sentinel(self):
        assert AgentArtsProvider._parse_event("data: [DONE]") is None

    def test_ping(self):
        assert AgentArtsProvider._parse_event("data: ping") is None

    def test_invalid_json(self):
        assert AgentArtsProvider._parse_event("data: {bad") is None

    def test_non_dict(self):
        assert AgentArtsProvider._parse_event("data: [1,2]") is None

    def test_empty(self):
        assert AgentArtsProvider._parse_event("") is None


# ---- chat 流式聚合 ----


def _stream_provider(
    handler,
) -> AgentArtsProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    p = AgentArtsProvider(api_key="k", base_url="https://x.example", runtime_name="rt")
    p._client = client
    return p


def _run(coro):
    return asyncio.run(coro)


def test_chat_aggregates_text():
    """聚合 event=='message' 的 content；start/statistic_data/summary_response 跳过。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = (
            b'data: {"event":"start","createdTime":1}\n'
            b'data: {"event":"message","content":"\xe4\xbd\xa0"}\n'
            b'data: {"event":"message","content":"\xe5\xa5\xbd"}\n'
            b'data: {"event":"statistic_data","latency":{"overall":0.5}}\n'
            b'data: {"event":"summary_response","content":"\xe5\xae\x8c\xe6\x95\xb4"}\n'
            b'data: {"event":"done"}\n'
        )
        return httpx.Response(200, content=body)

    p = _stream_provider(handler)
    text = _run(p.chat("sys", "usr"))
    assert text == "你好"


def test_chat_stops_on_done():
    """event='done' 后不再收后续 message（如果有）。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = (
            b'data: {"event":"message","content":"a"}\n'
            b'data: {"event":"done"}\n'
            b'data: {"event":"message","content":"b"}\n'
        )
        return httpx.Response(200, content=body)

    p = _stream_provider(handler)
    text = _run(p.chat("sys", "usr"))
    assert text == "a"


def test_chat_sends_official_inputs_query_with_system():
    """P0-1：body 为官方 {"inputs": {"query": ...}}，system prompt 拼进 query。"""
    seen_body: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_body.append(json.loads(request.content))
        return httpx.Response(200, content=b'data: {"event":"done"}\n')

    p = _stream_provider(handler)
    _run(p.chat("sys", "usr"))
    assert seen_body[0] == {
        "inputs": {"query": "[系统设定]\nsys\n\n[用户请求]\nusr"}
    }


def test_chat_falls_back_to_top_level_query_on_400():
    """官方 inputs 形态被拒（400）时回退顶层 {"query": ...}。"""
    seen_body: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_body.append(body)
        if "inputs" in body:
            return httpx.Response(400, content=b'{"error":"bad body"}')
        return httpx.Response(200, content=b'data: {"event":"message","content":"ok"}\ndata: {"event":"done"}\n')

    p = _stream_provider(handler)
    text = _run(p.chat("sys", "usr"))
    assert text == "ok"
    assert seen_body[0] == {"inputs": {"query": "[系统设定]\nsys\n\n[用户请求]\nusr"}}
    assert seen_body[1] == {"query": "[系统设定]\nsys\n\n[用户请求]\nusr"}


def test_chat_without_system_when_disabled(monkeypatch):
    """AGENTARTS_SYSTEM_IN_QUERY=0：只发 user prompt（人设已在平台侧配置）。"""
    import services.ai_provider as ap

    monkeypatch.setattr(ap, "AGENTARTS_SYSTEM_IN_QUERY", False)
    seen_body: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_body.append(json.loads(request.content))
        return httpx.Response(200, content=b'data: {"event":"done"}\n')

    p = _stream_provider(handler)
    _run(p.chat("sys", "usr"))
    assert seen_body[0] == {"inputs": {"query": "usr"}}


def test_chat_stream_invokes_on_delta_per_message_event():
    """真流式：每推一个 message event → 同步调 on_delta 一次，full 返回聚合文本。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        # 平台推两个 message 事件；其他事件（start/done）跳过不调 on_delta
        body = (
            b'data: {"event":"start","createdTime":1}\n'
            b'data: {"event":"message","content":"\xe4\xbd\xa0\xe5\xa5\xbd"}\n'
            b'data: {"event":"statistic_data","latency":{"overall":0.5}}\n'
            b'data: {"event":"message","content":"\xe4\xb8\x96\xe7\x95\x8c"}\n'
            b'data: {"event":"done"}\n'
        )
        return httpx.Response(200, content=body)

    p = _stream_provider(handler)
    deltas: list[str] = []
    full = _run(p.chat_stream("sys", "usr", deltas.append, timeout=5.0))
    # on_delta 应被调两次：message 内容 + message 内容；其他事件跳过
    assert deltas == ["你好", "世界"]
    assert full == "你好世界"


def test_chat_stream_skips_non_message_events():
    """非 message 事件（如 statistic_data / summary_response）不调 on_delta。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = (
            b'data: {"event":"start","createdTime":1}\n'
            b'data: {"event":"statistic_data","latency":0}\n'
            b'data: {"event":"summary_response","content":"\xe5\xae\x8c\xe6\x95\xb4\xe6\x80\xbb\xe7\xbb\x93"}\n'
            b'data: {"event":"done"}\n'
        )
        return httpx.Response(200, content=body)

    p = _stream_provider(handler)
    deltas: list[str] = []
    full = _run(p.chat_stream("sys", "usr", deltas.append, timeout=5.0))
    assert deltas == []
    assert full == ""


def test_chat_session_id_header_sent():
    """每次调用带 x-hw-agentarts-session-id 头（32 位 hex）。"""
    seen_ids: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_ids.append(request.headers.get("x-hw-agentarts-session-id", ""))
        return httpx.Response(200, content=b'data: {"event":"end"}\n')

    p = _stream_provider(handler)
    _run(p.chat("sys", "usr"))
    assert len(seen_ids[0]) == 32
    int(seen_ids[0], 16)  # 合法 hex


def test_chat_authorization_bearer():
    """Authorization: Bearer <api_key>。"""
    seen_auth: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization", ""))
        return httpx.Response(200, content=b'data: {"event":"end"}\n')

    p = _stream_provider(handler)
    _run(p.chat("sys", "usr"))
    assert seen_auth[0] == "Bearer k"


# ---- health ----


def test_health_configured():
    p = AgentArtsProvider(api_key="k", base_url="https://x", runtime_name="rt")
    assert _run(p.health()) is True


def test_health_missing_runtime():
    p = AgentArtsProvider(api_key="k", base_url="https://x", runtime_name="")
    assert _run(p.health()) is False


# ---- make_provider 工厂优先级 ----


def test_make_provider_agentarts_priority(monkeypatch):
    import services.ai_provider as ai_mod

    monkeypatch.setattr(ai_mod, "AGENTARTS_API_KEY", "ak")
    monkeypatch.setattr(ai_mod, "AGENTARTS_BASE_URL", "https://x")
    monkeypatch.setattr(ai_mod, "AGENTARTS_RUNTIME_NAME", "rt")
    monkeypatch.setattr(ai_mod, "AI_API_KEY", "sk")
    p = make_provider()
    assert isinstance(p, AgentArtsProvider)


def test_make_provider_openai_when_no_agentarts(monkeypatch):
    import services.ai_provider as ai_mod

    monkeypatch.setattr(ai_mod, "AGENTARTS_API_KEY", "")
    monkeypatch.setattr(ai_mod, "AGENTARTS_BASE_URL", "")
    monkeypatch.setattr(ai_mod, "AGENTARTS_RUNTIME_NAME", "")
    monkeypatch.setattr(ai_mod, "AI_API_KEY", "sk")
    p = make_provider()
    assert isinstance(p, OpenAICompatibleProvider)


def test_make_provider_disabled(monkeypatch):
    import services.ai_provider as ai_mod

    monkeypatch.setattr(ai_mod, "AGENTARTS_API_KEY", "")
    monkeypatch.setattr(ai_mod, "AGENTARTS_BASE_URL", "")
    monkeypatch.setattr(ai_mod, "AGENTARTS_RUNTIME_NAME", "")
    monkeypatch.setattr(ai_mod, "AI_API_KEY", "")
    p = make_provider()
    assert isinstance(p, DisabledProvider)


# ---- /api/atlas-story/stream SSE 端点测试已迁到 tests/test_atlas_story.py ----
# 2026-09-03 Task 3：原 /api/story/stream 端点重命名为 /api/atlas-story/stream，
# 对应的两个测试（test_stream_sse_title_char_done /
# test_stream_sse_invalid_abbr_returns_404）迁到 test_atlas_story.py 并解除
# @pytest.mark.integration 标记。