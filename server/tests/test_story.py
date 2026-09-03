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
    """P2-16 字符级：title → char ×N → done，字符顺序与 AI 输出逐字一致。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockStreamProvider())
    _clear_cache()

    with client.stream("POST", "/api/story/stream", json={"abbr": "ori", "style": "myth"}) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")

    events = _parse_sse_stream(body)
    types = [t for t, _ in events]
    assert types[0] == "title"
    assert types[-1] == "done"
    # 中间全 char 事件
    middle_types = types[1:-1]
    assert all(t == "char" for t in middle_types), f"middle events must all be char, got {middle_types}"

    assert events[0][1]["title"] == "猎户座：冬夜之誓"

    # 重组：title + 字符流 == AI 原始输出（首个 \n 作为 title 分隔符被 partition 消费，
    # 与 parse_story_text 行为对齐——body 段首只保留一个 \n 作段间距）
    ai_full = "猎户座：冬夜之誓\n\n这是第一段。\n\n这是第二段。"
    chars_only = "".join(ev_data["char"] for t, ev_data in events if t == "char")
    expected_body = ai_full.partition("\n")[2]  # 首 \n 之后的全部内容
    assert chars_only == expected_body
    assert events[0][1]["title"] + "\n" + chars_only == ai_full

    meta = events[-1][1]
    assert meta["provider"] == "mock-stream"
    assert meta["degraded"] is False
    assert meta["cached"] is False


def test_stream_cache_hit_one_shot(monkeypatch):
    """缓存命中：/stream 一次性 yield title + char ×N + done（不调 provider）。"""
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
    assert types[0] == "title"
    assert types[-1] == "done"
    assert all(t == "char" for t in types[1:-1])
    meta = events[-1][1]
    assert meta["cached"] is True


def test_stream_fallback_to_preset_on_ai_failure(monkeypatch):
    """P2-16 字符级：AI 失败 → reset 清空半截内容，再走 preset fallback（也走 char）。"""
    import routers.story as story_mod

    monkeypatch.setattr(story_mod, "make_provider", lambda: _MockStreamFailProvider())
    _clear_cache()

    with client.stream("POST", "/api/story/stream", json={"abbr": "ori", "style": "myth"}) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")

    events = _parse_sse_stream(body)
    types = [t for t, _ in events]
    # P0-3：reset 先行，随后 preset 全量
    assert types[0] == "reset"
    assert types[1] == "title"
    assert "done" in types
    # preset 全量也是 char 事件
    middle_types = types[2:-1]
    assert all(t == "char" for t in middle_types), f"preset must yield char events, got {middle_types}"
    meta = events[-1][1]
    assert meta["provider"] == "fallback"
    assert meta["model"] == "preset"
    assert meta["degraded"] is True
    assert "degraded_reason" in meta


def test_stream_partial_ai_then_failure_sends_reset(monkeypatch):
    """P0-3：AI 推了半截字符才挂——reset 必须在 preset 之前，清掉半截内容。"""
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
    # 半截 title/char 已发出，但 reset 在 done 之前
    assert types[0] == "title"
    assert "reset" in types
    assert types.index("reset") < types.index("done")
    # reset 之后不应再有半截内容，preset 字符完整
    meta = events[-1][1]
    assert meta["degraded"] is True


def test_stream_yields_title_at_first_newline(monkeypatch):
    """P2-16：验证边界检测——首个 \\n 触发 title 事件，\\n 之后的字符按 char 流式 yield。"""
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
    # title → char ×N → done
    assert types[0] == "title"
    assert types[-1] == "done"
    assert all(t == "char" for t in types[1:-1])
    assert events[0][1]["title"] == "t"
    chars = "".join(ev_data["char"] for t, ev_data in events if t == "char")
    # AI 输出「t\n\np」：title='t'（首 \n 前的部分），char 流 = "\np"（首 \n 被消费）
    expected_body = "t\n\np".partition("\n")[2]
    assert chars == expected_body

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


# ---- P2-12 / P2-13 / P2-14 增量测试 ----


def test_invalid_tradition_returns_400():
    """P2-12：未知 tradition → 400 INVALID_TRADITION。"""
    r = client.post(
        "/api/story",
        json={"abbr": "ori", "style": "myth", "tradition": "atlantis"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_TRADITION"


def test_tradition_in_cn_cache_distinct_from_default(monkeypatch):
    """P2-12：western / chinese 是缓存两个维度——同 abbr+style 不同 tradition 各自独立。

    测试方法：先填 western 缓存（mock-success 走 AI 返回英文「Western Title」）；
    再带 tradition='chinese' 请求（命中 chinese preset），如果错误地共用缓存，会拿到
    'Western Title'。期望各自走各自的预设/AI。
    """
    import routers.story as story_mod

    class _WesternEnProvider:
        name = "mock-western-en"

        async def chat(self, system, user, *, timeout=30.0):
            # 仅当 system 含 "western" 触发英文返回——验证 tradition 进 prompt 了
            if "western" in system.lower():
                return "Western Title\n\nWestern paragraph."
            return "Other Title\n\nOther paragraph."

        async def chat_stream(self, system, user, on_delta, *, timeout=30.0):
            return await self.chat(system, user)

        async def health(self):
            return True

    monkeypatch.setattr(story_mod, "make_provider", lambda: _WesternEnProvider())
    _clear_cache()

    r1 = client.post(
        "/api/story",
        json={"abbr": "ori", "style": "myth", "tradition": "western"},
    )
    assert r1.status_code == 200
    body1 = r1.json()
    # 缓存写了 (western, ori, myth)，下次同 abbr+style 但不带 tradition 仍走首命中
    r2 = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    assert r2.json()["cached"] is True
    assert r2.json()["title"] == body1["title"]


class TestCleanMarkdown:
    """P2-14：clean_markdown 剥离常见 Markdown 标记，幂等。"""

    def test_strips_bold_italic_code(self):
        from routers.story import clean_markdown

        assert clean_markdown("**加粗**") == "加粗"
        assert clean_markdown("*斜体*") == "斜体"
        assert clean_markdown("`code`") == "code"

    def test_strips_heading_and_bullet(self):
        from routers.story import clean_markdown

        # 行首 heading 标记
        text = "# 标题\n\n- 列表1\n- 列表2\n\n1. 编号\n2. 编号2"
        assert "列表" in clean_markdown(text)
        assert "标题" in clean_markdown(text)

    def test_idempotent(self):
        from routers.story import clean_markdown

        s = "纯文本无标记"
        assert clean_markdown(clean_markdown(s)) == s

    def test_preserves_chinese_punctuation(self):
        from routers.story import clean_markdown

        text = "**第一段，标点：，。！？**；*第二段。*"
        out = clean_markdown(text)
        assert "，" in out and "。" in out

    def test_parse_story_text_runs_clean_markdown(self):
        """P2-14：parse_story_text 也走 clean_markdown——AI 偶尔输出 **加粗** 不要漏到前端。"""
        from routers.story import parse_story_text

        title, paras = parse_story_text(
            "**标题：猎户**\n\n第一段带 **加粗** 和 *斜体*。\n\n第二段。",
            "兜底",
        )
        assert title == "猎户"  # 不应有 **...**
        assert "**" not in (title,)
        assert all("**" not in p for p in paras)


def test_prompt_truncates_stars_over_threshold(monkeypatch):
    """P2-13：星点数 > STORY_PROMPT_MAX_STARS 时按星等截断。"""
    import routers.story as story_mod

    captured = {"user_prompt": ""}

    class _CaptureProvider:
        name = "mock-capture"

        async def chat(self, system, user, *, timeout=30.0):
            captured["user_prompt"] = user
            return "title\n\np1\n\np2"

        async def chat_stream(self, system, user, on_delta, *, timeout=30.0):
            return await self.chat(system, user)

        async def health(self):
            return True

    # 造一个 stars 多（>=20 颗）的星座数据覆盖 cyber-yuan (xuanyuan/cyber)
    # 直接 monkeypatch _find_constellation 返回假数据
    class _ManyStarsConstellation(dict):
        def __init__(self):
            super().__init__({
                "abbr": "ori",
                "name": "猎户",
                "latin": "Orion",
                "tradition": "western",
                "stories": {},
            })
            self._stars = {
                f"alpha-{i}": {
                    "bayer": f"α{i}",
                    "name": f"星{i}",
                    "magnitude": 0.5 + i * 0.3,
                }
                for i in range(20)
            }

        def get(self, key, default=None):
            if key == "stars":
                return self._stars
            return super().get(key, default)

    monkeypatch.setattr(story_mod, "_find_constellation", lambda *a, **k: _ManyStarsConstellation())
    monkeypatch.setattr(story_mod, "make_provider", lambda: _CaptureProvider())
    monkeypatch.setattr(story_mod, "STORY_PROMPT_MAX_STARS", 5)
    _clear_cache()

    client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    # 只显示了 5 颗
    lines = [l for l in captured["user_prompt"].splitlines() if l.startswith("- ")]
    assert len(lines) == 5, f"expected 5 lines, got {len(lines)}: {lines}"


def test_prompt_handles_missing_star_fields(monkeypatch):
    """P2-13：数据下标访问 .get() 防护——star 缺 name 或 magnitude 时不抛 KeyError。"""
    import routers.story as story_mod

    captured = {"user_prompt": ""}

    class _CaptureProvider:
        name = "mock-capture-2"

        async def chat(self, system, user, *, timeout=30.0):
            captured["user_prompt"] = user
            return "title\n\np1\n\np2"

        async def chat_stream(self, system, user, on_delta, *, timeout=30.0):
            return await self.chat(system, user)

        async def health(self):
            return True

    class _BadStarsConstellation(dict):
        def __init__(self):
            super().__init__({
                "abbr": "ori", "name": "猎户", "latin": "Orion",
                "tradition": "western", "stories": {},
            })
            # 一颗全空、一颗只有 bayer、一颗 OK、一颗没 magnitude
            self._stars = {
                "empty": {},
                "bayer_only": {"bayer": "β"},
                "ok": {"bayer": "γ", "name": "γ星", "magnitude": 2.5},
                "no_mag": {"name": "无名星", "bayer": "δ"},
            }

        def get(self, key, default=None):
            if key == "stars":
                return self._stars
            return super().get(key, default)

    monkeypatch.setattr(story_mod, "_find_constellation", lambda *a, **k: _BadStarsConstellation())
    monkeypatch.setattr(story_mod, "make_provider", lambda: _CaptureProvider())
    _clear_cache()

    # 不抛错即成功
    r = client.post("/api/story", json={"abbr": "ori", "style": "myth"})
    assert r.status_code == 200
    # OK 这颗应当进 prompt
    assert "γ星" in captured["user_prompt"]
    # bayer_only 也应进（name 兜底为 bayer）
    assert "β" in captured["user_prompt"]


# ---- P2-15 测试：死代码清理后，约定接口仍在 ----


def test_postStory_non_stream_endpoint_keeps_return_contract():
    """P2-15：POST /api/story 非流式接口保留（向后兼容），契约不变。"""
    r = client.post(
        "/api/story",
        json={"abbr": "ori", "style": "myth", "lang": "zh"},
    )
    assert r.status_code == 200
    body = r.json()
    for key in ("ok", "abbr", "style", "title", "paragraphs", "provider", "model",
                "latency_ms", "cached", "degraded"):
        assert key in body, f"missing {key}"


# ---- P2-17 测试：story_fallback 仍可从 traditions 取 preset（无 clear_cache 误清） ----


def test_fallback_module_has_no_clear_cache():
    """P2-15：story_fallback.clear_cache 已删除（会误清 traditions 全局缓存）。"""
    import services.story_fallback as fb

    assert not hasattr(fb, "clear_cache")
