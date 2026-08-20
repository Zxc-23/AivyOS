"""熔断器模块 — 每后端独立的 Circuit Breaker 实现。

参考 LiteLLM 熔断器设计，实现三态状态机（CLOSED / OPEN / HALF_OPEN），
用于在后端连续失败时自动断路、冷却后探测恢复、恢复成功后自动闭合。

典型用法：
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    if cb.is_closed:
        result = await backend.complete(request)
        cb.record_success()
    else:
        # 熔断中，跳过或走降级链
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional

log = logging.getLogger(__name__)


class CircuitBreaker:
    """单后端熔断器 — 线程安全的状态机。

    状态转换：
        CLOSED ──(连续 N 次失败)──▶ OPEN
          ▲                          │
          │                          │ 冷却期结束
          │                          ▼
          └──(探测成功)──── HALF_OPEN
              │
              └──(探测失败)──▶ OPEN
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        half_open_max_requests: int = 1,
    ) -> None:
        """初始化熔断器。

        Args:
            failure_threshold: 连续失败次数阈值，超过后熔断。
            cooldown_seconds: 熔断冷却期（秒），期间拒绝所有请求。
            half_open_max_requests: HALF_OPEN 状态下允许的探测请求数。
        """
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._half_open_max = half_open_max_requests

        self._state: str = self.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_at: float = 0.0
        self._half_open_requests: int = 0

        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """当前熔断器状态（线程安全）。"""
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    @property
    def is_closed(self) -> bool:
        """熔断器是否处于闭合或半开状态（允许请求通过）。"""
        return self.state != self.OPEN

    @property
    def failure_count(self) -> int:
        """当前累计失败次数。"""
        with self._lock:
            return self._failure_count

    def record_success(self) -> None:
        """记录一次成功请求。"""
        with self._lock:
            self._failure_count = 0
            self._half_open_requests = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        """记录一次失败请求。"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_at = time.monotonic()

            if self._state == self.HALF_OPEN:
                self._state = self.OPEN
                self._half_open_requests = 0
                log.warning(
                    "熔断器 HALF_OPEN → OPEN：探测请求失败，冷却 %.1fs",
                    self._cooldown,
                )
            elif self._failure_count >= self._failure_threshold:
                self._state = self.OPEN
                log.warning(
                    "熔断器 CLOSED → OPEN：连续 %d 次失败，冷却 %.1fs",
                    self._failure_count,
                    self._cooldown,
                )

    def can_execute(self) -> bool:
        """判断是否允许执行请求（线程安全）。"""
        with self._lock:
            self._maybe_transition_to_half_open()

            if self._state == self.CLOSED:
                return True

            if self._state == self.HALF_OPEN:
                if self._half_open_requests < self._half_open_max:
                    self._half_open_requests += 1
                    return True
                return False

            return False

    def reset(self) -> None:
        """手动重置熔断器到 CLOSED 状态。"""
        with self._lock:
            self._state = self.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_requests = 0
            self._last_failure_at = 0.0

    def get_stats(self) -> Dict[str, object]:
        """获取熔断器统计信息。"""
        with self._lock:
            return {
                "state": self._state,
                "failure_count": self._failure_count,
                "failure_threshold": self._failure_threshold,
                "cooldown_seconds": self._cooldown,
                "last_failure_at": self._last_failure_at,
                "is_closed": self._state != self.OPEN,
            }

    # ---- 内部 ----

    def _maybe_transition_to_half_open(self) -> None:
        """检查是否应从 OPEN 转换为 HALF_OPEN（必须在锁内调用）。"""
        if self._state == self.OPEN:
            elapsed = time.monotonic() - self._last_failure_at
            if elapsed >= self._cooldown:
                self._state = self.HALF_OPEN
                self._half_open_requests = 0
                log.info("熔断器 OPEN → HALF_OPEN：冷却期结束，开始探测")


class CircuitBreakerRegistry:
    """熔断器注册表 — 管理多个后端的熔断器实例。

    每个 LLM 后端通过名称注册独立的熔断器，支持统一查询与重置。
    """

    def __init__(self) -> None:
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> CircuitBreaker:
        """获取或创建指定名称的熔断器。

        Args:
            name: 后端唯一标识。
            failure_threshold: 连续失败阈值。
            cooldown_seconds: 冷却时间。

        Returns:
            CircuitBreaker 实例。
        """
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    failure_threshold=failure_threshold,
                    cooldown_seconds=cooldown_seconds,
                )
            return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """获取指定名称的熔断器（不存在返回 None）。"""
        with self._lock:
            return self._breakers.get(name)

    def reset_all(self) -> None:
        """重置所有熔断器。"""
        with self._lock:
            for cb in self._breakers.values():
                cb.reset()

    def reset(self, name: str) -> bool:
        """重置指定熔断器（返回是否存在）。"""
        with self._lock:
            cb = self._breakers.get(name)
            if cb:
                cb.reset()
                return True
            return False

    def get_all_stats(self) -> Dict[str, Dict[str, object]]:
        """获取所有熔断器统计信息。"""
        with self._lock:
            return {name: cb.get_stats() for name, cb in self._breakers.items()}

    def get_stats(self, name: str) -> Dict[str, object]:
        """获取指定熔断器统计信息。"""
        with self._lock:
            cb = self._breakers.get(name)
            if cb:
                return cb.get_stats()
            return {}

    def list_names(self) -> list:
        """列出所有已注册的熔断器名称。"""
        with self._lock:
            return list(self._breakers.keys())

    def can_execute(self, name: str) -> bool:
        """检查指定熔断器是否允许执行。"""
        with self._lock:
            cb = self._breakers.get(name)
            if cb is None:
                return True
            return cb.can_execute()

    def record_success(self, name: str) -> None:
        """记录成功。"""
        with self._lock:
            cb = self._breakers.get(name)
            if cb:
                cb.record_success()

    def record_failure(self, name: str) -> None:
        """记录失败。"""
        with self._lock:
            cb = self._breakers.get(name)
            if cb:
                cb.record_failure()