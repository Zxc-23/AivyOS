"""自动预览控制器测试（§11 / T5.5、T5.9）：分类型 dev server + 生命周期管理 + AI 视觉验证 + 多设备视口。"""

import asyncio
import os
import shutil
import unittest

from aivyos_core.codegen.preview import VIEWPORTS, PreviewController

from tests import _TMP, AivyTestCase


class TestPreviewController(AivyTestCase):
    def setUp(self):
        self.ws = os.path.join(_TMP, "pv_ws")
        shutil.rmtree(self.ws, ignore_errors=True)
        os.makedirs(self.ws)
        with open(os.path.join(self.ws, "index.html"), "w", encoding="utf-8") as f:
            f.write("<!doctype html><html><head><title>预览</title></head><body>hello</body></html>")

    def test_static_server_serves_files(self):
        ctl = PreviewController()
        url = ctl.start(self.ws, "static-site")
        self.assertIn("127.0.0.1", url)
        try:
            import urllib.request

            body = urllib.request.urlopen(url, timeout=5).read().decode()
            self.assertIn("hello", body)
        finally:
            ctl.stop()
        self.assertEqual(ctl.server_status()["active"], 0)

    def test_list_servers(self):
        ctl = PreviewController()
        ctl.start(self.ws, "static-site")
        servers = ctl.list_servers()
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]["type"], "static-site")
        self.assertIn("http://127.0.0.1:", servers[0]["url"])
        ctl.stop()
        self.assertEqual(len(ctl.list_servers()), 0)

    def test_screenshot_mock_fallback(self):
        ctl = PreviewController()
        r = asyncio.run(ctl.capture_viewport("http://127.0.0.1:1/", "desktop"))
        self.assertEqual(r["backend"], "mock")  # 未装 playwright → 明确回退，不伪装
        self.assertEqual(r["device"], "desktop")

    def test_viewports_defined(self):
        self.assertIn("desktop", VIEWPORTS)
        self.assertIn("mobile", VIEWPORTS)
        self.assertIn("tablet", VIEWPORTS)

    def test_restart_same_workspace_reuses_url(self):
        ctl = PreviewController()
        url1 = ctl.start(self.ws, "static-site")
        url2 = ctl.start(self.ws, "static-site")  # 已启动 → 复用
        self.assertEqual(url1, url2)
        ctl.stop()
        self.assertEqual(ctl.server_status()["active"], 0)

    def test_visual_check_without_browser_server(self):
        # 无 browser server → no-screenshot（诚实失败，不伪造）
        ctl = PreviewController()
        r = asyncio.run(ctl.visual_check("http://127.0.0.1:1/"))
        self.assertEqual(r["verdict"], "no-screenshot")

    def test_visual_check_with_mock_understand(self):
        # browser server 返回真实截图（1x1 PNG）+ understand mock → not-verified（honest，不伪造判定）
        import base64

        from aivyos_core.mcp.types import ToolResult
        from aivyos_core.vision.understand import MockUnderstand

        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

        class _StubBrowser:
            async def _screenshot(self, args):
                return ToolResult(True, data={"image": png_b64, "backend": "stub"})

        ctl = PreviewController(browser_server=_StubBrowser(), understand=MockUnderstand())
        url = ctl.start(self.ws, "static-site")
        try:
            r = asyncio.run(ctl.visual_check(url))
            self.assertEqual(r["verdict"], "not-verified")
            self.assertEqual(r["backend"], "stub")
        finally:
            ctl.stop()


if __name__ == "__main__":
    unittest.main()
