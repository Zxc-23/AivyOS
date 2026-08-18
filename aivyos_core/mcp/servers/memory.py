"""MCP memory Server（文档 §4.2）：包装 MemoryManager 为 MCP 工具。"""

from __future__ import annotations

from typing import Any, Dict

from aivyos_core.mcp.types import PermissionLevel, Tool, ToolResult, make_tool


class MemoryServer:
    def __init__(self, memory_manager) -> None:
        self.memory = memory_manager

    async def _search(self, args: Dict[str, Any]) -> ToolResult:
        hits = await self.memory.search(args.get("query", ""), top_k=int(args.get("top_k", 5)))
        return ToolResult(True, data={"hits": [h.to_dict() for h in hits]})

    async def _add(self, args: Dict[str, Any]) -> ToolResult:
        rid = await self.memory.add(args["text"], metadata={"source": "mcp"})
        return ToolResult(True, content=f"记忆已写入: {rid}", data={"id": rid})

    async def _list(self, args: Dict[str, Any]) -> ToolResult:
        hits = await self.memory.get_all()
        return ToolResult(True, data={"count": len(hits), "hits": [h.to_dict() for h in hits[-20:]]})

    def tools(self) -> list[Tool]:
        return [
            make_tool(
                "mem_search", "检索长期记忆（L0）",
                {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["query"]},
                self._search, PermissionLevel.L0, server="memory",
            ),
            make_tool(
                "mem_add", "写入长期记忆（L1）",
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                self._add, PermissionLevel.L1, server="memory",
            ),
            make_tool(
                "mem_list", "列出记忆（L0）",
                {"type": "object", "properties": {}},
                self._list, PermissionLevel.L0, server="memory",
            ),
        ]
