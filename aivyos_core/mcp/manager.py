"""ToolManager（文档 §5.1）：聚合各 Server 工具 + 权限分级门控（§19.2）。

- L0/L1：直接执行（L1 记录日志）
- L2/L3：返回 MRTRRequest 等待确认（§5.1.2）；auto_approve 可跳过（演示）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from aivyos_core.mcp.types import (
    MRTRRequest,
    PermissionLevel,
    Tool,
    ToolResult,
)

log = logging.getLogger(__name__)


class ToolManager:
    def __init__(self, auto_approve: bool = False, mrtr_ttl_s: float = 60.0) -> None:
        self.tools: dict[str, Tool] = {}
        self.auto_approve = auto_approve
        self.mrtr_ttl_s = mrtr_ttl_s
        self._pending: dict[str, MRTRRequest] = {}

    def add_server(self, server_tools) -> None:
        """注册一个 Server 的全部工具（server_tools.tools()）。"""
        for t in server_tools.tools():
            self.tools[t.name] = t

    def list_tools(self) -> List[Dict[str, Any]]:
        return [t.to_mcp_schema() for t in self.tools.values()]

    # ---- 调用（§5.1.2 MRTR 门控）----

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        approval: Optional[Dict[str, Any]] = None,
    ) -> Any:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(False, error=f"未知工具: {name}")
        if tool.permission in (PermissionLevel.L2, PermissionLevel.L3) and not self.auto_approve:
            if not approval:
                mrt = MRTRRequest(tool=name, arguments=arguments, impact=(tool.impact(arguments) if tool.impact else "执行该工具"))
                self._pending[mrt.request_id] = mrt
                return mrt
        return await tool.handler(arguments)

    async def confirm(self, request_id: str, approved: bool) -> Dict[str, Any]:
        mrt = self._pending.pop(request_id, None)
        if mrt is None:
            return {"ok": False, "error": f"未知或已过期的确认请求: {request_id}"}
        import time

        if time.time() - mrt.created_at > self.mrtr_ttl_s:
            return {"ok": False, "error": "确认已超时，请重试调用"}
        tool = self.tools.get(mrt.tool)
        if tool is None:
            return {"ok": False, "error": f"工具已注销: {mrt.tool}"}
        if not approved:
            log.warning("工具被拒绝（审计）: %s args=%s", mrt.tool, mrt.arguments)
            return {"ok": True, "result": ToolResult(False, error="用户拒绝执行").to_dict()}
        result = await tool.handler(mrt.arguments)
        if tool.permission == PermissionLevel.L3:
            log.warning("L3 危险操作执行（审计）: %s args=%s", mrt.tool, mrt.arguments)
        return {"ok": True, "result": result.to_dict()}

    def pending_requests(self) -> List[Dict[str, Any]]:
        return [mrt.to_dict() for mrt in self._pending.values()]
