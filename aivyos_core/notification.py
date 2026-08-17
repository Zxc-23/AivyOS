"""原生通知（文档 §12.6 / T4.4）：分级推送适配（win10toast 可选 + console 回退）。"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict


class NotifierUnavailable(RuntimeError):
    pass


class Notifier(ABC):
    name: str = "base"

    @abstractmethod
    def notify(self, title: str, message: str, level: str = "normal") -> Dict[str, Any]:
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    """回退：结构化输出（无桌面通知能力时保底）。"""

    name = "console"

    def notify(self, title: str, message: str, level: str = "normal") -> Dict[str, Any]:
        entry = {
            "level": level,
            "title": title,
            "message": message,
            "ts": time.time(),
            "delivered": False,
            "note": "console 回退（安装 win10toast 后启用系统通知）",
        }
        print(f"[通知/{level}] {title}: {message[:80]}")
        return entry


class WinToastNotifier(Notifier):
    """Windows 系统通知（win10toast 可选依赖）。"""

    name = "win10toast"

    def __init__(self) -> None:
        try:
            from win10toast import ToastNotifier  # type: ignore

            self._toaster = ToastNotifier()
        except ImportError as e:
            raise NotifierUnavailable(
                "win10toast 未安装：pip install win10toast（缺失时降级 console 通知）"
            ) from e

    def notify(self, title: str, message: str, level: str = "normal") -> Dict[str, Any]:
        duration = {"urgent": 10, "important": 6, "normal": 3}.get(level, 3)
        self._toaster.show_toast(title, message, duration=duration, threaded=True)
        return {"level": level, "title": title, "message": message, "delivered": True, "ts": time.time()}


def create_notifier(cfg: Dict[str, Any]) -> Notifier:
    backend = cfg.get("notify_backend", "auto")
    if backend == "console":
        return ConsoleNotifier()
    if backend in ("win_toast", "auto"):
        try:
            return WinToastNotifier()
        except NotifierUnavailable:
            return ConsoleNotifier()
    return ConsoleNotifier()
