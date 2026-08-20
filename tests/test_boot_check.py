"""系统自检（boot.check）测试：结构完整性 + 真实性 + 不触发副作用。"""

import asyncio
import unittest
from unittest.mock import patch

from tests import AivyTestCase, make_config


class TestBootCheck(AivyTestCase):
    def _build_server(self):
        """构建一个最小 server_entry（闭包内 boot.check）。"""
        from aivyos_core.chat.engine import ChatEngine
        from aivyos_core.server_entry import build_server

        cfg = make_config()
        cfg["ipc"]["port"] = 0  # 随机端口（避免占用）
        engine = ChatEngine(cfg)
        server = build_server(engine, cfg)
        return server, engine

    def test_boot_check_structure(self):
        """结构：checks 列表 + progress/passed/total/summary。"""
        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        self.assertIn("boot.check", handlers)
        result = asyncio.run(handlers["boot.check"]({}))
        self.assertEqual(result["total"], len(result["checks"]))
        self.assertEqual(result["passed"], sum(1 for c in result["checks"] if c["ok"]))
        self.assertEqual(result["progress"], int(result["passed"] / max(1, result["total"]) * 100))
        self.assertGreaterEqual(result["total"], 10)  # 至少 10 项
        for c in result["checks"]:
            self.assertIn("name", c)
            self.assertIn("ok", c)
            self.assertIn("detail", c)
            self.assertIsInstance(c["ok"], bool)

    def test_boot_check_does_not_create_voice_session(self):
        """自检不应触发 VoiceSession 创建（避免打开麦克风副作用）。"""
        from unittest.mock import patch

        server, _ = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        # patch VoiceSession 导入源：若自检触发创建则会调用；不调用即未创建
        with patch("aivyos_core.voice.session.VoiceSession") as mock_vs:
            asyncio.run(handlers["boot.check"]({}))
            mock_vs.assert_not_called()

    def test_boot_check_memory_search(self):
        """记忆检查做真实检索（不再仅读 backend_name）。"""
        from unittest.mock import AsyncMock

        server, engine = self._build_server()
        handlers = {m: h for m, h in server._handlers.items()}
        mock_search = AsyncMock(return_value=[])
        with patch.object(engine.memory, "search", mock_search):
            result = asyncio.run(handlers["boot.check"]({}))
            memory_check = next(c for c in result["checks"] if c["name"] == "记忆系统")
            self.assertTrue(mock_search.called)  # 真实检索被调用
            self.assertTrue(memory_check["ok"])


if __name__ == "__main__":
    unittest.main()
