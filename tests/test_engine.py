"""对话引擎端到端测试（mock 模式，文档 §4.1-§4.4）。"""

import asyncio
import os
import unittest

from aivyos_core.chat.engine import ChatEngine

from tests import AivyTestCase, make_config


class TestChatEngine(AivyTestCase):
    def setUp(self):
        self.cfg = make_config()
        self.engine = ChatEngine(self.cfg)

    def test_send_returns_reply_and_persists(self):
        reply = asyncio.run(self.engine.send("你好"))
        self.assertIn("mock", reply.text)
        self.assertTrue(reply.session_id.startswith("sess_"))
        self.assertEqual(reply.route.mode.value, "mock")
        # 会话已持久化
        path = self.engine._session_path(reply.session_id)
        self.assertTrue(path.exists())
        sessions = self.engine.list_sessions()
        self.assertTrue(any(s["session_id"] == reply.session_id for s in sessions))

    def test_auto_memory_extract(self):
        reply = asyncio.run(self.engine.send("记住我叫小明"))
        hits = asyncio.run(self.engine.memory.search("小明", top_k=5))
        self.assertTrue(hits, "应自动抽取'记住'类事实")
        self.assertIn("小明", hits[0].text)

    def test_session_continuity(self):
        sid = asyncio.run(self.engine.send("你好")) .session_id
        asyncio.run(self.engine.send("今天天气如何", session_id=sid))
        state = self.engine.load_session(sid)
        self.assertEqual(len(state.messages), 4)  # 2 轮 × 2 条

    def test_reset_session(self):
        sid = asyncio.run(self.engine.send("你好")).session_id
        self.engine.reset_session(sid)
        self.assertFalse(self.engine._session_path(sid).exists())

    def test_persona_update(self):
        self.assertTrue(self.engine.set_persona("tone", "witty"))
        self.assertEqual(self.engine.persona.tone, "witty")
        self.assertFalse(self.engine.set_persona("tone", "bad"))

    def test_snapshot_roundtrip(self):
        sid = asyncio.run(self.engine.send("你好")).session_id
        snap = self.engine.load_session(sid).snapshot()
        from aivyos_core.models import SessionState

        restored = SessionState.from_snapshot(snap)
        self.assertEqual(restored.session_id, sid)
        self.assertEqual(len(restored.messages), 2)

    def test_status(self):
        st = self.engine.status()
        self.assertIn("backend", st)
        self.assertEqual(st["backend"], "simple-jsonl")  # 未装 mem0 → simple


if __name__ == "__main__":
    unittest.main()
