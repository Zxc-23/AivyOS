"""快速启动器（文档 桌面端规格 §3.4 / Week 11）：更新后重启场景分阶段引导。

加速策略（§3.4）：延迟导入非关键模块 / 状态快照原子恢复 / 调度器直接从快照恢复。
分阶段：Phase 1 关键路径（用户可见）→ Phase 2 后台恢复 → Phase 3 完成通知。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from aivyos_core.hotswap.snapshot import StateSnapshot

log = logging.getLogger(__name__)


class FastBoot:
    """快速启动器：注册启动步骤，按阶段执行（关键路径优先，§3.4）。"""

    def __init__(self, snapshot: Optional[StateSnapshot] = None) -> None:
        self.snapshot = snapshot
        self.steps: Dict[int, List[Callable[[], Any]]] = {1: [], 2: [], 3: []}  # phase → steps
        self.timings: Dict[str, float] = {}
        self.results: Dict[str, Any] = {}

    def register(self, name: str, fn: Callable[[], Any], phase: int = 2) -> None:
        """注册启动步骤。phase：1=关键路径（用户可见）2=后台 3=收尾。"""
        if phase not in self.steps:
            raise ValueError(f"非法启动阶段: {phase}（1/2/3）")
        self.steps[phase].append((name, fn))

    async def boot(self) -> Dict[str, Any]:
        """执行完整快速启动（§3.4）。返回各阶段耗时与结果。"""
        total_start = time.monotonic()
        for phase in (1, 2, 3):
            p_start = time.monotonic()
            for name, fn in self.steps[phase]:
                try:
                    r = fn()
                    if asyncio.iscoroutine(r):
                        r = await r
                    self.results[name] = r
                    log.info("[FastBoot] P%d %s: OK", phase, name)
                except Exception as e:
                    self.results[name] = {"error": str(e)}
                    log.warning("[FastBoot] P%d %s: 失败 %s", phase, name, e)
            self.timings[f"phase{phase}"] = round(time.monotonic() - p_start, 3)
        self.timings["total"] = round(time.monotonic() - total_start, 3)
        return {"timings": self.timings, "results": self.results}

    # ---- 便捷恢复器（§3.4 状态恢复 / 调度器恢复）----

    def restore_from_snapshot(self, key: str = "state") -> Callable[[], Optional[Dict[str, Any]]]:
        """从快照原子恢复（§3.2/§3.4：0ms 级恢复）。"""
        if self.snapshot is None:
            return lambda: None

        def _fn():
            snap = self.snapshot.restore()
            if snap is None:
                return None
            return snap.get("state", {}).get(key)
        return _fn

    def restore_scheduler(self) -> Callable[[], Optional[Dict[str, Any]]]:
        """调度器直接从快照恢复任务列表（§3.4：100ms）。"""
        return self.restore_from_snapshot("scheduler")
