"""POST /api/atlas-nota 路由测试。

覆盖：
- 正常 AI 路径（200 + intro + degraded:false）
- 缓存命中（mock provider 不再被调用）
- cacheBust=true 绕过缓存（mock provider 被调）
- AI DisabledProvider → 降级到 caption + degraded:true
- AI 抛超时 → 同上降级
- 未知 abbr → 404 CONSTELLATION_NOT_FOUND
- 非法 tradition → 400 INVALID_TRADITION
- 降级不写缓存（第一次 degraded 后第二次仍调 AI）
- tradition 缺省：跨 tradition 首命中
- 限流：超阈值 → 429
- Cache-Bust header 也支持绕过缓存
"""
from __future__ import annotations

import json as _json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import atlas_nota
from services.story_throttle import reset_rate_limit_buckets, reset_all_circuits


client = TestClient(app)


# ---------- Helpers ----------


class _OkProvider:
    """AI 正常返回（可控文本，方便断言 intro 内容）。"""

    name = "mock-success"

    def __init__(self, text: str = "猎户座，冬季星空最醒目的坐标。腰带三星横跨天球赤道。"):
        self._text = text

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        return self._text

    async def health(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _isolate():
    """每个用例前后清缓存 / 重置熔断 / 清限流桶。"""
    atlas_nota.cache_clear()
    atlas_nota.reset_breaker()
    reset_rate_limit_buckets()
    # 熔断器是 lazy 创建的；确保 atlas-nota 实例被清掉
    reset_all_circuits()
    yield
    atlas_nota.cache_clear()
    atlas_nota.reset_breaker()
    reset_rate_limit_buckets()
    reset_all_circuits()


# ---------- Basic ----------


def test_atlas_nota_happy_path_returns_intro():
    """正常路径：mock AI 返回 → 200 + intro + degraded:false。"""
    with patch("services.atlas_nota.make_provider", return_value=_OkProvider()):
        r = client.post("/api/atlas-nota", json={"abbr": "ori"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["abbr"] == "ori"
    assert body["tradition"] == "western"
    assert body["degraded"] is False
    assert body["source"] == "agentarts"
    assert "猎户" in body["intro"]
    assert "latency_ms" in body


def test_atlas_nota_cache_hit_second_call_skips_provider():
    """第 2 次请求命中缓存：mock provider 调用次数断言。"""
    with patch("services.atlas_nota.make_provider", return_value=_OkProvider()) as mp:
        r1 = client.post("/api/atlas-nota", json={"abbr": "ori"})
        assert r1.status_code == 200
        # 第 2 次：不调 provider（patch 计数器不增）
        r2 = client.post("/api/atlas-nota", json={"abbr": "ori"})
        assert r2.status_code == 200
    assert mp.call_count == 1
    assert r2.json()["cached"] is True
    assert r2.json()["latency_ms"] == 0


def test_atlas_nota_cache_bust_body_field_calls_provider():
    """cacheBust=true body 字段绕过缓存：每次都调 AI。"""
    with patch("services.atlas_nota.make_provider", return_value=_OkProvider()) as mp:
        client.post("/api/atlas-nota", json={"abbr": "ori"})
        client.post(
            "/api/atlas-nota", json={"abbr": "ori", "cacheBust": True},
        )
    assert mp.call_count == 2


def test_atlas_nota_cache_bust_header_calls_provider():
    """Cache-Bust: 1 header 也绕过缓存。"""
    with patch("services.atlas_nota.make_provider", return_value=_OkProvider()) as mp:
        client.post("/api/atlas-nota", json={"abbr": "ori"})
        client.post(
            "/api/atlas-nota", json={"abbr": "ori"}, headers={"Cache-Bust": "1"},
        )
    assert mp.call_count == 2


# ---------- Degradation ----------


def test_atlas_nota_ai_disabled_returns_degraded_caption():
    """AI 不可用 → 降级到 caption + degraded:true。"""
    from services.ai_provider import DisabledProvider

    with patch("services.atlas_nota.make_provider", return_value=DisabledProvider()):
        r = client.post("/api/atlas-nota", json={"abbr": "ori"})
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True
    assert body["source"] == "preset"
    # ori.json caption 实测：含"腰带三星"或"冬夜"
    assert "腰带三星" in body["intro"] or "冬夜" in body["intro"]
    assert body["degraded_reason"] == "AI_PROVIDER_DISABLED"


def test_atlas_nota_ai_timeout_returns_degraded_caption():
    """AI 抛超时 → 降级到 caption。"""
    provider = AsyncMock()
    provider.name = "agentarts"
    provider.chat = AsyncMock(side_effect=TimeoutError("AI timed out"))

    with patch("services.atlas_nota.make_provider", return_value=provider):
        r = client.post("/api/atlas-nota", json={"abbr": "ori"})
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True
    assert "AI_PROVIDER_TIMEOUT" in body["degraded_reason"]


def test_atlas_nota_ai_general_exception_returns_degraded():
    """AI 抛通用异常（如网络错）→ 同上降级。"""
    provider = AsyncMock()
    provider.name = "agentarts"
    provider.chat = AsyncMock(side_effect=RuntimeError("network unreachable"))

    with patch("services.atlas_nota.make_provider", return_value=provider):
        r = client.post("/api/atlas-nota", json={"abbr": "ori"})
    assert r.status_code == 200
    assert r.json()["degraded"] is True


def test_atlas_nota_degraded_does_not_cache():
    """第一次 degraded 后，第二次仍尝试调 AI（验证不写缓存）。"""
    from services.ai_provider import DisabledProvider

    # 第 1 次：降级
    with patch("services.atlas_nota.make_provider", return_value=DisabledProvider()):
        r1 = client.post("/api/atlas-nota", json={"abbr": "ori"})
    assert r1.json()["degraded"] is True

    # 第 2 次：换 provider——若不调 AI，会命中缓存
    with patch("services.atlas_nota.make_provider", return_value=_OkProvider()) as mp:
        r2 = client.post("/api/atlas-nota", json={"abbr": "ori"})
    assert mp.call_count == 1  # 关键：调了 AI
    assert r2.json()["degraded"] is False


# ---------- 错误码 ----------


def test_atlas_nota_unknown_abbr_returns_404():
    """未知 abbr → 404 CONSTELLATION_NOT_FOUND。"""
    r = client.post("/api/atlas-nota", json={"abbr": "__totally_fake__"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CONSTELLATION_NOT_FOUND"


def test_atlas_nota_invalid_tradition_returns_400():
    """非法 tradition → 400 INVALID_TRADITION。"""
    r = client.post(
        "/api/atlas-nota", json={"abbr": "ori", "tradition": "fake"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_TRADITION"


def test_atlas_nota_tradition_valid_but_abbr_missing_returns_404():
    """tradition 合法但该 tradition 下无此 abbr → 404（不是 400）。"""
    r = client.post(
        "/api/atlas-nota", json={"abbr": "__missing__", "tradition": "western"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CONSTELLATION_NOT_FOUND"


def test_atlas_nota_missing_required_abbr_returns_422():
    """缺 abbr → 422 Pydantic validation error。"""
    r = client.post("/api/atlas-nota", json={})
    assert r.status_code == 422


# ---------- Tradition 缺省：跨 tradition 首命中 ----------


def test_atlas_nota_tradition_omitted_cross_tradition_first_hit():
    """不带 tradition → 跨 tradition 首命中（ori 应在 western 下）。"""
    with patch("services.atlas_nota.make_provider", return_value=_OkProvider()):
        r = client.post("/api/atlas-nota", json={"abbr": "ori"})
    assert r.status_code == 200
    assert r.json()["tradition"] == "western"


def test_atlas_nota_explicit_tradition_respected():
    """显式传 tradition → 用它（即使 western 也有，仍走 chinese 即失败）。
    这里用 cyg（天鹅）在 western 下必中，断言 tradition=western。"""
    with patch("services.atlas_nota.make_provider", return_value=_OkProvider()):
        r = client.post(
            "/api/atlas-nota", json={"abbr": "cyg", "tradition": "western"},
        )
    assert r.status_code == 200
    assert r.json()["tradition"] == "western"


# ---------- 限流 ----------


def test_atlas_nota_rate_limit_returns_429(monkeypatch):
    """连续触发超阈值 → 429 RATE_LIMITED。"""
    from config import STORY_RATE_LIMIT, STORY_RATE_WINDOW

    # 把阈值调小，避免打满 60 次
    monkeypatch.setattr("services.story_throttle.STORY_RATE_LIMIT", 3)
    monkeypatch.setattr("services.story_throttle.STORY_RATE_WINDOW", 60)

    # 重置单例：前文用了 monkeypatch 但 STORY_RATE_LIMIT 是模块级常量，
    # 限流函数在调用时读取，所以下面直接发起请求就会读到新值。
    reset_rate_limit_buckets()

    with patch("services.atlas_nota.make_provider", return_value=_OkProvider()):
        for _ in range(3):
            r = client.post("/api/atlas-nota", json={"abbr": "ori"})
            assert r.status_code == 200
        r4 = client.post("/api/atlas-nota", json={"abbr": "ori"})
    assert r4.status_code == 429
    assert r4.json()["detail"]["code"] == "RATE_LIMITED"


# ---------- 熔断 ----------


def test_atlas_nota_circuit_breaker_short_circuits_to_caption():
    """熔断打开（连续失败 + 冷却中）→ 直接降级 caption，不调 AI。"""
    from services.ai_provider import DisabledProvider

    # 触发 3 次连续失败（STORY_CB_THRESHOLD 默认 3）
    with patch("services.atlas_nota.make_provider", return_value=DisabledProvider()):
        for _ in range(3):
            client.post("/api/atlas-nota", json={"abbr": "ori"})

    # 现在熔断已开——下次即使 mock 一个能用的 provider，也应走 caption（不调 AI）
    with patch("services.atlas_nota.make_provider", return_value=_OkProvider()) as mp:
        r = client.post("/api/atlas-nota", json={"abbr": "ori"})
    assert r.status_code == 200
    assert r.json()["degraded"] is True
    assert r.json()["degraded_reason"] == "AI_CIRCUIT_OPEN"
    mp.assert_not_called()


# ============= /api/atlas-nota/stream（SSE 字符级） =============


class _StreamOkProvider:
    """SSE 路径需要的 chat_stream provider mock：分块调 on_delta。"""

    name = "mock-stream-success"

    def __init__(self, text: str = "猎户座，冬季星空最醒目的坐标。腰带三星横跨天球赤道。", chunks: int | None = None):
        self._text = text
        self._chunks = chunks or max(1, len(text) // 4)

    async def chat(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        return self._text

    async def chat_stream(self, system, user, on_delta, *, timeout: float = 30.0) -> str:
        # 按 4 字一块调 on_delta，模拟 AI 逐段返回
        for i in range(0, len(self._text), self._chunks):
            on_delta(self._text[i : i + self._chunks])
        return self._text

    async def health(self) -> bool:
        return True


class _StreamFailProvider:
    name = "mock-stream-fail"

    async def chat(self, system, user, *, timeout: float = 30.0) -> str:
        raise RuntimeError("network down")

    async def chat_stream(self, system, user, on_delta, *, timeout: float = 30.0) -> str:
        # 推一点字符让前端看到过渡，再报失败
        on_delta("在古希腊")
        raise RuntimeError("network down")

    async def health(self) -> bool:
        return True


def _parse_sse_frames(raw: str) -> list[tuple[str, dict]]:
    """拆 SSE 帧为 [(event, data_dict), ...]，辅助断言。"""
    out: list[tuple[str, dict]] = []
    for frame in raw.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        ev = ""
        data: dict = {}
        for line in frame.split("\n"):
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
            elif line.startswith("data:"):
                try:
                    data = _json.loads(line[len("data:"):].strip())
                except _json.JSONDecodeError:
                    pass
        if ev:
            out.append((ev, data))
    return out


def test_stream_sse_char_done_happy_path():
    """SSE 字符级流：AI 成功时收到 char ×N + done，且无 reset。"""
    with patch("services.ai_provider.make_provider", return_value=_StreamOkProvider()):
        with client.stream(
            "POST", "/api/atlas-nota/stream", json={"abbr": "ori"},
        ) as r:
            assert r.status_code == 200
            raw = r.read().decode("utf-8")

    frames = _parse_sse_frames(raw)
    events = [ev for ev, _ in frames]
    assert "char" in events
    assert "done" in events
    assert "reset" not in events

    # 拼接所有 char 事件检查内容
    char_text = "".join(d.get("char", "") for ev, d in frames if ev == "char")
    assert "猎户" in char_text

    # done 事件的 meta
    done_payload = next(d for ev, d in frames if ev == "done")
    assert done_payload["ok"] is True
    assert done_payload["degraded"] is False
    assert done_payload["source"] == "agentarts"
    assert "猎户" in done_payload["intro"]


def test_stream_sse_cache_hit_skips_provider():
    """缓存命中：第 1 次走 provider 写 cache，第 2 次直接走 cache 不调 provider。"""
    with patch("services.ai_provider.make_provider", return_value=_StreamOkProvider()) as mp:
        with client.stream(
            "POST", "/api/atlas-nota/stream", json={"abbr": "ori"},
        ) as r:
            r.read()
        # 第 2 次：mock provider 不被调
        with client.stream(
            "POST", "/api/atlas-nota/stream", json={"abbr": "ori"},
        ) as r:
            raw2 = r.read().decode("utf-8")
    assert mp.call_count == 1
    frames = _parse_sse_frames(raw2)
    done_payload = next(d for ev, d in frames if ev == "done")
    assert done_payload["cached"] is True


def test_stream_sse_ai_failure_emits_reset_then_preset():
    """AI 中途失败：前端收到 reset 事件后跟着 caption 字符流 + done (degraded:true)。"""
    with patch("services.ai_provider.make_provider", return_value=_StreamFailProvider()):
        with client.stream(
            "POST", "/api/atlas-nota/stream", json={"abbr": "ori"},
        ) as r:
            assert r.status_code == 200
            raw = r.read().decode("utf-8")

    frames = _parse_sse_frames(raw)
    events = [ev for ev, _ in frames]
    assert "reset" in events
    assert "done" in events
    done_payload = next(d for ev, d in frames if ev == "done")
    assert done_payload["degraded"] is True
    assert done_payload["source"] == "preset"
    # 异常类型映射后是个具体 reason（不同 service 分类）——只要是 AI_* 即可
    assert done_payload["degraded_reason"].startswith("AI_")
    # 降级后 intro 来自 caption
    assert "冬夜之王" in done_payload["intro"]


def test_stream_sse_invalid_abbr_returns_404():
    """未知 abbr → 404 HTTP（校验在端点入口，未进 SSE 流）。"""
    c = TestClient(app)
    r = c.post("/api/atlas-nota/stream", json={"abbr": "draco"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CONSTELLATION_NOT_FOUND"
