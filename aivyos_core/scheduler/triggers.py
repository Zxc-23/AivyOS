"""触发器模块：CronTrigger / EventTrigger / ConditionTrigger。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict


@dataclass
class CronTrigger:
    """Cron 触发器：支持 MVP 两种表达式 * * * * * 和 N H * * *。

    参数:
        spec: cron 表达式字符串（MVP 仅支持 "* * * * *" 或 "N H * * *"）

    异常:
        NotImplementedError: 其他复杂 cron spec 暂不支持
    """

    spec: str

    def next_fire_at(self, after: datetime) -> datetime:
        """计算 after 之后的下一次触发时间。

        参数:
            after: 基准时间

        返回:
            下一次触发的 datetime

        异常:
            NotImplementedError: spec 不是 MVP 支持的两种格式时抛出
        """
        try:
            import schedule as _schedule  # type: ignore

            return self._next_via_schedule(after)
        except ImportError:
            return self._next_manual(after)

    def _next_via_schedule(self, after: datetime) -> datetime:
        """通过 schedule 包解析（若可用）。"""
        import schedule as _schedule  # type: ignore

        parts = self.spec.split()
        if len(parts) != 5:
            raise NotImplementedError("MVP 仅支持 */N N * * * 两种")
        minute, hour, day, month, weekday = parts
        if self.spec == "* * * * *":
            return (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
        if re.match(r"^\d+ \d+ \* \* \*$", self.spec):
            m = int(minute)
            h = int(hour)
            candidate = after.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate <= after:
                candidate += timedelta(days=1)
            return candidate
        raise NotImplementedError("MVP 仅支持 */N N * * * 两种")

    def _next_manual(self, after: datetime) -> datetime:
        """手写最小 cron parse（schedule 不可用时）。"""
        if self.spec == "* * * * *":
            return (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
        if re.match(r"^\d+ \d+ \* \* \*$", self.spec):
            parts = self.spec.split()
            m = int(parts[0])
            h = int(parts[1])
            candidate = after.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate <= after:
                candidate += timedelta(days=1)
            return candidate
        raise NotImplementedError("MVP 仅支持 */N N * * * 两种")


@dataclass
class EventTrigger:
    """事件触发器：按事件名匹配。

    参数:
        name: 事件名称字符串
    """

    name: str

    def match(self, ev_name: str, payload: Any) -> bool:
        """判断事件名是否匹配。

        参数:
            ev_name: 传入的事件名
            payload: 事件负载（未使用，保持接口兼容）

        返回:
            bool: ev_name 与触发器 name 相等时返回 True
        """
        return ev_name == self.name


@dataclass
class ConditionTrigger:
    """条件触发器：表达式 eval 为 True 且冷却期满足才触发。

    参数:
        expr: 可 eval 的 Python 表达式字符串，可用 ctx 变量引用上下文
        cooldown_seconds: 两次触发最小间隔秒数，默认 60.0
    """

    expr: str
    cooldown_seconds: float = 60.0
    _last_fired_ts: float = field(default=0.0, init=False, repr=False)

    def evaluate(self, ctx: Dict) -> bool:
        """安全 eval 表达式，冷却通过且表达式为 True 时触发。

        参数:
            ctx: 上下文字典，表达式中可通过 ctx['key'] 访问

        返回:
            bool: True 表示本次触发；False 表示未触发
        """
        try:
            result = eval(self.expr, {"__builtins__": {}}, {"ctx": ctx})
        except Exception:
            return False
        if not result:
            return False
        now = time.time()
        if (now - self._last_fired_ts) >= self.cooldown_seconds:
            self._last_fired_ts = now
            return True
        return False
