"""热交换与热启动（Phase 3 Week 11）：零请求丢失 / 零状态损坏 / 零数据竞争。

- rwlock：模块读写锁 + 安全代理（§2.2，C1/C3）
- drain：Drain 排空八阶段（§2.3，C5/C6）
- breaker：热交换熔断器（§2.6）
- snapshot：状态快照（§3.2）
- health：健康检查（§3.3）
- boot：快速启动（§3.4）
"""

from aivyos_core.hotswap.breaker import HotSwapCircuitBreaker
from aivyos_core.hotswap.boot import FastBoot
from aivyos_core.hotswap.drain import PHASES, DrainManager
from aivyos_core.hotswap.health import DEFAULT_CHECKS, HealthChecker
from aivyos_core.hotswap.rwlock import ModuleRWLock, SafeModuleProxy
from aivyos_core.hotswap.snapshot import StateSnapshot

__all__ = [
    "ModuleRWLock", "SafeModuleProxy",
    "PHASES", "DrainManager",
    "HotSwapCircuitBreaker",
    "StateSnapshot",
    "DEFAULT_CHECKS", "HealthChecker",
    "FastBoot",
]
