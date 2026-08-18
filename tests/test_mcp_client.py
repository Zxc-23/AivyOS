"""MCP 客户端-服务器 TCP 集成测试 + 记忆工具测试。"""

import asyncio
import os
import shutil
import socket
import unittest

from aivyos_core.mcp.client import McpClient
from aivyos_core.mcp.server import McpServer
from aivyos_core.mcp.types import ToolResult, make_tool
from aivyos_core.chat.engine import ChatEngine
from aivyos_core.mcp.servers.memory import MemoryServer

from tests import AivyTestCase, _TMP, make_config


async def _echo(args):
    return ToolResult(True, content=f"echo:{args.get('text', '')}")


async def _danger(args):
    return ToolResult(True, content="done")


class TestMcpClientServer(AivyTestCase):
    def test_tcp_roundtrip_with_mrtr(self):
        async def scenario():
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]

            server = McpServer({
                "echo": make_tool("echo", "回显", {"type": "object"}, _echo),
                "danger": make_tool("danger", "危险", {"type": "object"}, _danger,
                                    permission="L2", impact=lambda a: "执行危险命令"),
            })
            tcp = await server.serve_tcp(port=port)
            client = McpClient(port=port)
            try:
                await client.connect()
                self.assertTrue(await client.ping())
                tools = await client.list_tools()
                self.assertEqual(len(tools), 2)

                # L0 直接调用
                r1 = await client.call_tool("echo", {"text": "hi"})
                self.assertEqual(r1["content"], "echo:hi")

                # L2 → MRTR → 客户端确认回调
                r2 = await client.call_tool("danger", {}, confirm=lambda mrt: True)
                self.assertEqual(r2["content"], "done")

                # 确认回调拒绝
                r3 = await client.call_tool("danger", {}, confirm=lambda mrt: False)
                self.assertFalse(r3["ok"])
            finally:
                await client.close()
                tcp.close()
                await tcp.wait_closed()

        asyncio.run(scenario())


class TestMemoryServer(AivyTestCase):
    def test_memory_tools(self):
        cfg = make_config()
        cfg["home"] = os.path.join(_TMP, "mcp_mem")
        shutil.rmtree(cfg["home"], ignore_errors=True)
        engine = ChatEngine(cfg)
        srv = MemoryServer(engine.memory)
        tools = {t.name: t for t in srv.tools()}

        r = asyncio.run(tools["mem_add"].handler({"text": "用户喜欢咖啡"}))
        self.assertTrue(r.ok)
        r2 = asyncio.run(tools["mem_search"].handler({"query": "咖啡"}))
        self.assertTrue(any("咖啡" in h["text"] for h in r2.data["hits"]))


if __name__ == "__main__":
    unittest.main()
