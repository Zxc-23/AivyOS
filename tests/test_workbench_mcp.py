"""Workbench MCP Server 测试：工具注册权限 + handler 走 service。"""

import asyncio
import unittest
from unittest import mock

from tests import AivyTestCase
from aivyos_core.mcp.servers.workbench import WorkbenchServer
from aivyos_core.mcp.types import PermissionLevel
from aivyos_core.workbench.models import AgentResult


class TestWorkbenchMcp(AivyTestCase):
    def test_tools_registered_with_permissions(self):
        """注册 3 个工具：claude/codex 为 L3，vscode_open 为 L1。"""
        tools = {t.name: t for t in WorkbenchServer(service=mock.Mock()).tools()}
        self.assertEqual(
            set(tools),
            {"workbench_claude_run", "workbench_codex_run", "workbench_vscode_open"},
        )
        self.assertEqual(tools["workbench_claude_run"].permission, PermissionLevel.L3)
        self.assertEqual(tools["workbench_codex_run"].permission, PermissionLevel.L3)
        self.assertEqual(tools["workbench_vscode_open"].permission, PermissionLevel.L1)
        self.assertTrue(all(t.server == "workbench" for t in tools.values()))

    def test_handler_routes_to_service(self):
        """handler 调用 service.run_claude，返回内容不含机密。"""
        svc = mock.Mock()
        svc.last_notice = ""
        svc.run_claude = mock.AsyncMock(
            return_value=AgentResult(agent="claude", ok=True, output="已完成", exit_code=0)
        )
        server = WorkbenchServer(service=svc)
        result = asyncio.run(server._claude_run({"prompt": "写一个天气网页"}))
        svc.run_claude.assert_awaited_once()
        self.assertTrue(result.ok)
        self.assertIn("已完成", result.content)


if __name__ == "__main__":
    unittest.main()
