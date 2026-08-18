"""系统托盘与桌面端工程化（Phase 3 Week 9 / T7.x）。

- state_machine：托盘 8 状态机（§3.1）
- notify：分级通知管理器（§3.6）
- file_router：拖拽文件类型路由（§3.5）
"""

from aivyos_core.tray.file_router import ANALYZERS, EXT_ROUTES, FileRoute, route_file, route_files, supported_extensions
from aivyos_core.tray.notify import NOTIFY_LEVELS, TrayNotificationManager
from aivyos_core.tray.state_machine import (
    STATE_VISUALS,
    TRAY_STATES,
    TrayStateMachine,
)

__all__ = [
    "TRAY_STATES", "STATE_VISUALS", "TrayStateMachine",
    "NOTIFY_LEVELS", "TrayNotificationManager",
    "ANALYZERS", "EXT_ROUTES", "FileRoute", "route_file", "route_files", "supported_extensions",
]
