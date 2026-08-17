"""跨重启连续性测试（§8 记忆连续性：重启后记忆/会话/MemFS 存活）。"""

import asyncio
import unittest

from aivyos_core.chat.engine import ChatEngine

from tests import AivyTestCase, make_config


class TestCrossRestart(AivyTestCase):
    def test_memory_and_memfs_survive_restart(self):
        cfg = make_config()
        home = cfg["home"]

        # 第一次"运行"：写入记忆 + MemFS 事实
        engine1 = ChatEngine(cfg)
        reply1 = asyncio.run(engine1.send("记住我叫小明，喜欢咖啡"))
        engine1.memfs.remember("用户项目: 天气应用", category="tasks.md")

        # 模拟重启：全新引擎实例，同一数据目录
        cfg2 = make_config()
        cfg2["home"] = home
        engine2 = ChatEngine(cfg2)

        # 长期记忆检索命中
        hits = asyncio.run(engine2.memory.search("小明", top_k=5))
        self.assertTrue(any("小明" in h.text for h in hits))

        # MemFS 存活
        self.assertIn("小明", engine2.memfs.read("facts.md"))
        self.assertIn("天气应用", engine2.memfs.read("tasks.md"))

        # 会话文件存活（可恢复历史）
        sessions = engine2.list_sessions()
        self.assertTrue(any(s["session_id"] == reply1.session_id for s in sessions))
        restored = engine2.load_session(reply1.session_id)
        self.assertGreaterEqual(len(restored.messages), 2)

    def test_workflow_checkpoint_survives_restart(self):
        cfg = make_config()
        engine = ChatEngine(cfg)
        from aivyos_core.workflow.checkpointer import SqliteCheckpointer
        from aivyos_core.workflow.workflows import build_vibe_coding_graph

        ck = SqliteCheckpointer(engine.home / cfg["workflow"]["checkpoint_db"])
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
        asyncio.run(app.invoke({"user_request": "重启测试项目"}, thread_id="wf_restart"))

        # 重启后可从检查点续传
        ck2 = SqliteCheckpointer(engine.home / cfg["workflow"]["checkpoint_db"])
        app2 = build_vibe_coding_graph(ck2).compile(checkpointer=ck2)
        out = asyncio.run(app2.resume("wf_restart", ctx={}))
        self.assertTrue(out["preview_ok"])


if __name__ == "__main__":
    unittest.main()
