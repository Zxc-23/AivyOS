"""MCP 核心测试：协议分发、工具发现、MRTR 确认流（§5.1.2）。"""

import asyncio
import unittest

from aivyos_core.mcp.manager import ToolManager
from aivyos_core.mcp.server import McpServer
from aivyos_core.mcp.types import PermissionLevel, ToolResult, make_tool

from tests import AivyTestCase


def _tools() -> list:
    async def echo(args):
        return ToolResult(True, content=f"echo:{args.get('text', '')}")

    async def danger(args):
        return ToolResult(True, content="done")

    return [
        make_tool("echo", "回显", {"type": "object", "properties": {"text": {"type": "string"}}},
                  echo, PermissionLevel.L0),
        make_tool("danger", "危险操作", {"type": "object", "properties": {"cmd": {"type": "string"}}},
                  danger, PermissionLevel.L2, impact=lambda a: f"执行 {a.get('cmd', '')}"),
    ]


class TestMcpServer(AivyTestCase):
    def setUp(self):
        self.server = McpServer({t.name: t for t in _tools()})

    def test_ping(self):
        resp = asyncio.run(self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
        self.assertTrue(resp["result"]["pong"])

    def test_tools_list(self):
        resp = asyncio.run(self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
        names = [t["name"] for t in resp["result"]["tools"]]
        self.assertIn("echo", names)
        self.assertIn("danger", names)

    def test_l0_tool_direct(self):
        resp = asyncio.run(self.server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                               "params": {"name": "echo", "arguments": {"text": "hi"}}}))
        self.assertEqual(resp["result"]["content"], "echo:hi")

    def test_l2_tool_requires_mrtr(self):
        resp = asyncio.run(self.server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                               "params": {"name": "danger", "arguments": {"cmd": "rm -rf"}}}))
        result = resp["result"]
        self.assertEqual(result["resultType"], "input_required")
        self.assertIn("impact", result)
        rid = result["request_id"]

        # 拒绝
        denied = asyncio.run(self.server.handle({"jsonrpc": "2.0", "id": 5, "method": "mrtr/confirm",
                                                 "params": {"request_id": rid, "approved": False}}))
        self.assertTrue(denied["result"]["ok"])
        self.assertFalse(denied["result"]["result"]["ok"])

        # 再次调用 → 新请求 → 批准 → 执行
        resp2 = asyncio.run(self.server.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                                                "params": {"name": "danger", "arguments": {"cmd": "run"}}}))
        rid2 = resp2["result"]["request_id"]
        ok = asyncio.run(self.server.handle({"jsonrpc": "2.0", "id": 7, "method": "mrtr/confirm",
                                             "params": {"request_id": rid2, "approved": True}}))
        self.assertEqual(ok["result"]["result"]["content"], "done")

    def test_unknown_method(self):
        resp = asyncio.run(self.server.handle({"jsonrpc": "2.0", "id": 8, "method": "nope"}))
        self.assertEqual(resp["error"]["code"], -32601)

    def test_unknown_tool(self):
        resp = asyncio.run(self.server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                               "params": {"name": "x", "arguments": {}}}))
        self.assertFalse(resp["result"]["ok"])


class TestToolManager(AivyTestCase):
    def setUp(self):
        self.mgr = ToolManager()
        for t in _tools():
            self.mgr.tools[t.name] = t

    def test_aggregation_and_gate(self):
        self.assertEqual(len(self.mgr.list_tools()), 2)
        result = asyncio.run(self.mgr.call_tool("danger", {"cmd": "x"}))
        from aivyos_core.mcp.types import MRTRRequest

        self.assertIsInstance(result, MRTRRequest)
        out = asyncio.run(self.mgr.confirm(result.request_id, True))
        self.assertEqual(out["result"]["content"], "done")

    def test_auto_approve(self):
        mgr = ToolManager(auto_approve=True)
        for t in _tools():
            mgr.tools[t.name] = t
        result = asyncio.run(mgr.call_tool("danger", {"cmd": "x"}))
        self.assertEqual(result.content, "done")

    def test_l3_audit_log(self):
        async def rm(args):
            return ToolResult(True, content="deleted")

        self.mgr.tools["rm"] = make_tool("rm", "删", {"type": "object"}, rm, PermissionLevel.L3)
        req = asyncio.run(self.mgr.call_tool("rm", {}))
        from aivyos_core.mcp.types import MRTRRequest

        self.assertIsInstance(req, MRTRRequest)
        out = asyncio.run(self.mgr.confirm(req.request_id, True))
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
