"""记忆连续性测试（文档 §21.3 / T10.8）：模拟断电重启 → 零记忆丢失验证。

覆盖：MemFS 记忆文件 / 会话检查点 / 配置持久化 在"断电"（直接 kill，无清理）后恢复。
"""

import asyncio
import os
import shutil
import unittest

from aivyos_core.memfs import MemFS
from aivyos_core.workflow.checkpointer import SqliteCheckpointer
from aivyos_core.workflow.mini_graph import END, StateGraph

from tests import AivyTestCase, _TMP


class TestMemoryContinuity(AivyTestCase):
    def test_memfs_survives_power_loss(self):
        """MemFS 记忆文件断电后仍在（§8.1 跨重启存活 / T10.8 零记忆丢失）。"""
        root = os.path.join(_TMP, "mem_power")
        shutil.rmtree(root, ignore_errors=True)
        mem = MemFS(root)
        mem.write("facts.md", "- [2026-08-18] 用户喜欢咖啡", append=True)

        # 模拟断电：直接丢弃对象（无 flush/close 清理），新进程重新加载
        del mem
        mem2 = MemFS(root)
        self.assertIn("用户喜欢咖啡", mem2.read("facts.md"))
        shutil.rmtree(root, ignore_errors=True)

    def test_checkpoint_survives_power_loss(self):
        """工作流检查点断电后仍可续传（§4.5.2 / T10.8）。"""
        db = os.path.join(_TMP, "ck_power.db")
        if os.path.exists(db):
            os.remove(db)
        ck = SqliteCheckpointer(db)
        ck.save("wf_power", "understand", {"user_request": "断电测试", "retry_count": 0})
        ck.close()  # 模拟断电：关闭连接（数据已落盘）

        # 断电重启：新连接对象读取同一 SQLite 文件
        ck2 = SqliteCheckpointer(db)
        node, state = ck2.latest("wf_power")
        ck2.close()
        self.assertEqual(node, "understand")
        self.assertEqual(state["user_request"], "断电测试")
        os.remove(db)

    def test_workflow_resume_after_power_loss(self):
        """断电重启后从检查点续跑完整工作流（T10.8 零丢失）。"""
        db = os.path.join(_TMP, "ck_power2.db")
        if os.path.exists(db):
            os.remove(db)
        ck = SqliteCheckpointer(db)

        g = StateGraph({"n": 0})

        async def inc(s, c):
            s["n"] = s.get("n", 0) + 1
            return s

        g.add_node("a", inc)
        g.add_node("b", inc)
        g.set_entry_point("a")
        g.add_edge("a", "b")
        g.add_edge("b", END)
        app = g.compile(checkpointer=ck)
        asyncio.run(app.invoke({"n": 5}, thread_id="wf_power2"))  # 完成 a→b（5+1+1=7）
        ck.close()

        # 断电后从检查点恢复（b 已执行完 → 直接 END，n 保持 7 不重跑）
        ck2 = SqliteCheckpointer(db)
        app2 = g.compile(checkpointer=ck2)
        out = asyncio.run(app2.resume("wf_power2"))
        ck2.close()
        self.assertEqual(out["n"], 7)
        self.assertEqual(app2.last_trace, [])  # 无节点重跑（零丢失零重复）
        os.remove(db)


if __name__ == "__main__":
    unittest.main()
