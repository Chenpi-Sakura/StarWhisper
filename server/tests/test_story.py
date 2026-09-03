"""POST /api/story 测试（T3 AI Provider 抽象 + LRU + preset 降级）。

覆盖 plan T3 §Step 8 的全部用例：
- test_disabled_provider_returns_preset_degraded：DisabledProvider → degraded:true
- 5 星座 × 2 风格 参数化（10 用例，全命中 preset）
- test_cache_hit_second_call / test_cache_hit_under_50ms：MockSuccessProvider 验证缓存
- test_cache_bust_header_bypasses_cache / test_cache_bust_body_bypasses_cache
- test_degraded_not_cached：degraded:true 不进缓存
- test_invalid_abbr_returns_404 / test_invalid_style_returns_400

测试策略（PREFERENCE_1）：
- 默认 autouse fixture 把 `routers.story.make_provider` 替换为 _DisabledProvider；
  缓存测试再用 monkeypatch.setattr 二次覆盖为 _MockSuccessProvider。
- monkeypatch.setattr 比手动 try/finally 更安全（测试失败也能自动还原）。
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


ABBRs = ["ori", "cyg", "sco", "leo", "and"]
STYLES = ["myth", "science"]


def _clear_cache() -> None:
    """清空 routers/story.py 模块级 LRU；加锁避免并发覆盖。"""
    from routers.story import _CACHE_LOCK, _STORY_CACHE

    with _CACHE_LOCK:
        _STORY_CACHE.clear()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """每个用例前后：清缓存 + 默认 provider 设为 _DisabledProvider。

    monkeypatch 会在用例结束自动还原 make_provider。
    另外重置熔断器与限流桶，避免用例间状态泄漏。
    """
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _DisabledProvider())
    story_mod._BREAKER.reset()
    with story_mod._RATE_LOCK:
        story_mod._RATE_BUCKETS.clear()
    _clear_cache()
    yield
    _clear_cache()


class _DisabledProvider:
    """测试用 DisabledProvider：chat() 抛错触发 fallback preset。"""

    name = "disabled"

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        raise RuntimeError("AI_PROVIDER_DISABLED")

    async def health(self) -> bool:
        return False


class _MockSuccessProvider:
    """缓存测试专用：返回真实 AI 段落（非降级），让 spec §5.4 缓存路径生效。"""

    name = "mock-success"

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        return "测试标题：猎户永不相见\n\n这是真实 AI 返回的第一段文字。\n\n这是真实 AI 返回的第二段文字。"

    async def health(self) -> bool:
        return True


def test_disabled_provider_returns_preset_degraded():
    """DisabledProvider → 走 preset，degraded:true，provider=fallback（**非 503**）。"""
    r = client.post("/api/story", json={"abbr": "ori", "style": "myth", "lang": "zh"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["provider"] == "fallback"
    assert data["degraded"] is True
    assert data["cached"] is False
    assert data["model"] == "preset"
    assert len(data["paragraphs"]) >= 3
    assert "title" in data and data["title"]


@pytest.mark.parametrize("abbr", ABBRs)
@pytest.mark.parametrize("style", STYLES)
def test_all_5_constellations_x_2_styles_hit_preset(abbr: str, style: str):
    """5 星座 × 2 风格 = 10 条请求，全命中 preset（DisabledProvider 场景）。"""
    r = client.post(
        "/api/story", json={"abbr": abbr, "style": style, "lang": "zh"}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["abbr"] == abbr
    assert data["style"] == style
    assert data["degraded"] is True
    assert data["provider"] == "fallback"
    assert len(data["paragraphs"]) >= 3
    assert data["title"]


def test_cache_hit_second_call(monkeypatch):
    """同请求第二次命中缓存（cached:true）。

    必须 mock 成功 provider（spec §5.4：degraded 不缓存）。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockSuccessProvider())
    _clear_cache()
    client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    r2 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    body = r2.json()
    assert body["cached"] is True
    assert body["degraded"] is False
    assert body["provider"] == "mock-success"


def test_cache_hit_under_50ms(monkeypatch):
    """缓存命中应在 50ms 内完成（无 provider 网络往返）。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockSuccessProvider())
    _clear_cache()
    client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    t0 = time.time()
    r2 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    elapsed_ms = (time.time() - t0) * 1000
    assert r2.json()["cached"] is True
    assert elapsed_ms < 50, f"cache hit {elapsed_ms:.1f}ms 超过 50ms"


def test_cache_bust_header_bypasses_cache(monkeypatch):
    """Cache-Bust: 1 header 绕过缓存，cached:false。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockSuccessProvider())
    _clear_cache()
    client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    r = client.post(
        "/api/story",
        json={"abbr": "ori", "style": "myth"},
        headers={"Cache-Bust": "1"},
    )
    assert r.json()["cached"] is False


def test_cache_bust_body_bypasses_cache(monkeypatch):
    """cacheBust=true body 字段绕过缓存，cached:false。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockSuccessProvider())
    _clear_cache()
    client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    r = client.post(
        "/api/story",
        json={"abbr": "ori", "style": "myth", "cacheBust": True},
    )
    assert r.json()["cached"] is False


def test_degraded_not_cached():
    """degraded:true 响应不写缓存：连续两次都重走 fallback，cached=false。"""
    _clear_cache()
    r1 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    r2 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    assert r1.json()["degraded"] is True
    assert r2.json()["cached"] is False  # 没有命中缓存
    assert r2.json()["degraded"] is True


def test_invalid_abbr_returns_404():
    """未知星座 → 404 CONSTELLATION_NOT_FOUND（spec §3.3）。"""
    r = client.post("/api/story", json={"abbr": "draco", "style": "myth"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CONSTELLATION_NOT_FOUND"


def test_invalid_style_returns_400():
    """非法风格 → 400 INVALID_STYLE。"""
    r = client.post("/api/story", json={"abbr": "ori", "style": "romantic"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_STYLE"




# ---- /api/story/stream 真 SSE 流式测试 ----


class _MockStreamProvider:
    """流式 mock：模拟 AgentArts 逐 message event 推增量。"""

    name = "mock-stream"

    async def chat(self, system, user, *, timeout=30.0):
        # 聚合版本（默认 chat_stream 调用方式）
        return "猎户座：冬夜之誓\n\n这是第一段。\n\n这是第二段。"

    async def chat_stream(self, system, user, on_delta, *, timeout=30.0):
        # 真流式：逐 message 推增量，边界为 \n\n
        on_delta("猎户座：冬夜之誓\n\n")
        on_delta("这是第一段。\n\n")
        on_delta("这是第二段。")
        return "猎户座：冬夜之誓\n\n这是第一段。\n\n这是第二段。"

    async def health(self):
        return True


class _MockStreamFailProvider:
    """流式 mock：chat_stream 抛错。"""

    name = "mock-stream-fail"

    async def chat(self, system, user, *, timeout=30.0):
        raise RuntimeError("AI_PROVIDER_5XX")

    async def chat_stream(self, system, user, on_delta, *, timeout=30.0):
        raise RuntimeError("AI_PROVIDER_5XX")

    async def health(self):
        return True


def _parse_sse_stream(body: str) -> list[tuple[str, dict]]:
    """把 SSE body 解析为 [(event, data), ...] 元组列表。"""
    import json as _json

    events: list[tuple[str, dict]] = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        ev_type = ""
        ev_data = ""
        for line in frame.split("\n"):
            if line.startswith("event:"):
                ev_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                ev_data += line[len("data:"):].strip()
        if ev_type and ev_data:
            events.append((ev_type, _json.loads(ev_data)))
    return events


def test_stream_yields_events_in_order(monkeypatch):
    """真 SSE：title → paragraph ×N → done，事件顺序与 AI 输出一致。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockStreamProvider())
    _clear_cache()

    with client.stream("POST", "/api/story/stream", json={"abbr": "ori", "style": "myth"}) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")

    events = _parse_sse_stream(body)
    types = [t for t, _ in events]
    assert types == ["title", "paragraph", "paragraph", "done"]

    assert events[0][1]["title"] == "猎户座：冬夜之誓"
    assert events[1][1]["index"] == 0
    assert events[1][1]["text"] == "这是第一段。"
    assert events[2][1]["index"] == 1
    assert events[2][1]["text"] == "这是第二段。"
    meta = events[3][1]
    assert meta["provider"] == "mock-stream"
    assert meta["degraded"] is False
    assert meta["cached"] is False


def test_stream_cache_hit_one_shot(monkeypatch):
    """缓存命中：/stream 一次性 yield 所有事件（不调 provider）。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockStreamProvider())
    _clear_cache()

    # 先 POST /api/story 一次以填充缓存
    r0 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    assert r0.status_code == 200
    # 改 provider 为会报错的，确保流式不走 provider
    call_count = {"chat_stream": 0}

    class _TrackingFailProvider(_MockStreamFailProvider):
        async def chat_stream(self, system, user, on_delta, *, timeout=30.0):
            call_count["chat_stream"] += 1
            raise RuntimeError("不应被调用")

    monkeypatch.setattr(story_mod, "make_provider", lambda: _TrackingFailProvider())

    with client.stream("POST", "/api/story/stream", json={"abbr": "ori", "style": "myth"}) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")

    assert call_count["chat_stream"] == 0  # 不应调 provider
    events = _parse_sse_stream(body)
    types = [t for t, _ in events]
    assert types == ["title", "paragraph", "paragraph", "done"]
    meta = events[3][1]
    assert meta["cached"] is True


def test_stream_fallback_to_preset_on_ai_failure(monkeypatch):
    """AI 失败：先发 reset 清空半截内容（P0-3），再走 preset fallback。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockStreamFailProvider())
    _clear_cache()

    with client.stream("POST", "/api/story/stream", json={"abbr": "ori", "style": "myth"}) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")

    events = _parse_sse_stream(body)
    types = [t for t, _ in events]
    # P0-3：reset 先行，随后直接 fallback 到 preset（不发 error，直接 preset）
    assert types[0] == "reset"
    assert types[1] == "title"
    assert "done" in types
    meta = events[-1][1]
    assert meta["provider"] == "fallback"
    assert meta["model"] == "preset"
    assert meta["degraded"] is True
    assert "degraded_reason" in meta


def test_stream_partial_ai_then_failure_sends_reset(monkeypatch):
    """P0-3：AI 推了半截段落才挂——reset 必须在 preset 之前，清掉半截内容。"""
    import routers.story as story_mod

    class _PartialFailProvider:
        name = "mock-partial-fail"

        async def chat(self, system, user, *, timeout=30.0):
            raise RuntimeError("AI_PROVIDER_5XX")

        async def chat_stream(self, system, user, on_delta, *, timeout=30.0):
            on_delta("半截标题\n\n")
            on_delta("半截第一段。\n\n")
            raise RuntimeError("AI_PROVIDER_5XX")

        async def health(self):
            return True

    monkeypatch.setattr(story_mod, "make_provider", lambda: _PartialFailProvider())
    _clear_cache()

    with client.stream("POST", "/api/story/stream", json={"abbr": "ori", "style": "myth"}) as r:
        body = b"".join(r.iter_bytes()).decode("utf-8")

    events = _parse_sse_stream(body)
    types = [t for t, _ in events]
    # 半截 title/paragraph 已发出，但 reset 在 preset 之前
    assert types[0] == "title"
    assert "reset" in types
    assert types.index("reset") < types.index("done")
    # reset 之后不应再有半截内容，preset 段落完整
    meta = events[-1][1]
    assert meta["degraded"] is True


def test_stream_yields_title_at_first_double_newline(monkeypatch):
    """验证边界检测：第一个 \\n\\n 后立即 yield title。"""
    import routers.story as story_mod

    class _OneCharProvider:
        name = "mock-one"

        async def chat(self, system, user, *, timeout=30.0):
            return "t\n\np"

        async def chat_stream(self, system, user, on_delta, *, timeout=30.0):
            on_delta("t")
            on_delta("\n\n")
            on_delta("p")
            return "t\n\np"

        async def health(self):
            return True

    monkeypatch.setattr(story_mod, "make_provider", lambda: _OneCharProvider())
    _clear_cache()

    with client.stream("POST", "/api/story/stream", json={"abbr": "ori", "style": "myth"}) as r:
        body = b"".join(r.iter_bytes()).decode("utf-8")

    events = _parse_sse_stream(body)
    types = [t for t, _ in events]
    assert types == ["title", "paragraph", "done"]
    assert events[0][1]["title"] == "t"
    assert events[1][1]["text"] == "p"

# ---- P0-2 / P1-7 / P1-9 / P1-10 / P1-11 增量测试 ----


class TestParseStoryText:
    """P0-2：parse_story_text 首行为标题 + 前缀剥离（流式/非流式共用）。"""

    def test_first_line_is_title(self):
        from routers.story import parse_story_text

        title, paras = parse_story_text("猎户的故事\n\n第一段。\n\n第二段。", "兜底")
        assert title == "猎户的故事"
        assert paras == ["第一段。", "第二段。"]

    def test_strips_title_prefixes(self):
        from routers.story import parse_story_text

        for prefixed in ("标题：猎户", "标题:猎户", "Title:猎户", "# 猎户"):
            title, _ = parse_story_text(f"{prefixed}\n\n正文。", "兜底")
            assert title == "猎户"

    def test_single_line_no_body_falls_back(self):
        from routers.story import parse_story_text

        title, paras = parse_story_text("只有一行", "兜底标题")
        assert title == "兜底标题"
        assert paras == ["只有一行"]

    def test_empty_text(self):
        from routers.story import parse_story_text

        title, paras = parse_story_text("", "兜底标题")
        assert title == "兜底标题"
        assert paras == []


def test_cache_hit_latency_zero_and_origin_kept(monkeypatch):
    """P1-11：缓存命中 latency_ms=0，首次生成耗时挪到 origin_latency_ms。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockSuccessProvider())
    _clear_cache()
    client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    r2 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    body = r2.json()
    assert body["cached"] is True
    assert body["latency_ms"] == 0
    assert body["origin_latency_ms"] >= 0


def test_stream_cache_hit_latency_zero(monkeypatch):
    """P1-11：流式缓存命中 done.meta 同样 latency_ms=0。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockStreamProvider())
    _clear_cache()
    client.post("/api/story", json={"abbr": "ori", "style": "myth"})

    with client.stream("POST", "/api/story/stream", json={"abbr": "ori", "style": "myth"}) as r:
        body = b"".join(r.iter_bytes()).decode("utf-8")
    events = _parse_sse_stream(body)
    meta = events[-1][1]
    assert meta["cached"] is True
    assert meta["latency_ms"] == 0
    assert "origin_latency_ms" in meta


def test_stream_total_timeout_degrades(monkeypatch):
    """P1-7：AI 挂起超过总预算 → 降级 preset，degraded_reason=AI_PROVIDER_TIMEOUT。"""
    import asyncio

    import routers.story as story_mod

    class _HangingProvider:
        name = "mock-hang"

        async def chat(self, system, user, *, timeout=30.0):
            await asyncio.sleep(60)
            return ""

        async def chat_stream(self, system, user, on_delta, *, timeout=30.0):
            await asyncio.sleep(60)
            return ""

        async def health(self):
            return True

    monkeypatch.setattr(story_mod, "make_provider", lambda: _HangingProvider())
    monkeypatch.setattr(story_mod, "STORY_TOTAL_TIMEOUT", 0.2)
    _clear_cache()

    with client.stream("POST", "/api/story/stream", json={"abbr": "ori", "style": "myth"}) as r:
        body = b"".join(r.iter_bytes()).decode("utf-8")

    events = _parse_sse_stream(body)
    types = [t for t, _ in events]
    assert types[0] == "reset"
    assert "done" in types
    meta = events[-1][1]
    assert meta["degraded"] is True
    assert meta["degraded_reason"] == "AI_PROVIDER_TIMEOUT"


class TestCircuitBreaker:
    """P1-9：连续失败开熔断，冷却期内直走 preset，成功恢复。"""

    def test_opens_after_threshold(self):
        from routers.story import _CircuitBreaker

        cb = _CircuitBreaker(threshold=3, cooldown=60)
        assert cb.allow() is True
        cb.record_failure()
        cb.record_failure()
        assert cb.allow() is True  # 未达阈值仍放行
        cb.record_failure()
        assert cb.allow() is False  # 达阈值 → 熔断
        cb.record_success()
        assert cb.allow() is True  # 成功即恢复

    def test_cooldown_expiry_half_opens(self):
        from routers.story import _CircuitBreaker

        cb = _CircuitBreaker(threshold=1, cooldown=0.05)
        cb.record_failure()
        assert cb.allow() is False
        time.sleep(0.08)
        assert cb.allow() is True  # 冷却结束半开

    def test_router_skips_ai_when_open(self, monkeypatch):
        import routers.story as story_mod

        calls = {"n": 0}

        class _CountingFailProvider:
            name = "mock-count-fail"

            async def chat(self, system, user, *, timeout=30.0):
                calls["n"] += 1
                raise RuntimeError("AI_PROVIDER_5XX")

            async def chat_stream(self, system, user, on_delta, *, timeout=30.0):
                calls["n"] += 1
                raise RuntimeError("AI_PROVIDER_5XX")

            async def health(self):
                return True

        provider = _CountingFailProvider()
        monkeypatch.setattr(story_mod, "make_provider", lambda: provider)
        monkeypatch.setattr(story_mod._BREAKER, "_threshold", 2)
        monkeypatch.setattr(story_mod._BREAKER, "_cooldown", 60)
        story_mod._BREAKER.reset()
        _clear_cache()

        # 前两次失败达阈值（threshold=2）
        client.post("/api/story", json={"abbr": "ori", "style": "myth"})
        client.post("/api/story", json={"abbr": "ori", "style": "myth"})
        assert calls["n"] == 2
        # 熔断开启：不再调 provider，直接 preset
        r3 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
        assert calls["n"] == 2
        assert r3.json()["degraded"] is True
        assert r3.json()["degraded_reason"] == "AI_CIRCUIT_OPEN"


def test_rate_limit_returns_429(monkeypatch):
    """P1-10：超过窗口内限额 → 429 RATE_LIMITED。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "STORY_RATE_LIMIT", 2)
    monkeypatch.setattr(story_mod, "STORY_RATE_WINDOW", 60)
    with story_mod._RATE_LOCK:
        story_mod._RATE_BUCKETS.clear()

    r1 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    r2 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    r3 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert r3.json()["detail"]["code"] == "RATE_LIMITED"


def test_rate_limit_disabled_when_zero(monkeypatch):
    """P1-10：STORY_RATE_LIMIT<=0 关闭限流。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "STORY_RATE_LIMIT", 0)
    for _ in range(5):
        r = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
        assert r.status_code == 200
