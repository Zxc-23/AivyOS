"""IPC 协议（文档 §16.2）：JSON 信封 + 长度前缀帧。

信封为 JSON-RPC 2.0 风格：
  Request      { "jsonrpc": "2.0", "id": 1, "method": "chat.send", "params": {...} }
  Response     { "jsonrpc": "2.0", "id": 1, "result": {...} }
  Error        { "jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "..."} }
  Notification { "jsonrpc": "2.0", "method": "event", "params": {...} }   # 无 id
帧格式：4 字节大端长度前缀 + UTF-8 JSON（单帧最大 16MB）。
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

FRAME_HEADER = struct.Struct(">I")
MAX_FRAME = 16 * 1024 * 1024


class ProtocolError(Exception):
    pass


@dataclass
class Request:
    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Request":
        return cls(method=d["method"], params=d.get("params", {}) or {}, id=d.get("id"))


@dataclass
class Response:
    id: Optional[int]
    result: Any = None
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"jsonrpc": "2.0", "id": self.id}
        if self.error is not None:
            out["error"] = self.error
        else:
            out["result"] = self.result
        return out


@dataclass
class Notification:
    method: str
    params: Dict[str, Any] = field(default_factory=dict)


def encode_frame(obj: Dict[str, Any]) -> bytes:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_FRAME:
        raise ProtocolError(f"帧过大: {len(data)} bytes")
    return FRAME_HEADER.pack(len(data)) + data


class FrameCodec:
    """流式帧解码：喂入字节，产出完整 JSON 对象。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[Dict[str, Any]]:
        self._buf.extend(chunk)
        out: list[Dict[str, Any]] = []
        while True:
            if len(self._buf) < FRAME_HEADER.size:
                break
            (length,) = FRAME_HEADER.unpack_from(self._buf, 0)
            if length > MAX_FRAME:
                raise ProtocolError(f"帧长度越界: {length}")
            if len(self._buf) < FRAME_HEADER.size + length:
                break
            payload = bytes(self._buf[FRAME_HEADER.size : FRAME_HEADER.size + length])
            del self._buf[: FRAME_HEADER.size + length]
            try:
                out.append(json.loads(payload.decode("utf-8")))
            except json.JSONDecodeError as e:
                raise ProtocolError(f"JSON 解析失败: {e}") from e
        return out


def parse_message(obj: Dict[str, Any]) -> Request | Notification:
    """按信封解析为 Request 或 Notification；非法信封抛 ProtocolError。"""
    if not isinstance(obj, dict) or obj.get("jsonrpc") != "2.0" or "method" not in obj:
        raise ProtocolError(f"非法信封: {obj}")
    if "id" in obj:
        return Request.from_dict(obj)
    return Notification(method=obj["method"], params=obj.get("params", {}) or {})
