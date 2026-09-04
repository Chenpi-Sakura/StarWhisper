"""Photo / atlas 故事共用节流工具（熔断 + 限流）。

- CircuitBreaker：固定窗口冷却熔断（P1-9）。冷却期内 allow() 返回 False。
- check_rate_limit：按客户端 IP 的固定窗口限流（P1-10）。超限抛 429 RATE_LIMITED。
- get_circuit：每路由独立实例（photo 与 atlas 互不干扰——一个熔断了不影响另一个）。

I5 提取：从 routers/story.py 与 routers/atlas_story.py 的重复实现抽出。
每个 router 持有自己的 CircuitBreaker 实例（photo vs atlas 独立熔断窗口），
但 class / helper / 限流桶锁 都共享，避免 100% 重复。
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from fastapi import HTTPException, Request

from config import (
    STORY_CB_COOLDOWN,
    STORY_CB_THRESHOLD,
    STORY_RATE_LIMIT,
    STORY_RATE_WINDOW,
)


# ---------- Circuit breaker ----------


class CircuitBreaker:
    """P1-9：AI 故障熔断（固定窗口冷却）。

    连续失败 STORY_CB_THRESHOLD 次后进入 STORY_CB_COOLDOWN 秒冷却期；
    冷却期内 allow() 返回 False（photo-level 直接走 error，atlas 走 preset），
    冷却结束自动半开重试一次。
    """

    def __init__(self, threshold: int, cooldown: float) -> None:
        self._threshold = max(1, threshold)
        self._cooldown = cooldown
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_at: Optional[float] = None

    def allow(self) -> bool:
        """未开启或冷却已过 → True；仍在冷却期 → False。"""
        with self._lock:
            if self._opened_at is None:
                return True
            if time.time() - self._opened_at >= self._cooldown:
                # 冷却结束：半开，放行一次尝试
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._threshold:
                self._opened_at = time.time()

    def reset(self) -> None:
        """恢复初始态（测试夹具用）。"""
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None


# 每路由独立实例（photo 与 atlas 互不干扰）
_circuits: dict[str, CircuitBreaker] = {}
_circuits_lock = threading.Lock()


def get_circuit(name: str) -> CircuitBreaker:
    """按 name 取一个独立 CircuitBreaker（photo / atlas 各一份）。"""
    with _circuits_lock:
        cb = _circuits.get(name)
        if cb is None:
            cb = CircuitBreaker(STORY_CB_THRESHOLD, STORY_CB_COOLDOWN)
            _circuits[name] = cb
        return cb


def reset_all_circuits() -> None:
    """测试夹具用：清空所有路由的熔断器实例（确保用例间状态完全隔离）。"""
    with _circuits_lock:
        for cb in _circuits.values():
            cb.reset()
        _circuits.clear()


# ---------- Rate limit ----------


# 按客户端 IP 的固定窗口限流桶；模块级单例（跨路由共享）。
_RATE_BUCKETS: dict[str, list[float]] = {}
_RATE_LOCK = threading.Lock()


def check_rate_limit(request: Request) -> None:
    """P1-10：超限抛 429 RATE_LIMITED；窗口过期的时间戳惰性清理。

    STORY_RATE_LIMIT <= 0 时关掉限流。
    """
    if STORY_RATE_LIMIT <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE_BUCKETS.get(ip, []) if now - t < STORY_RATE_WINDOW]
        if len(hits) >= STORY_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "RATE_LIMITED",
                    "message": "请求过于频繁，请稍后再试",
                },
            )
        hits.append(now)
        _RATE_BUCKETS[ip] = hits
        # 防桶泄漏：桶数超阈值时顺手清掉全过期 ip（低频执行）
        if len(_RATE_BUCKETS) > 1024:
            for k in [k for k, v in _RATE_BUCKETS.items() if not v or now - v[-1] >= STORY_RATE_WINDOW]:
                _RATE_BUCKETS.pop(k, None)


def reset_rate_limit_buckets() -> None:
    """测试夹具用：清空所有 IP 限流桶。"""
    with _RATE_LOCK:
        _RATE_BUCKETS.clear()
