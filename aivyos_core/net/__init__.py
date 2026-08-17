"""网络层：最小 WebSocket 实时通道（RFC6455，零依赖）。"""

from aivyos_core.net.ws import (
    WebSocketConnection,
    WebSocketError,
    WebSocketServer,
    compute_accept,
)

__all__ = ["WebSocketConnection", "WebSocketError", "WebSocketServer", "compute_accept"]
