"""热交换熔断器（文档 §2.6 / Week 11）：连续失败后停止热交换尝试，降级冷启动安装。

状态机：closed → (连续失败 ≥ threshold) → open → (冷却期后) → half_open → (一次试探)
half_open 成功 → closed；half_open 失败 → open（重新计时）。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)


class HotSwapCircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown: float = 3600,
        on_degrade: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown  # 熔断后冷却 1 小时（§2.6）
        self.failure_count = 0
        self.state = "closed"  # closed / open / half_open
        self.last_failure_time: Optional[float] = None
        self.on_degrade = on_degrade  # 降级回调（通知更新器改用冷启动安装）

    def can_attempt(self) -> bool:
        """是否允许尝试热交换（§2.6）。"""
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.last_failure_time is not None and time.monotonic() - self.last_failure_time > self.cooldown:
                self.state = "half_open"
                return True
            return False
        # half_open：允许一次试探
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            log.warning("[熔断] 热交换连续失败 %d 次，进入熔断，%ss 后重试", self.failure_count, self.cooldown)
            if self.on_degrade is not None:
                try:
                    self.on_degrade("cold_install")
                except Exception as e:
                    log.debug("忽略预期内异常: %s", e, exc_info=True)

    def status(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "threshold": self.failure_threshold,
            "cooldown_s": self.cooldown,
        }
