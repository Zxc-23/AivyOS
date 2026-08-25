"""托盘分级通知管理器（文档 AIVY-DDD-004 §3.6 / T7.10）：四级通知 + 勿扰排队。

级别（§3.6）：
- urgent    紧急：系统异常/安全告警/认证失败 —— 绕过勿扰 + 图标红闪 + 提示音
- important 重要：任务完成/更新可用/文件分析完成 —— 提示音，勿扰静默排队
- normal    普通：AI 主动建议/摘要/提醒 —— 无音，勿扰静默排队
- silent    静默：后台整理完成 —— 仅入通知中心，不弹气泡

零依赖：send() 走回调钩子（壳层接 Tauri notification / win10toast 可选），
勿扰模式与排队逻辑为纯 Python，可单测。
"""

from __future__ import annotations

import logging
log = logging.getLogger(__name__)

import time
from typing import Any, Callable, Dict, List, Optional

NOTIFY_LEVELS: Dict[str, Dict[str, Any]] = {
    "urgent":    {"bypass_dnd": True,  "sound": True,  "icon_flash": True,  "duration_ms": 0},
    "important": {"bypass_dnd": False, "sound": True,  "icon_flash": False, "duration_ms": 5000},
    "normal":    {"bypass_dnd": False, "sound": False, "icon_flash": False, "duration_ms": 4000},
    "silent":    {"bypass_dnd": False, "sound": False, "icon_flash": False, "duration_ms": 0},
}


class TrayNotificationManager:
    def __init__(self, dnd: bool = False, sender=None, icon_flash=None, sound=None) -> None:
        """
        dnd: 当前勿扰模式（§3.6）
        sender: async def send(title, body, level, actions) -> None（壳层接系统通知）
        icon_flash: async def flash(state) -> None（urgent 时托盘图标红闪）
        sound: async def play(name) -> None（提示音）
        """
        self.dnd = dnd
        self.sender = sender
        self.icon_flash = icon_flash
        self.sound = sound
        self._queue: List[Dict[str, Any]] = []  # 勿扰静默排队（§3.6）
        self._sent: List[Dict[str, Any]] = []

    def set_dnd(self, active: bool) -> None:
        self.dnd = active

    def _level_cfg(self, level: str) -> Dict[str, Any]:
        return NOTIFY_LEVELS.get(level, NOTIFY_LEVELS["normal"])

    async def send(self, title: str, body: str, level: str = "normal", actions: Optional[list] = None) -> Dict[str, Any]:
        """发送分级通知（§3.6）：勿扰非绕过级别 → 静默排队；否则按策略投递。"""
        cfg = self._level_cfg(level)
        if not cfg["bypass_dnd"] and self.dnd:
            item = {
                "title": title, "body": body, "level": level,
                "actions": actions or [], "ts": time.time(),
            }
            self._queue.append(item)
            return {"queued": True, "level": level, "reason": "dnd"}
        await self._dispatch(title, body, level, actions or [], cfg)
        return {"queued": False, "level": level}

    async def _dispatch(self, title: str, body: str, level: str, actions: list, cfg: Dict[str, Any]) -> None:
        if cfg["icon_flash"] and self.icon_flash is not None:
            try:
                await self.icon_flash("error")
            except Exception as e:
                log.debug("忽略预期内异常: %s", e, exc_info=True)
        if cfg["sound"] and self.sound is not None:
            try:
                await self.sound("notification.wav")
            except Exception as e:
                log.debug("忽略预期内异常: %s", e, exc_info=True)
        if self.sender is not None:
            try:
                await self.sender(title, body, level, actions)
            except Exception as e:
                log.debug("忽略预期内异常: %s", e, exc_info=True)
        self._sent.append({"title": title, "body": body, "level": level, "ts": time.time()})

    async def flush_pending(self) -> int:
        """勿扰结束后批量投递排队通知（§3.6）。返回投递条数。"""
        if self.dnd:
            return 0
        n = len(self._queue)
        items, self._queue = self._queue, []
        for it in items:
            await self._dispatch(it["title"], it["body"], it["level"], it["actions"], self._level_cfg(it["level"]))
        return n

    def pending_count(self) -> int:
        return len(self._queue)

    def sent_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._sent[-limit:]

    def status(self) -> Dict[str, Any]:
        return {"dnd": self.dnd, "queued": len(self._queue), "sent": len(self._sent)}
