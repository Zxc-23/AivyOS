"""MCP search Server（文档 §5.1.2 / T3.7）：SearXNG 集成 + mock 回退。"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from aivyos_core.mcp.types import PermissionLevel, Tool, ToolResult, make_tool


class SearchServer:
    def __init__(self, searxng_url: Optional[str] = None, timeout_s: float = 15.0) -> None:
        self.url = (searxng_url or "").rstrip("/")
        self.timeout_s = timeout_s
        self.backend = "searxng" if self.url else "mock"

    def _search_searxng(self, query: str, n: int) -> List[Dict[str, str]]:
        url = f"{self.url}/search?q={urllib.parse.quote(query)}&format=json"
        with urllib.request.urlopen(url, timeout=self.timeout_s) as r:
            data = json.loads(r.read().decode())
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in data.get("results", [])[:n]
        ]

    async def _search(self, args: Dict[str, Any]) -> ToolResult:
        query = args.get("query", "")
        n = int(args.get("top_k", 5))
        if not query:
            return ToolResult(False, error="query 为空")
        try:
            if self.backend == "searxng":
                results = self._search_searxng(query, n)
                return ToolResult(True, data={"results": results, "backend": "searxng"})
            return ToolResult(
                True,
                content=f"（mock search）查询「{query}」：配置 SearXNG（mcp.search.searxng_url）后返回真实结果",
                data={"backend": "mock", "results": []},
            )
        except Exception as e:
            return ToolResult(False, error=f"搜索失败: {e}")

    def tools(self) -> list[Tool]:
        return [
            make_tool(
                "web_search", "互联网搜索（L0 只读）",
                {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["query"]},
                self._search, PermissionLevel.L0, server="search",
            ),
        ]
