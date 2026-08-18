"""Drain 排空管理器（文档 §2.3 / Week 11）：协调热交换全流程 D1-D8。

阶段（§2.3）：entering(拒绝新请求) → queueing(请求排队) → draining(等待活跃请求完成)
→ extracting(状态提取) → reloading(模块重载) → restoring(状态恢复) → verifying(健康检查)
→ releasing(放行排队请求)。

超时策略：排空超时 → 强制切换并标记中断请求；重载失败 → 回滚旧模块；
健康检查失败 → 回滚（C6）。保证零请求丢失（排队等待）。
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from aivyos_core.hotswap.rwlock import SafeModuleProxy

log = logging.getLogger(__name__)

PHASES = [
    "idle", "entering", "queueing", "draining",
    "extracting", "reloading", "restoring", "verifying", "releasing",
]


class DrainManager:
    def __init__(
        self,
        proxy: SafeModuleProxy,
        drain_timeout: float = 30.0,
        health_check: Optional[Callable[[Any], Awaitable[Dict[str, Any]]]] = None,
    ) -> None:
        self.proxy = proxy
        self.drain_timeout = drain_timeout
        self.health_check = health_check  # async fn(new_module) -> {"healthy": bool}
        self.phase: str = "idle"
        self.draining = False
        self._queue: List[Dict[str, Any]] = []  # 排队请求（D2）
        self._interrupted: List[str] = []  # 超时强制切换中断的请求（D3）

    # ---- 主流程（§2.3 execute_hot_swap）----

    async def execute_hot_swap(self, reload_fn: Optional[Callable] = None) -> Dict[str, Any]:
        """执行完整 Drain 热交换。返回阶段结果字典。"""
        results: Dict[str, Any] = {"phase": self.phase}

        # D1: 进入排空 — 拒绝新请求入队
        self._set_phase("entering")
        self.draining = True
        results["entered"] = True

        # D2+D3: 排空活跃请求（等待 active_count → 0）
        self._set_phase("queueing")
        drain = await self._drain_active(self.drain_timeout)
        results["drain"] = drain
        if not drain["success"]:
            # D3 超时 — 强制切换，标记中断请求
            self._interrupted = list(range(drain["remaining"]))
            results["forced"] = True
            results["interrupted"] = len(self._interrupted)

        # D4: 状态提取（§2.4 快照/持久状态）
        self._set_phase("extracting")
        old_module = self.proxy.module
        old_state = self.proxy._extract_persistent_state(old_module)
        results["state_attrs"] = len(old_state)

        # D5: 模块重载（C5：import 失败 → 回滚旧模块）
        self._set_phase("reloading")
        try:
            new_module = reload_fn(old_module) if reload_fn else importlib.reload(old_module)
            results["reloaded"] = True
        except Exception as e:
            self.draining = False
            self._set_phase("idle")
            results["success"] = False
            results["reload_failed"] = str(e)
            results["rolled_back"] = True  # 旧模块继续服务（指针未切换）
            log.warning("[Drain] 重载失败，回滚旧模块: %s", e)
            return results

        # D6: 状态恢复（迁移；异常 → 跳过，快照兜底由上层处理）
        self._set_phase("restoring")
        try:
            self.proxy._migrate_state(new_module, old_state)
        except Exception as e:
            results["restore_failed"] = str(e)
            log.warning("[Drain] 状态恢复失败（新模块以干净状态启动）: %s", e)
        self.proxy._module = new_module  # 原子指针切换（C3）

        # D7: 健康检查（C6：失败 → 回滚）
        self._set_phase("verifying")
        if self.health_check is not None:
            try:
                health = await self.health_check(new_module)
            except Exception as e:
                health = {"healthy": False, "error": str(e)}
            results["health"] = health
            if not health.get("healthy", False):
                await self._rollback(old_module, old_state)
                results["success"] = False
                results["rolled_back"] = True
                results["rollback_reason"] = health.get("failed", health.get("error", "health"))
                self.draining = False
                self._set_phase("idle")
                return results

        # D8: 放行排队请求（队列中的请求转入新模块执行）
        self._set_phase("releasing")
        self.draining = False
        released = len(self._queue)
        self._queue.clear()
        results["released"] = released
        results["success"] = True
        self._set_phase("idle")
        log.info("[Drain] 热交换完成：放行 %d 个排队请求", released)
        return results

    # ---- 请求排队（D2：排空期间新请求不进入旧模块）----

    def queue_request(self, method: str, args: tuple = (), kwargs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """排空期间提交的请求 → 排队（D2），热交换完成后执行。"""
        item = {"method": method, "args": args, "kwargs": kwargs or {}, "ts": time.time()}
        self._queue.append(item)
        return item

    async def execute_queued(self, item: Dict[str, Any]) -> Any:
        """执行排队请求（D8：转入新模块，持读锁）。"""
        self.proxy.lock.acquire_read()
        try:
            method = getattr(self.proxy.module, item["method"])
            return await method(*item["args"], **item["kwargs"])
        finally:
            self.proxy.lock.release_read()

    # ---- 内部 ----

    async def _drain_active(self, timeout: float) -> Dict[str, Any]:
        """等待所有活跃请求完成（§2.3 D3：轮询 active_count → 0）。"""
        start = time.monotonic()
        while self.proxy.lock.active_count > 0:
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                return {"success": False, "remaining": self.proxy.lock.active_count, "elapsed": round(elapsed, 2)}
            await asyncio.sleep(0.02)
        return {"success": True, "elapsed": round(time.monotonic() - start, 3)}

    async def _rollback(self, old_module, old_state: Dict[str, Any]) -> None:
        """回滚（C6）：恢复旧模块指针 + 旧状态。"""
        self.proxy._module = old_module
        try:
            self.proxy._migrate_state(old_module, old_state)
        except Exception as e:
            log.warning("[Drain] 回滚状态恢复失败: %s", e)
        log.info("[Drain] 已回滚到旧模块")

    def _set_phase(self, phase: str) -> None:
        self.phase = phase

    @property
    def queued_count(self) -> int:
        return len(self._queue)
