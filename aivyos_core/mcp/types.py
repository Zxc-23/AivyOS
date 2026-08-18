"""MCP 类型定义（文档 §5.1：Tool 注册、权限分级 §19.2）。

权限级别（§19.2）：
- L0 只读：文件读取、搜索 → 自动执行
- L1 低危写：文件写入、代码生成 → 自动执行 + 日志
- L2 高危写：Shell 命令、代码执行 → 需用户确认（MRTR）
- L3 危险操作：删除文件、网络外发 → 需确认 + 操作日志
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional


class PermissionLevel(str, Enum):
    L0 = "L0"   # 只读
    L1 = "L1"   # 低危写
    L2 = "L2"   # 高危写（需 MRTR 确认）
    L3 = "L3"   # 危险操作（需确认 + 审计）


ToolHandler = Callable[[Dict[str, Any]], Awaitable["ToolResult"]]
ImpactFn = Callable[[Dict[str, Any]], str]


@dataclass
class Tool:
    """MCP 工具定义（§5.1.1：name/description/inputSchema）。"""

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: ToolHandler
    permission: PermissionLevel = PermissionLevel.L0
    impact: Optional[ImpactFn] = None   # 生成 MRTR 确认时的"预期影响"描述
    server: str = ""

    def to_mcp_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class ToolResult:
    ok: bool
    content: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "content": self.content, "data": self.data, "error": self.error}


@dataclass
class MRTRRequest:
    """MRTR 确认请求（§5.1.2：resultType=input_required）。"""

    request_id: str = field(default_factory=lambda: "mrt_" + uuid.uuid4().hex[:10])
    tool: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    impact: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resultType": "input_required",
            "request_id": self.request_id,
            "tool": self.tool,
            "arguments": self.arguments,
            "impact": self.impact,
        }


def make_tool(
    name: str,
    description: str,
    input_schema: Dict[str, Any],
    handler: ToolHandler,
    permission: PermissionLevel = PermissionLevel.L0,
    impact: Optional[ImpactFn] = None,
    server: str = "",
) -> Tool:
    return Tool(
        name=name, description=description, input_schema=input_schema,
        handler=handler, permission=permission, impact=impact, server=server,
    )
