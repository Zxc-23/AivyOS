"""主动调度器（文档 §5.3 / T3.10）：定时（Cron）/ 事件 / 条件 触发。

- CronJob：标准 5 字段 cron 表达式（分 时 日 月 周，支持 * / 与数值范围）
- EventJob：asyncio.Event 触发
- ConditionJob：周期性检查条件，满足时执行
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, List, Optional

log = logging.getLogger(__name__)

JobFn = Callable[[], Awaitable[Any]]


class CronError(ValueError):
    pass


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    """解析 cron 字段：* / 数值与范围（如 1-5,10/2）。"""
    if field == "*":
        return set(range(lo, hi + 1))
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            base, step = part.split("/")
            step = int(step)
            if base == "*":
                base_vals = range(lo, hi + 1)
            elif "-" in base:
                a, b = (int(x) for x in base.split("-"))
                base_vals = range(a, b + 1)
            else:
                base_vals = [int(base)]
            out.update(v for v in base_vals if v % step == 0)
        elif "-" in part:
            a, b = (int(x) for x in part.split("-"))
            out.update(range(a, b + 1))
        else:
            v = int(part)
            if v < lo or v > hi:
                raise CronError(f"字段值越界: {v}（{lo}-{hi}）")
            out.add(v)
    return out


class CronSchedule:
    """5 字段 cron：分(0-59) 时(0-23) 日(1-31) 月(1-12) 周(0-6, 0=周日)。"""

    def __init__(self, expr: str) -> None:
        parts = expr.split()
        if len(parts) != 5:
            raise CronError(f"cron 需 5 个字段: {expr}")
        self.minutes = _parse_field(parts[0], 0, 59)
        self.hours = _parse_field(parts[1], 0, 23)
        self.days = _parse_field(parts[2], 1, 31)
        self.months = _parse_field(parts[3], 1, 12)
        self.weekdays = _parse_field(parts[4], 0, 6)

    def matches(self, dt: datetime) -> bool:
        # cron 周几：0=周日…6=周六；Python weekday()：0=周一…6=周日
        cron_weekday = (dt.weekday() + 1) % 7
        return (
            dt.minute in self.minutes
            and dt.hour in self.hours
            and dt.day in self.days
            and dt.month in self.months
            and cron_weekday in self.weekdays
        )

    def next_run(self, after: Optional[datetime] = None) -> Optional[datetime]:
        """计算下一次匹配时间（1 年内，找不到返回 None）。"""
        cur = (after or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(365 * 24 * 60):
            if self.matches(cur):
                return cur
            cur += timedelta(minutes=1)
        return None

    def __repr__(self) -> str:
        return f"CronSchedule({self.minutes}|{self.hours}|{self.days}|{self.months}|{self.weekdays})"


@dataclass
class Job:
    name: str
    fn: JobFn
    schedule: Optional[CronSchedule] = None
    event: Optional[asyncio.Event] = None
    condition: Optional[Callable[[], bool]] = None
    condition_interval_s: float = 60.0
    last_run: Optional[datetime] = None
    runs: int = field(default=0)
    last_error: str = ""

    @property
    def kind(self) -> str:
        if self.schedule:
            return "cron"
        if self.event is not None:
            return "event"
        return "condition"


class Scheduler:
    """主动调度器（§5.3）：Cron / 事件 / 条件 三类任务。"""

    def __init__(self, tick_s: float = 5.0) -> None:
        self.tick_s = tick_s
        self.jobs: List[Job] = []

    # ---- 注册 ----

    def cron(self, name: str, expr: str) -> Callable[[JobFn], JobFn]:
        def deco(fn: JobFn) -> JobFn:
            self.jobs.append(Job(name=name, fn=fn, schedule=CronSchedule(expr)))
            return fn

        return deco

    def on_event(self, name: str, event: asyncio.Event) -> Callable[[JobFn], JobFn]:
        def deco(fn: JobFn) -> JobFn:
            self.jobs.append(Job(name=name, fn=fn, event=event))
            return fn

        return deco

    def on_condition(self, name: str, cond: Callable[[], bool], interval_s: float = 60.0) -> Callable[[JobFn], JobFn]:
        def deco(fn: JobFn) -> JobFn:
            self.jobs.append(Job(name=name, fn=fn, condition=cond, condition_interval_s=interval_s))
            return fn

        return deco

    # ---- 执行 ----

    async def _run_job(self, job: Job) -> None:
        try:
            await job.fn()
            job.runs += 1
            job.last_run = datetime.now()
        except Exception as e:
            job.last_error = str(e)
            log.error("任务执行失败 %s: %s", job.name, e)

    async def run(self) -> None:
        """主循环：tick 检查 cron 分钟匹配 + 条件轮询；事件任务由 set() 唤醒。"""
        last_minute = None
        while True:
            now = datetime.now()
            # Cron：分钟级匹配（§5.3 定时触发）
            if now.minute != last_minute:
                last_minute = now.minute
                for job in self.jobs:
                    if job.schedule and job.schedule.matches(now):
                        asyncio.create_task(self._run_job(job))
            # 条件触发（§5.3 条件监控）
            for job in self.jobs:
                if job.condition and job.condition():
                    asyncio.create_task(self._run_job(job))
            # 事件触发（§5.3 事件触发）
            for job in self.jobs:
                if job.event and job.event.is_set():
                    job.event.clear()
                    asyncio.create_task(self._run_job(job))
            await asyncio.sleep(self.tick_s)

    def status(self) -> List[dict]:
        return [
            {"name": j.name, "kind": j.kind, "runs": j.runs,
             "last_run": str(j.last_run) if j.last_run else None, "error": j.last_error}
            for j in self.jobs
        ]
