"""系统托盘 8 状态机（文档 AIVY-DDD-004 §3.1 / T7.1）：零依赖事件驱动状态机。

8 状态：idle 待命 / listening 监听 / working 工作 / voice 语音 /
        updating 更新 / booting 启动 / error 异常 / paused 暂停

- 事件驱动转换（transition 表）
- 守卫（guards）：booting 忽略左键/双击，updating 忽略双击（§3.2/§3.4）
- 监听器（listener）：状态变更回调（壳层据此切换托盘图标）
- 诚实报告：非法转换返回 False 且不改状态（不静默假成功）
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# 8 状态定义（§3.1）
TRAY_STATES: tuple = (
    "idle", "listening", "working", "voice", "updating", "booting", "error", "paused",
)

# 状态 → 视觉表现（§3.1 图标 + tooltip 文案）
STATE_VISUALS: Dict[str, Dict[str, str]] = {
    "idle":      {"icon": "🔵", "tooltip": "AivyOS — 待命中", "color": "#2563EB"},
    "listening": {"icon": "🌀", "tooltip": "AivyOS — 语音监听中", "color": "#0EA5E9"},
    "working":   {"icon": "🟢", "tooltip": "AivyOS — 正在执行任务", "color": "#059669"},
    "voice":     {"icon": "🔊", "tooltip": "AivyOS — 语音对话中", "color": "#7C3AED"},
    "updating":  {"icon": "⏳", "tooltip": "AivyOS — 更新中", "color": "#D97706"},
    "booting":   {"icon": "⚡", "tooltip": "AivyOS — 启动恢复中", "color": "#6366F1"},
    "error":     {"icon": "🔴", "tooltip": "AivyOS — 异常，请关注", "color": "#DC2626"},
    "paused":    {"icon": "⏸️", "tooltip": "AivyOS — 监听已暂停", "color": "#6B7280"},
}

# 事件转换表（§3.1 图 3.1）：event → {from_state: to_state}
TRANSITION_TABLE: Dict[str, Dict[str, str]] = {
    "boot_complete":  {"booting": "idle"},
    "listening_start": {"idle": "listening", "paused": "listening"},
    "listening_stop":  {"listening": "idle"},
    "task_start":      {"idle": "working", "listening": "working"},
    "task_done":       {"working": "idle"},
    "voice_start":     {"idle": "voice", "paused": "voice"},
    "voice_end":       {"voice": "idle"},
    "update_detected": {"idle": "updating", "listening": "updating", "paused": "updating"},
    "install_restart": {"updating": "booting"},
    "pause":           {"idle": "paused", "listening": "paused"},
    "resume":          {"paused": "idle"},
    "error":           None,  # 特殊：任意状态 → error
    "retry_ok":        {"error": "idle"},
}

# 用户动作守卫（§3.2/§3.4）：哪些状态下忽略该动作（返回 False，不转换）
ACTION_GUARDS: Dict[str, Dict[str, bool]] = {
    "left_click":   {"booting": True},   # booting 忽略左键
    "double_click": {"booting": True, "updating": True},  # 启动/更新中忽略双击（§3.4）
}

Listener = Callable[[str, str, str], None]  # (old_state, new_state, event)


class TrayStateError(RuntimeError):
    pass


class TrayStateMachine:
    def __init__(self, initial: str = "booting") -> None:
        if initial not in TRAY_STATES:
            raise TrayStateError(f"非法初始状态: {initial}")
        self.state: str = initial
        self._listeners: List[Listener] = []
        self._history: List[Dict[str, str]] = []

    # ---- 事件驱动转换 ----

    def on(self, event: str) -> bool:
        """触发事件。合法转换 → True 并通知监听器；非法/守卫拦截 → False（不改状态）。"""
        if event == "error":
            return self._set("error", event)
        mapping = TRANSITION_TABLE.get(event)
        if mapping is None:
            raise TrayStateError(f"未知事件: {event}")
        to_state = mapping.get(self.state)
        if to_state is None:
            return False  # 当前状态下该事件无转换（诚实报告）
        return self._set(to_state, event)

    def _set(self, to_state: str, event: str) -> bool:
        if to_state == self.state:
            return False
        old = self.state
        self.state = to_state
        self._history.append({"from": old, "to": to_state, "event": event})
        for fn in self._listeners:
            try:
                fn(old, to_state, event)
            except Exception:
                pass  # 监听器异常不阻断状态机
        return True

    # ---- 守卫（§3.2 左键 / §3.4 双击）----

    def allow_action(self, action: str) -> bool:
        """该动作在当前状态下是否允许（如 booting 下左键/双击被忽略）。"""
        guards = ACTION_GUARDS.get(action)
        if not guards:
            return True
        return not guards.get(self.state, False)

    # ---- 交互辅助（§3.2 左键状态感知）----

    def left_click(self) -> Optional[str]:
        """左键单击：booting 忽略；返回建议动作（toggle/hide/show-error/show-update）。"""
        if not self.allow_action("left_click"):
            return None
        return {
            "error": "show-error",
            "updating": "show-update",
            "working": "show-task",
            "paused": "show-resume",
        }.get(self.state, "toggle")

    def double_click(self) -> bool:
        """双击：进入语音模式（§3.4）。updating/booting 忽略。"""
        return self.allow_action("double_click")

    # ---- 监听器 ----

    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Listener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    # ---- 查询 ----

    def visual(self) -> Dict[str, str]:
        return STATE_VISUALS[self.state]

    def history(self, limit: int = 10) -> List[Dict[str, str]]:
        return self._history[-limit:]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "visual": self.visual(),
            "history": self.history(),
        }
