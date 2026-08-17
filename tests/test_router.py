"""LLM 路由测试（文档 §4.1.3）。"""

import copy
import os
import unittest

from aivyos_core.config import DEFAULT_CONFIG
from aivyos_core.llm.router import ModelRouter
from aivyos_core.models import LLMRequest, RouteMode

from tests import AivyTestCase


def _router(mode: str = "auto", cloud_key: str | None = None) -> ModelRouter:
    cfg = copy.deepcopy(DEFAULT_CONFIG["llm"])
    cfg["mode"] = mode
    cfg["local"]["probe"] = False  # 路由测试确定性：关闭真实探测（乐观可用）
    if cloud_key:
        os.environ["AIVYOS_CLOUD_API_KEY"] = cloud_key
    else:
        os.environ.pop("AIVYOS_CLOUD_API_KEY", None)
    return ModelRouter(cfg)


class TestRouter(AivyTestCase):
    def tearDown(self):
        os.environ.pop("AIVYOS_CLOUD_API_KEY", None)

    def test_complexity_classification(self):
        r = _router()
        self.assertEqual(r.estimate_complexity("你好"), "simple_chat")
        self.assertEqual(r.estimate_complexity("帮我写个计算器程序"), "coding")
        self.assertEqual(r.estimate_complexity("分析一下这个方案的影响"), "complex_reasoning")
        self.assertEqual(r.estimate_complexity("看看这张截图"), "vision")

    def test_mock_mode(self):
        r = _router(mode="mock")
        d = r.route("随便什么")
        self.assertEqual(d.mode, RouteMode.MOCK)

    def test_auto_simple_goes_local(self):
        r = _router()
        d = r.route("你好")
        self.assertEqual(d.mode, RouteMode.LOCAL)
        self.assertFalse(d.fallback)  # 探测关闭 → 乐观本地可用

    def test_auto_complex_no_key_falls_back_local(self):
        r = _router()
        d = r.route("请分析一下这个架构方案的权衡")
        self.assertEqual(d.mode, RouteMode.LOCAL)
        self.assertTrue(d.fallback)  # 云端无密钥 → 降级本地

    def test_auto_complex_with_key_goes_cloud(self):
        r = _router(cloud_key="sk-test")
        d = r.route("请分析一下这个架构方案的权衡")
        self.assertEqual(d.mode, RouteMode.CLOUD)

    def test_complete_mock_roundtrip(self):
        import asyncio

        r = _router(mode="mock")
        d = r.route("你好")
        resp = asyncio.run(r.complete(LLMRequest(messages=[{"role": "user", "content": "你好"}], model="mock"), d))
        self.assertIn("Aivy", resp.text)

    def test_real_backend_failure_falls_back_to_mock(self):
        import asyncio

        # 本地指向不可达端口 → complete 应降级 mock 而非抛错
        cfg = dict(DEFAULT_CONFIG["llm"])
        cfg["mode"] = "local"
        cfg["local"]["base_url"] = "http://127.0.0.1:1/v1"  # 必然连接失败
        cfg["local"]["timeout_s"] = 2
        r = ModelRouter(cfg)
        d = r.route("你好")
        resp = asyncio.run(r.complete(LLMRequest(messages=[{"role": "user", "content": "你好"}], model="x"), d))
        self.assertIn("mock", resp.model)


class TestLocalProbe(AivyTestCase):
    """A4：本地可用性真实探测（GET /models + TTL 缓存，确定性测试）。"""

    def _cfg(self, base_url: str, timeout: float = 1.0) -> ModelRouter:
        cfg = copy.deepcopy(DEFAULT_CONFIG["llm"])
        cfg["local"]["base_url"] = base_url
        cfg["local"]["probe_timeout_s"] = timeout
        return ModelRouter(cfg)

    def test_probe_unreachable_false(self):
        r = self._cfg("http://127.0.0.1:1/v1")  # 必然拒绝/超时
        self.assertFalse(r._local_available())

    def test_probe_live_server_true(self):
        import json as _json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class ModelsHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = _json.dumps({"object": "list", "data": []}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), ModelsHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            r = self._cfg(f"http://127.0.0.1:{srv.server_address[1]}/v1")
            self.assertTrue(r._local_available())
            # TTL 缓存：服务停止后短时间内仍缓存 True
            srv.shutdown()
            self.assertTrue(r._local_available())
        finally:
            srv.server_close()

    def test_probe_disabled_optimistic(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG["llm"])
        cfg["local"]["probe"] = False
        r = ModelRouter(cfg)
        self.assertTrue(r._local_available())

    def test_env_disable_local(self):
        os.environ["AIVYOS_DISABLE_LOCAL"] = "1"
        try:
            r = self._cfg("http://127.0.0.1:11434/v1")
            self.assertFalse(r._local_available())
        finally:
            del os.environ["AIVYOS_DISABLE_LOCAL"]


if __name__ == "__main__":
    unittest.main()
