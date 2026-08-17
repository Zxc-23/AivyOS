"""启动上下文重建测试（§8.2 restore_on_boot 三重恢复）。"""

import asyncio
import unittest

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.workflow.checkpointer import SqliteCheckpointer
from aivyos_core.workflow.workflows import build_vibe_coding_graph

from tests import AivyTestCase, _TMP, make_config


class TestBootRecovery(AivyTestCase):
    def test_restore_three_sources(self):
        cfg = make_config()
        engine = ChatEngine(cfg)

        # 1) 长期记忆
        asyncio.run(engine.memory.add("用户喜欢咖啡"))
        # 2) MemFS 记忆
        engine.memfs.remember("用户偏好: 简洁回复", category="user_prefs.md")
        # 3) 工作流检查点
        ck = SqliteCheckpointer(engine.home / cfg["workflow"]["checkpoint_db"])
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
        asyncio.run(app.invoke({"user_request": "天气网页"}, thread_id="wf_boot"))

        summary = asyncio.run(engine.restore_on_boot())
        self.assertGreaterEqual(len(summary.long_term_memories), 1)
        self.assertTrue(summary.memfs_state.get("files"))
        self.assertIsNotNone(summary.workflow_checkpoint)
        self.assertEqual(summary.workflow_checkpoint["node"], "save_memory")
        self.assertIn("长期记忆", summary.summary_text)
        self.assertIn("MemFS", summary.summary_text)
        self.assertIn("工作流", summary.summary_text)

    def test_restore_with_empty_state(self):
        import os
        import uuid

        cfg = make_config()
        cfg["home"] = os.path.join(_TMP, "recovery_empty_" + uuid.uuid4().hex[:8])  # 隔离空数据目录
        engine = ChatEngine(cfg)
        summary = asyncio.run(engine.restore_on_boot())
        self.assertEqual(summary.long_term_memories, [])
        self.assertIsNone(summary.workflow_checkpoint)
        self.assertTrue(summary.summary_text)


if __name__ == "__main__":
    unittest.main()
