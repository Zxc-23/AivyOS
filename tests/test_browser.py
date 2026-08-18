"""浏览器 MCP Server 测试（§11 / T5.8 控制台/网络监控、T5.9 多设备视口）。"""

import asyncio
import unittest

from aivyos_core.mcp.servers.browser import BrowserServer

from tests import AivyTestCase


class TestBrowserServer(AivyTestCase):
    def setUp(self):
        self.srv = BrowserServer()
        self.tools = {t.name: t for t in self.srv.tools()}

    def test_tool_names_registered(self):
        for name in ("browser_navigate", "browser_screenshot", "browser_monitor", "browser_viewport"):
            self.assertIn(name, self.tools, name)

    def test_navigate_mock_fallback(self):
        r = asyncio.run(self.tools["browser_navigate"].handler({"url": "http://127.0.0.1:1/"}))
        self.assertTrue(r.ok)
        self.assertEqual(r.data["backend"], "mock")

    def test_navigate_rejects_bad_url(self):
        r = asyncio.run(self.tools["browser_navigate"].handler({"url": "not a url"}))
        self.assertFalse(r.ok)
        self.assertIn("URL", r.error)

    def test_monitor_returns_events(self):
        r = asyncio.run(self.tools["browser_monitor"].handler({"url": "http://127.0.0.1:1/"}))
        self.assertTrue(r.ok)
        self.assertIn("console", r.data["events"])
        self.assertIn("network", r.data["events"])
        self.assertEqual(r.data["backend"], "mock")

    def test_viewport_returns_device(self):
        r = asyncio.run(self.tools["browser_viewport"].handler({"url": "http://127.0.0.1:1/", "device": "mobile"}))
        self.assertTrue(r.ok)
        self.assertEqual(r.data["device"], "mobile")
        self.assertEqual(r.data["viewport"], (390, 844))

    def test_viewport_unknown_device_rejected(self):
        r = asyncio.run(self.tools["browser_viewport"].handler({"url": "http://127.0.0.1:1/", "device": "watch"}))
        self.assertFalse(r.ok)
        self.assertIn("未知设备", r.error)


if __name__ == "__main__":
    unittest.main()
