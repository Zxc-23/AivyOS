"""Phase 3: LLM 路由 MCP Server — 将 LLM 能力暴露为 MCP 工具。

允许外部 MCP 客户端调用 AivyOS 的 LLM 路由能力：
    - mcp_llm_chat: 对话完成（带路由）
    - mcp_llm_embed: 嵌入向量
    - mcp_llm_list_models: 列出可用模型
    - mcp_llm_health: 健康检查

用途：
    - 其他 Agent/MCP Server 可通过此接口获取 AivyOS 的 LLM 能力
    - 实现报告 §Phase 3 MCP Server 双向暴露

注意：此模块为可选扩展，不影响核心功能。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

# MCP 工具定义 schema
MCP_TOOL_SCHEMAS = {
    "mcp_llm_chat": {
        "name": "mcp_llm_chat",
        "description": "使用 AivyOS LLM 路由引擎进行对话，自动选择最优后端",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "description": "对话消息列表 [{role, content}]",
                    "items": {"type": "object"},
                },
                "model": {
                    "type": "string",
                    "description": "指定模型（可选，默认自动路由）",
                },
                "stream": {
                    "type": "boolean",
                    "description": "是否流式响应",
                    "default": False,
                },
                "temperature": {
                    "type": "number",
                    "description": "温度参数 0-2",
                    "default": 0.7,
                },
            },
            "required": ["messages"],
        },
    },
    "mcp_llm_list_models": {
        "name": "mcp_llm_list_models",
        "description": "列出所有可用的 LLM 后端及其状态",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_disabled": {
                    "type": "boolean",
                    "description": "是否包含已禁用的后端",
                    "default": False,
                },
            },
        },
    },
    "mcp_llm_health": {
        "name": "mcp_llm_health",
        "description": "获取 LLM 路由健康仪表盘",
        "inputSchema": {
            "type": "object",
            "properties": {
                "backend": {
                    "type": "string",
                    "description": "指定后端名称（可选）",
                },
            },
        },
    },
    "mcp_llm_cost": {
        "name": "mcp_llm_cost",
        "description": "获取成本追踪数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "backend": {
                    "type": "string",
                    "description": "指定后端名称（可选）",
                },
                "recent": {
                    "type": "boolean",
                    "description": "是否包含最近记录",
                    "default": False,
                },
            },
        },
    },
}


class LLMMcpServer:
    """LLM 路由 MCP Server 适配器。

    将 ModelRouter 的能力暴露为 MCP 工具调用。
    支持 MCP 协议的工具注册和调用模式。

    用法：
        from aivyos_core.llm.mcp_server import LLMMcpServer
        mcp = LLMMcpServer(router)
        tools = mcp.list_tools()
        result = mcp.call_tool("mcp_llm_chat", {"messages": [...]})
    """

    def __init__(self, router) -> None:
        """初始化 LLM MCP Server。

        Args:
            router: ModelRouter 实例。
        """
        self._router = router
        self._tools: Dict[str, Callable] = {
            "mcp_llm_chat": self._handle_chat,
            "mcp_llm_list_models": self._handle_list_models,
            "mcp_llm_health": self._handle_health,
            "mcp_llm_cost": self._handle_cost,
        }

    @property
    def name(self) -> str:
        return "aivyos-llm-router"

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有可用的 MCP 工具。

        Returns:
            工具 schema 列表。
        """
        return list(MCP_TOOL_SCHEMAS.values())

    def call_tool(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """调用指定 MCP 工具。

        Args:
            name: 工具名称。
            params: 工具参数。

        Returns:
            工具执行结果。

        Raises:
            ValueError: 工具不存在。
        """
        handler = self._tools.get(name)
        if handler is None:
            return {"error": f"未知工具: {name}", "available": list(self._tools.keys())}
        try:
            return handler(params)
        except Exception as e:
            log.exception("MCP 工具 %s 执行失败", name)
            return {"error": str(e), "tool": name}

    async def call_tool_async(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """异步调用 MCP 工具。

        Args:
            name: 工具名称。
            params: 工具参数。

        Returns:
            工具执行结果。
        """
        handler = self._tools.get(name)
        if handler is None:
            return {"error": f"未知工具: {name}"}
        try:
            # chat 工具需要异步
            if name == "mcp_llm_chat":
                return await self._handle_chat_async(params)
            return handler(params)
        except Exception as e:
            log.exception("MCP 工具 %s 执行失败", name)
            return {"error": str(e), "tool": name}

    # ====================================================================
    #  工具处理器
    # ====================================================================

    def _handle_chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理对话请求（同步）。"""
        import asyncio
        return asyncio.run(self._handle_chat_async(params))

    async def _handle_chat_async(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理对话请求（异步）。"""
        from aivyos_core.models import LLMRequest, RouteDecision, RouteMode

        messages = params.get("messages", [])
        model_hint = params.get("model", "")
        stream = params.get("stream", False)

        # 构建请求
        text = messages[-1].get("content", "") if messages else ""
        request = LLMRequest(messages=messages, model=model_hint or "auto")

        # 路由
        if model_hint:
            decision = RouteDecision(
                RouteMode.CLOUD, model_hint, f"MCP 指定模型: {model_hint}"
            )
        else:
            decision = self._router.route(text)

        # 执行
        try:
            if stream:
                chunks = []
                async for chunk in self._router.stream(request, decision):
                    chunks.append(chunk.text)
                return {
                    "text": "".join(chunks),
                    "model": decision.model,
                    "route": decision.to_dict(),
                    "streamed": True,
                }
            else:
                response = await self._router.complete(request, decision)
                return {
                    "text": response.text,
                    "model": response.model,
                    "route": decision.to_dict(),
                    "usage": response.usage,
                    "latency_ms": response.latency_ms,
                }
        except Exception as e:
            return {"error": str(e), "route": decision.to_dict()}

    def _handle_list_models(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """列出可用模型。"""
        include_disabled = params.get("include_disabled", False)
        status = self._router.backends_status()
        if not include_disabled:
            status = [s for s in status if s.get("available", True)]
        return {"models": status, "count": len(status)}

    def _handle_health(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """健康检查。"""
        backend = params.get("backend")
        if backend:
            stats = self._router.cost_tracker.get_stats(backend)
            return {"backend": backend, "stats": stats}
        return self._router.cost_tracker.get_dashboard()

    def _handle_cost(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """成本追踪。"""
        backend = params.get("backend")
        recent = params.get("recent", False)

        if backend:
            stats = self._router.cost_tracker.get_stats(backend)
        else:
            stats = self._router.cost_tracker.get_dashboard()

        if recent:
            stats["recent"] = self._router.cost_tracker.get_recent(limit=20)

        return stats


def create_mcp_server(router) -> LLMMcpServer:
    """创建 LLM MCP Server 实例。

    Args:
        router: ModelRouter 实例。

    Returns:
        LLMMcpServer 实例。
    """
    return LLMMcpServer(router)