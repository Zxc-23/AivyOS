"""主动调度器运行器：ActiveScheduler（事件循环 + 三触发驱动）。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from aivyos_core.scheduler.registry import JobRegistry
from aivyos_core.scheduler.triggers import ConditionTrigger, CronTrigger, EventTrigger


def _trigger_info(trigger: Any) -> Dict[str, Any]:
    """将触发器对象转为可序列化字典。"""
    if isinstance(trigger, CronTrigger):
        return {"type": "cron", "spec": trigger.spec}
    if isinstance(trigger, EventTrigger):
        return {"type": "event", "name": trigger.name}
    if isinstance(trigger, ConditionTrigger):
        return {"type": "condition", "expr": trigger.expr, "cooldown_seconds": trigger.cooldown_seconds}
    return {"type": type(trigger).__name__}


class ActiveScheduler:
    """主动调度器：start() 启动后台 task，支持 cron/事件/条件三触发。

    属性:
        _registry: JobRegistry 实例，存储所有注册 job
        _event_listeners: 事件名 → [async_fn] 监听列表
        _task: 后台 _loop 对应的 asyncio.Task，未启动时为 None
        _event_q: asyncio.Queue，存放 (name, payload) 待处理事件
        _stop_flag: bool 标志，_loop 退出条件
        _last_cron_check_ts: float，上次 cron 检查时间戳（秒级）
        _last_condition_check_ts: float，上次条件检查时间戳
        _cron_fire_history: Dict[job_id, datetime]，记录每个 cron job 最近触发时间
        _shared_ctx: Dict，_loop 内部条件评估默认上下文
    """

    def __init__(self) -> None:
        """初始化调度器（未启动状态）。"""
        self._registry: JobRegistry = JobRegistry()
        self._event_listeners: Dict[str, List[Callable[[Any], Awaitable[Any]]]] = {}
        self._task: Optional[asyncio.Task] = None
        self._event_q: asyncio.Queue = asyncio.Queue()
        self._stop_flag: bool = False
        self._last_cron_check_ts: float = 0.0
        self._last_condition_check_ts: float = 0.0
        self._cron_fire_history: Dict[str, datetime] = {}
        self._cron_next_cache: Dict[str, datetime] = {}
        self._shared_ctx: Dict[str, Any] = {}

    def status(self) -> List[Dict[str, Any]]:
        """返回可序列化的任务状态列表。

        返回:
            每个元素包含 job_id、trigger 类型与参数、running 状态。
        """
        running = self._task is not None and not self._task.done()
        return [
            {
                "job_id": job["job_id"],
                "trigger": _trigger_info(job["trigger"]),
                "running": running,
            }
            for job in self._registry.list()
        ]

    def cron(self, job_id: str, spec: str):
        """装饰器：注册一个 cron 任务。

        参数:
            job_id: 任务唯一标识
            spec: cron 表达式字符串

        返回:
            装饰器函数，接收 coroutine function 并注册到注册表。
        """
        def decorator(coro_fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            self._registry.register(job_id, CronTrigger(spec), coro_fn)
            return coro_fn
        return decorator

    async def start(self) -> None:
        """启动后台调度循环 task。

        重复调用幂等：若已启动则直接返回。
        """
        if self._task is not None and not self._task.done():
            return
        self._stop_flag = False
        self._last_cron_check_ts = time.time()
        self._last_condition_check_ts = time.time()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """停止调度循环，等待 task 结束。

        若未启动则直接返回。
        """
        if self._task is None:
            return
        self._stop_flag = True
        try:
            await asyncio.wait_for(self._task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def add_event_listener(
        self,
        name: str,
        async_fn: Callable[[Any], Awaitable[Any]],
    ) -> None:
        """为指定事件名追加监听函数。

        参数:
            name: 事件名称
            async_fn: async 回调，签名为 async_fn(payload)
        """
        self._event_listeners.setdefault(name, []).append(async_fn)

    def fire_event(self, name: str, payload: Any) -> None:
        """非阻塞地投递事件到内部队列（put_nowait）。

        参数:
            name: 事件名称
            payload: 任意负载对象
        """
        self._event_q.put_nowait((name, payload))

    def evaluate_conditions(self, ctx: Dict[str, Any]) -> List[str]:
        """立即遍历注册表中 ConditionTrigger，命中则创建 task 调用 job。

        参数:
            ctx: 条件评估上下文（传给 ConditionTrigger.evaluate）

        返回:
            本次触发的 job_id 列表
        """
        fired_ids: List[str] = []
        for job in self._registry.list():
            trigger = job["trigger"]
            if not isinstance(trigger, ConditionTrigger):
                continue
            if trigger.evaluate(ctx):
                fn = job["coro_fn_ref"]
                args = job["args"]
                asyncio.create_task(fn(*args))
                fired_ids.append(job["job_id"])
        return fired_ids

    async def _loop(self) -> None:
        """主循环：每秒检查 cron、拉取事件队列 fire、每 500ms 评估条件。"""
        while not self._stop_flag:
            now = time.time()

            if (now - self._last_cron_check_ts) >= 1.0:
                self._last_cron_check_ts = now
                self._evaluate_cron_now()

            self._drain_and_fire_events()

            if (now - self._last_condition_check_ts) >= 0.5:
                self._last_condition_check_ts = now
                self.evaluate_conditions(self._shared_ctx)

            await asyncio.sleep(0.05)

    def _evaluate_cron_now(self) -> None:
        """秒级 cron 检查：对每个 CronTrigger 判断 now 是否到达 next_fire_at。"""
        now_dt = datetime.now()
        for job in self._registry.list():
            trigger = job["trigger"]
            if not isinstance(trigger, CronTrigger):
                continue
            job_id = job["job_id"]
            last_fired = self._cron_fire_history.get(job_id)
            try:
                if last_fired is None:
                    if job_id not in self._cron_next_cache:
                        self._cron_next_cache[job_id] = trigger.next_fire_at(now_dt)
                    next_at = self._cron_next_cache[job_id]
                else:
                    next_at = trigger.next_fire_at(last_fired)
            except NotImplementedError:
                continue
            if now_dt >= next_at and (last_fired is None or next_at > last_fired):
                self._cron_fire_history[job_id] = next_at
                self._cron_next_cache.pop(job_id, None)
                fn = job["coro_fn_ref"]
                args = job["args"]
                asyncio.create_task(fn(*args))

    def _drain_and_fire_events(self) -> None:
        """拉取事件队列所有待处理事件：调用 listeners + 匹配 EventTrigger job。"""
        pending: List[tuple] = []
        while True:
            try:
                pending.append(self._event_q.get_nowait())
            except asyncio.QueueEmpty:
                break
        for name, payload in pending:
            for listener in self._event_listeners.get(name, []):
                asyncio.create_task(listener(payload))
            for job in self._registry.list():
                trigger = job["trigger"]
                if isinstance(trigger, EventTrigger) and trigger.match(name, payload):
                    fn = job["coro_fn_ref"]
                    args = job["args"]
                    try:
                        asyncio.create_task(fn(*args, payload=payload))
                    except TypeError:
                        asyncio.create_task(fn(*args))
