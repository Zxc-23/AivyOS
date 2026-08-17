"""认证状态机（文档 §9.1 / 任务 T6.6：dormant→listening→verifying→authenticated/rejected）。

- 静默拒绝（§9.1）：rejected 不产生任何响应，超时后自动回到 dormant（不暴露系统存在）
- 事件日志供审计（§19.3 安全审计日志入口）
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AuthState(str, Enum):
    DORMANT = "dormant"          # 待机：AI 核心就绪，等待交互
    LISTENING = "listening"      # 监听：VAD 持续监听语音唤醒
    VERIFYING = "verifying"      # 认证中：声纹/面部/活体比对
    AUTHENTICATED = "authenticated"  # 已认证：进入工作状态
    REJECTED = "rejected"        # 拒绝：静默忽略，保持待机


@dataclass
class AuthEvent:
    ts: float = field(default_factory=time.time)
    action: str = ""
    detail: str = ""


class AuthStateMachine:
    """认证状态机：受保护的转移 + 超时自动重置。"""

    def __init__(self, silent_reject: bool = True, reject_timeout_s: float = 5.0) -> None:
        self.silent_reject = silent_reject
        self.reject_timeout_s = reject_timeout_s
        self.state = AuthState.DORMANT
        self.current_user: Optional[str] = None
        self.events: List[AuthEvent] = []
        self._timer: Optional[asyncio.Task] = None

    # ---- 日志 ----

    def _log(self, action: str, detail: str = "") -> None:
        self.events.append(AuthEvent(action=action, detail=detail))
        self.events = self.events[-200:]  # 只保留最近 200 条

    # ---- 转移 ----

    def wake(self) -> AuthState:
        """监听唤醒（§9.1 步骤 1：VAD 检测到语音活动）。"""
        if self.state in (AuthState.DORMANT, AuthState.REJECTED):
            self.state = AuthState.LISTENING
            self._log("wake", "VAD 检测到语音活动")
        return self.state

    def start_verify(self) -> AuthState:
        if self.state == AuthState.LISTENING:
            self.state = AuthState.VERIFYING
            self._log("start_verify")
        return self.state

    def accept(self, user_id: str, score: float) -> AuthState:
        if self.state in (AuthState.VERIFYING, AuthState.LISTENING):
            self.state = AuthState.AUTHENTICATED
            self.current_user = user_id
            self._log("accept", f"user={user_id} score={score:.3f}")
            self._cancel_timer()
        return self.state

    def reject(self, score: float = 0.0, reason: str = "声纹/面部未匹配") -> AuthState:
        if self.state in (AuthState.VERIFYING, AuthState.LISTENING):
            self.state = AuthState.REJECTED
            self._log("reject", f"score={score:.3f} {reason}")
            if self.silent_reject:
                self._schedule_silent_reset()
        return self.state

    def logout(self) -> AuthState:
        self.state = AuthState.DORMANT
        self.current_user = None
        self._log("logout")
        return self.state

    # ---- 静默重置（§9.1 失败处理）----

    def _schedule_silent_reset(self) -> None:
        self._cancel_timer()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # 无运行中事件循环（纯同步场景）→ 不调度自动重置

        async def _reset():
            await asyncio.sleep(self.reject_timeout_s)
            if self.state == AuthState.REJECTED:
                self.state = AuthState.DORMANT
                self._log("silent_reset", "静默回到待机")

        self._timer = loop.create_task(_reset())

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    # ---- 查询 ----

    def is_authenticated(self) -> bool:
        return self.state == AuthState.AUTHENTICATED

    def status(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "current_user": self.current_user,
            "silent_reject": self.silent_reject,
            "recent_events": [{"ts": e.ts, "action": e.action, "detail": e.detail} for e in self.events[-8:]],
        }
