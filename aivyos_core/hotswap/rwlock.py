"""模块级读写锁与安全代理（文档 §2.2 / Week 11）：解决 C1（执行中热交换）与 C3（并发请求竞争）。

- ModuleRWLock：读锁可并发（正常请求），写锁独占（热交换），引用计数 active_count
- SafeModuleProxy：所有模块调用持读锁；hot_swap 持写锁，提取持久状态 → reload →
  状态迁移 → 原子指针切换（C3：新旧模块不并发执行）

状态持久化协议（§2.4）：
- `_PERSISTENT_STATE__`：需要跨版本保持的属性名列表
- `_STATE_SCHEMA_VERSION__`：状态 schema 版本
- `_migrate_state_(old_state, from_version)`：版本迁移函数（可选）
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


class ModuleRWLock:
    """模块级读写锁 — 读操作可并发，写操作（热交换）独占（§2.2 / C1+C3）。"""

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer_active = False
        self._active_calls = 0  # 引用计数：当前活跃模块调用数

    # ---- 读锁（请求进入/离开模块）----

    def acquire_read(self) -> None:
        with self._cond:
            while self._writer_active:
                self._cond.wait()  # 热交换进行中，等待
            self._readers += 1
            self._active_calls += 1

    def release_read(self) -> None:
        with self._cond:
            self._readers -= 1
            self._active_calls -= 1
            if self._readers == 0:
                self._cond.notify_all()  # 通知等待的写者

    # ---- 写锁（热交换专用）----

    def acquire_write(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._readers > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"热交换超时：仍有 {self._readers} 个请求在执行")
                self._cond.wait(remaining)
            self._writer_active = True

    def release_write(self) -> None:
        with self._cond:
            self._writer_active = False
            self._cond.notify_all()  # 通知排队的读者

    @property
    def active_count(self) -> int:
        with self._cond:
            return self._active_calls

    @property
    def reader_count(self) -> int:
        with self._cond:
            return self._readers

    @property
    def writer_active(self) -> bool:
        with self._cond:
            return self._writer_active


class SafeModuleProxy:
    """安全模块代理 — 所有调用经读写锁保护；hot_swap 原子切换（§2.2）。"""

    def __init__(self, module_name: str, module=None) -> None:
        self.module_name = module_name
        self._lock = ModuleRWLock()
        # module 参数便于测试注入（缺省真实导入）
        self._module = module if module is not None else importlib.import_module(module_name)

    # ---- 安全调用（持读锁，可并发）----

    def call(self, method_name: str, *args, **kwargs) -> Any:
        """同步安全调用模块方法（§2.2 持读锁）。"""
        self._lock.acquire_read()
        try:
            method = getattr(self._module, method_name)
            return method(*args, **kwargs)
        finally:
            self._lock.release_read()

    async def acall(self, method_name: str, *args, **kwargs) -> Any:
        """异步安全调用模块方法。"""
        self._lock.acquire_read()
        try:
            method = getattr(self._module, method_name)
            return await method(*args, **kwargs)
        finally:
            self._lock.release_read()

    # ---- 热交换（持写锁，独占）----

    def hot_swap(self, timeout: float = 30.0, reload_fn: Optional[Callable] = None) -> bool:
        """热交换模块（§2.2）：提取状态 → reload → 迁移 → 原子切换指针。

        reload_fn: 自定义重载函数（默认 importlib.reload），便于测试注入。
        失败（C5：import 失败）→ 不切换指针，旧模块继续服务。
        """
        self._lock.acquire_write(timeout)
        try:
            old_module = self._module
            old_state = self._extract_persistent_state(old_module)

            new_module = reload_fn(old_module) if reload_fn else importlib.reload(old_module)

            self._migrate_state(new_module, old_state)
            self._module = new_module  # 原子指针切换（C3）
            log.info("[热交换] %s 已重载", self.module_name)
            return True
        except Exception as e:
            log.warning("[热交换] %s 失败（旧模块继续服务）: %s", self.module_name, e)
            return False
        finally:
            self._lock.release_write()

    # ---- 状态协议（§2.4）----

    def _extract_persistent_state(self, module) -> Dict[str, Any]:
        """提取 `_PERSISTENT_STATE__` 声明的跨版本状态（§2.4）。"""
        state: Dict[str, Any] = {}
        persistent_attrs = getattr(module, "_PERSISTENT_STATE__", [])
        for attr in persistent_attrs:
            if hasattr(module, attr):
                state[attr] = getattr(module, attr)
        # 记录旧 schema 版本（迁移用）
        state["_state_schema_version__"] = getattr(module, "_STATE_SCHEMA_VERSION__", 1)
        return state

    def _migrate_state(self, new_module, old_state: Dict[str, Any]) -> None:
        """状态迁移（§2.4 / C2）：新模块定义 `_migrate_state_` 则调用，否则直接恢复。"""
        if hasattr(new_module, "_migrate_state_"):
            migrated = new_module._migrate_state_(old_state, from_version=str(old_state.get("_state_schema_version__", 1)))
            for key, val in (migrated or {}).items():
                setattr(new_module, key, val)
        else:
            for key, val in old_state.items():
                if hasattr(new_module, key):
                    setattr(new_module, key, val)

    # ---- 查询 ----

    @property
    def lock(self) -> ModuleRWLock:
        return self._lock

    @property
    def module(self):
        return self._module
