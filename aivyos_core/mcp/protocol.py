"""MCP 协议（JSON-RPC 2.0 信封，对齐 MCP 2026-07-28 无状态核心）。

方法：
  tools/list          → {tools: [...]}
  tools/call          → ToolResult；L2+ 无预授权时返回 MRTRRequest（resultType=input_required）
  mrtr/confirm        → {request_id, approved, answer} → 执行/拒绝原调用
  ping                → {pong}

传输：
  - stdio：换行分隔 JSON（MCP 标准）
  - TCP：长度前缀帧（复用 ipc.protocol.FrameCodec）
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from aivyos_core.ipc.protocol import FrameCodec, encode_frame  # noqa: F401（复用）

# ---- stdio 行帧 ----

def encode_line(obj: Dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def decode_line(line: bytes) -> Dict[str, Any]:
    return json.loads(line.decode("utf-8"))


class LineCodec:
    """换行分隔 JSON 解码器（stdio）。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[Dict[str, Any]]:
        self._buf.extend(chunk)
        out: list[Dict[str, Any]] = []
        while True:
            idx = self._buf.find(b"\n")
            if idx < 0:
                break
            line = bytes(self._buf[:idx])
            del self._buf[: idx + 1]
            if line.strip():
                out.append(decode_line(line))
        return out


# ---- 信封 ----

def request(method: str, params: Optional[Dict[str, Any]] = None, rid: Optional[int] = None) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def response(rid: Optional[int], result: Any = None, error: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out
