"""工作流引擎测试（§4.5：状态图 / 条件边 / 检查点 / 断点续传）。"""

import asyncio
import os
import unittest

from aivyos_core.workflow.checkpointer import SqliteCheckpointer
from aivyos_core.workflow.mini_graph import END, StateGraph, WorkflowError
from aivyos_core.workflow.workflows import build_vibe_coding_graph

from tests import _TMP, AivyTestCase


def _ckpt(name: str) -> SqliteCheckpointer:
    return SqliteCheckpointer(os.path.join(_TMP, name))


class TestMiniGraph(AivyTestCase):
    def test_linear_graph(self):
        async def n1(s, c):
            s["v"] = s.get("v", 0) + 1
            return s

        g = StateGraph({"v": 0})
        g.add_node("a", n1)
        g.add_node("b", n1)
        g.set_entry_point("a")
        g.add_edge("a", "b")
        g.add_edge("b", END)
        app = g.compile()
        state = asyncio.run(app.invoke({}))
        self.assertEqual(state["v"], 2)
        self.assertEqual(app.last_trace, ["a", "b"])

    def test_conditional_loop(self):
        calls = {"n": 0}

        async def dec(s, c):
            s["count"] = s.get("count", 0) + 1
            return s

        def cond(s):
            return "again" if s["count"] < 3 else "done"

        g = StateGraph({"count": 0})
        g.add_node("w", dec)
        g.set_entry_point("w")
        g.add_conditional_edges("w", cond, {"again": "w", "done": END})
        app = g.compile()
        state = asyncio.run(app.invoke({}))
        self.assertEqual(state["count"], 3)
        self.assertEqual(len(app.last_trace), 3)

    def test_missing_entry(self):
        with self.assertRaises(WorkflowError):
            StateGraph().compile()

    def test_node_must_return_dict(self):
        async def bad(s, c):
            return "oops"

        g = StateGraph()
        g.add_node("x", bad)
        g.set_entry_point("x")
        g.add_edge("x", END)
        app = g.compile()
        with self.assertRaises(WorkflowError):
            asyncio.run(app.invoke({}))


class TestCheckpointer(AivyTestCase):
    def test_save_latest_clear(self):
        ck = _ckpt("ck_test.db")
        ck.save("t1", "a", {"x": 1})
        ck.save("t1", "b", {"x": 2})
        node, state = ck.latest("t1")
        self.assertEqual(node, "b")
        self.assertEqual(state, {"x": 2})
        self.assertEqual(len(ck.list_threads()), 1)
        ck.clear("t1")
        self.assertIsNone(ck.latest("t1"))


class TestVibeCodingWorkflow(AivyTestCase):
    def test_success_path(self):
        ck = _ckpt("ck_vibe.db")
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
        state = asyncio.run(app.invoke({"user_request": "做一个天气网页"}, thread_id="wf_test"))
        self.assertFalse(state["build_failed"])
        self.assertTrue(state["preview_ok"])
        self.assertIn("save_memory", app.last_trace)
        self.assertEqual(app.last_trace[0], "understand")

    def test_build_failure_retry_loop(self):
        ck = _ckpt("ck_vibe_fail.db")
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
        state = asyncio.run(app.invoke({"user_request": "做一个天气网页失败"}, thread_id="wf_fail"))
        # 构建失败回环（上限 2 次）后成功 → build_failed 最终为 False
        self.assertFalse(state["build_failed"])
        self.assertEqual(state["retry_count"], 2)
        self.assertGreater(app.last_trace.count("generate"), 1)  # 回环触发

    def test_resume_from_checkpoint(self):
        ck = _ckpt("ck_resume.db")
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)

        # 手动在 deliver 后写入检查点，模拟中断
        state = {"user_request": "项目X", "retry_count": 0, "spec": {"t": 1}, "plan": [], "files": {}}
        ck.save("wf_resume", "deliver", state)

        out = asyncio.run(app.resume("wf_resume", ctx={}))
        self.assertTrue(out["preview_ok"])
        self.assertIn("save_memory", app.last_trace)
        self.assertNotIn("understand", app.last_trace)  # 不重跑已完成的节点

    def test_resume_without_checkpoint_raises(self):
        ck = _ckpt("ck_empty.db")
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
        with self.assertRaises(WorkflowError):
            asyncio.run(app.resume("nope"))


if __name__ == "__main__":
    unittest.main()
