"""MCP 客户端：TCP 连接服务器，调用工具并处理 MRTR 确认（§5.1.2）。"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from aivyos_core.ipc.protocol import FrameCodec, encode_frame
from aivyos_core.mcp.protocol import request, response

ConfirmFn = Callable[[Dict[str, Any]], bool]  # (mrtr_request) -> approved


class McpClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 31889) -> None:
        self.host = host
        self.port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer = None
        self._seq = 0
        self._codec = FrameCodec()

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    async def _rpc(self, method: str, params: Dict[str, Any]) -> Any:
        self._seq += 1
        self._writer.write(encode_frame(request(method, params, self._seq)))
        await self._writer.drain()
        while True:
            data = await self._reader.read(65536)
            for obj in self._codec.feed(data):
                if obj.get("id") == self._seq:
                    if "error" in obj:
                        raise RuntimeError(obj["error"].get("message", "RPC 错误"))
                    return obj["result"]

    async def list_tools(self) -> List[Dict[str, Any]]:
        return (await self._rpc("tools/list", {}))["tools"]

    async def call_tool(self, name: str, arguments: Dict[str, Any], confirm: Optional[ConfirmFn] = None) -> Any:
        """调用工具；若返回 input_required 则调用 confirm 回调（默认拒绝）。"""
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        if isinstance(result, dict) and result.get("resultType") == "input_required":
            approved = confirm(result) if confirm else False
            out = await self._rpc("mrtr/confirm", {"request_id": result["request_id"], "approved": approved})
            if not out.get("ok"):
                raise RuntimeError(out.get("error", "确认失败"))
            return out.get("result")
        return result

    async def ping(self) -> bool:
        return (await self._rpc("ping", {}))["pong"] is True
