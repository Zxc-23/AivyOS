"""MCP 服务器（文档 §5.1：工具发现 + 调用 + MRTR 确认机制）。

- 注册 Tool（ToolManager 聚合）
- 传输：stdio（MCP 标准，换行 JSON）/ TCP（长度前缀帧，复用 IPC 编解码）
- MRTR（§5.1.2）：L2+ 工具在无预授权时返回 resultType=input_required，
  客户端确认后以 mrtr/confirm 携带答案重试，服务器执行原调用
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from typing import Any, Dict, Optional

from aivyos_core.ipc.protocol import FrameCodec, encode_frame
from aivyos_core.mcp.protocol import LineCodec, decode_line, encode_line, request, response
from aivyos_core.mcp.types import MRTRRequest, PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)


class McpServer:
    def __init__(
        self,
        tools: Optional[dict[str, Tool]] = None,
        mrtr_ttl_s: float = 60.0,
        auto_approve: bool = False,
    ) -> None:
        self.tools: dict[str, Tool] = tools or {}
        self.mrtr_ttl_s = mrtr_ttl_s
        self.auto_approve = auto_approve
        self._pending: dict[str, MRTRRequest] = {}
        self._approvals: dict[str, float] = {}  # request_id -> approved_at

    # ---- 工具注册 ----

    def add_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def add_tools(self, tools) -> None:
        for t in tools:
            self.add_tool(t)

    # ---- JSON-RPC 分发 ----

    async def handle(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return response(None, error={"code": -32700, "message": "非法信封"})
        rid = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}
        try:
            if method == "ping":
                return response(rid, {"pong": True})
            if method == "tools/list":
                return response(rid, {"tools": [t.to_mcp_schema() for t in self.tools.values()]})
            if method == "tools/call":
                result = await self._call_tool(params)
                return response(rid, result.to_dict() if isinstance(result, ToolResult) else result)
            if method == "mrtr/confirm":
                return response(rid, await self._confirm(params))
            return response(rid, error={"code": -32601, "message": f"未知方法: {method}"})
        except Exception as e:
            log.exception("MCP 方法异常: %s", method)
            return response(rid, error={"code": -32603, "message": str(e)})

    async def _call_tool(self, params: Dict[str, Any]) -> Any:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"未知工具: {name}")
        # MRTR 门控：L2+ 且未预授权（§19.2）
        if tool.permission in (PermissionLevel.L2, PermissionLevel.L3) and not self.auto_approve:
            pre = params.get("approval")  # 客户端可在单次调用内预授权（MRTR 答案形式）
            if pre:
                return await tool.handler(args)
            mrt = MRTRRequest(tool=name, arguments=args, impact=(tool.impact(args) if tool.impact else "执行该工具"))
            self._pending[mrt.request_id] = mrt
            return mrt.to_dict()
        return await tool.handler(args)

    async def _confirm(self, params: Dict[str, Any]) -> Dict[str, Any]:
        rid = params.get("request_id", "")
        mrt = self._pending.pop(rid, None)
        if mrt is None:
            return {"ok": False, "error": f"未知或已过期的确认请求: {rid}"}
        if time.time() - mrt.created_at > self.mrtr_ttl_s:
            return {"ok": False, "error": "确认已超时，请重试调用"}
        if not params.get("approved"):
            return {"ok": True, "result": ToolResult(ok=False, error="用户拒绝执行").to_dict()}
        tool = self.tools.get(mrt.tool)
        if tool is None:
            return {"ok": False, "error": f"工具已注销: {mrt.tool}"}
        result = await tool.handler(mrt.arguments)
        return {"ok": True, "result": result.to_dict()}

    # ---- 传输 ----

    async def serve_stdio(self) -> None:
        """MCP 标准 stdio 传输：换行分隔 JSON。"""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        codec = LineCodec()
        while True:
            line = await reader.readline()
            if not line:
                break
            for obj in codec.feed(line):
                if obj.get("id") is None:
                    continue  # 通知
                resp = await self.handle(obj)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                    sys.stdout.flush()

    async def serve_tcp(self, host: str = "127.0.0.1", port: int = 31889) -> asyncio.AbstractServer:
        async def handle_conn(reader, writer):
            codec = FrameCodec()
            try:
                while True:
                    chunk = await reader.read(65536)
                    if not chunk:
                        break
                    for obj in codec.feed(chunk):
                        if obj.get("id") is None:
                            continue
                        resp = await self.handle(obj)
                        if resp is not None:
                            writer.write(encode_frame(resp))
                            await writer.drain()
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception as e:
                    log.debug("忽略预期内异常: %s", e, exc_info=True)

        server = await asyncio.start_server(handle_conn, host, port)
        log.info("MCP TCP 服务: %s:%d（%d 工具）", host, port, len(self.tools))
        return server
