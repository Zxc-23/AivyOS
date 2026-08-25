"""任务注册表：内存 dict 存储 job 元信息。"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional


class JobRegistry:
    """任务注册表（内存实现，可选 SQLite 持久化）。

    负责 job 的增删查，保存 job_id → {trigger, coro_fn, args} 映射。
    """

    def __init__(self) -> None:
        """初始化空注册表。"""
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        job_id: str,
        trigger: Any,
        coro_fn_ref: Callable[..., Awaitable[Any]],
        args: tuple = (),
    ) -> None:
        """注册一个任务。

        参数:
            job_id: 任务唯一标识
            trigger: 触发器实例（CronTrigger / EventTrigger / ConditionTrigger）
            coro_fn_ref: async 函数引用，触发时被调用
            args: 传递给 coro_fn_ref 的位置参数元组
        """
        self._jobs[job_id] = {
            "job_id": job_id,
            "trigger": trigger,
            "coro_fn_ref": coro_fn_ref,
            "args": args,
        }

    def unregister(self, job_id: str) -> None:
        """取消注册任务。

        参数:
            job_id: 要取消的任务 ID；不存在时静默忽略
        """
        self._jobs.pop(job_id, None)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        """根据 job_id 查询任务。

        参数:
            job_id: 任务 ID

        返回:
            任务 dict（含 job_id / trigger / coro_fn_ref / args），不存在返回 None
        """
        return self._jobs.get(job_id)

    def list(self) -> List[Dict[str, Any]]:
        """列出所有已注册任务。

        返回:
            任务 dict 列表（浅拷贝）
        """
        return [dict(job) for job in self._jobs.values()]
