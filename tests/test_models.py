"""模型管理后端测试（§12.2：models.* IPC，本地/云端分组与连通性测试）。"""

import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch

from tests import AivyTestCase, make_config


class TestModelsIPC(AivyTestCase):
    def _build_server(self):
        from aivyos_core.chat.engine import ChatEngine
        from aivyos_core.server_entry import build_server

        cfg = make_config()
        cfg["ipc"]["port"] = 0
        engine = ChatEngine(cfg)
        server = build_server(engine, cfg)
        return server, engine

    def test_test_connection_ok(self):
        """test-connection：/models 返回 200 + 模型列表 → ok。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        fake_resp = MagicMock()
        fake_resp.read.return_value = b'{"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}'
        fake_cm = MagicMock()
        fake_cm.__enter__.return_value = fake_resp
        with patch("urllib.request.urlopen", return_value=fake_cm):
            result = asyncio.run(handlers["models.test-connection"]({
                "provider": "openai",
                "api_key": "sk-test",
                "base_url": "https://api.openai.com/v1",
            }))
        self.assertTrue(result["ok"])
        self.assertEqual(result["model_count"], 2)

    def test_test_connection_http_error(self):
        """test-connection：401 → 返回 HTTP 错误信息。"""
        import urllib.error

        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        fake_resp = MagicMock()
        fake_resp.read.return_value = b'{"error": "invalid key"}'
        fake_resp.code = 401
        fake_cm = MagicMock()
        fake_cm.__enter__.side_effect = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, fake_resp
        )
        with patch("urllib.request.urlopen", return_value=fake_cm):
            result = asyncio.run(handlers["models.test-connection"]({
                "provider": "openai",
                "api_key": "sk-bad",
                "base_url": "https://api.openai.com/v1",
            }))
        self.assertFalse(result["ok"])
        self.assertIn("HTTP 401", result["error"])

    def test_test_cloud_skips_local_and_unconfigured(self):
        """test-cloud：本地提供商跳过；未配置 key 的云端标为未配置。"""
        from aivyos_core.api_key_store import ApiKeyStore

        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        # 清空环境变量中的云端 key（保证未配置分支可测）
        for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY"):
            os.environ.pop(var, None)
        with patch.object(ApiKeyStore, "list_keys", return_value={}):
            result = asyncio.run(handlers["models.test-cloud"]({}))
        self.assertTrue(result["ok"])
        # 每个结果必须是云端（非 local）
        for r in result["results"]:
            self.assertNotEqual(r["provider"], "ollama")
            self.assertNotEqual(r["provider"], "vllm")
        # 未配置 → ok=False
        self.assertGreaterEqual(result["total"], 1)
        unconfigured = [r for r in result["results"] if not r["ok"]]
        self.assertGreaterEqual(len(unconfigured), 1)
        self.assertTrue(any("未配置" in r["error"] for r in unconfigured))

    def test_test_cloud_reports_success(self):
        """test-cloud：已配置 key + 可用端点 → ok=True 且带模型数。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek-test"

        fake_resp = MagicMock()
        fake_resp.read.return_value = b'{"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]}'
        fake_cm = MagicMock()
        fake_cm.__enter__.return_value = fake_resp

        # 对 deepseek 的端点返回成功，其余请求抛连接失败
        def fake_urlopen(req, timeout=8):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "api.deepseek.com" in url:
                return fake_cm
            raise OSError("connection refused")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = asyncio.run(handlers["models.test-cloud"]({}))
        deepseek = next((r for r in result["results"] if r["provider"] == "deepseek"), None)
        self.assertIsNotNone(deepseek)
        self.assertTrue(deepseek["ok"])
        self.assertEqual(deepseek["model_count"], 2)
        self.assertIn("deepseek-chat", deepseek["models"])

        os.environ.pop("DEEPSEEK_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
