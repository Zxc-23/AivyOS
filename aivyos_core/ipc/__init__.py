"""IPC 层（文档 §16.2）：JSON 信封协议 + TCP/NamedPipe 服务端。"""

from aivyos_core.ipc.protocol import (
    FrameCodec,
    Notification,
    ProtocolError,
    Request,
    Response,
    encode_frame,
    parse_message,
)
from aivyos_core.ipc.server import AivyIpcServer

__all__ = [
    "AivyIpcServer",
    "FrameCodec",
    "ProtocolError",
    "Request",
    "Response",
    "Notification",
    "encode_frame",
    "parse_message",
]
