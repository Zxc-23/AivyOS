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

    def test_build_failure_retry_then_give_up(self):
        ck = _ckpt("ck_vibe_fail.db")
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
        state = asyncio.run(app.invoke({"user_request": "做一个天气网页失败"}, thread_id="wf_fail"))
        # 构建失败回环（上限 2 次）后 give_up 终止：不假成功、不无限循环
        self.assertTrue(state["build_failed"])
        self.assertEqual(state["retry_count"], 2)
        self.assertGreater(app.last_trace.count("generate"), 1)  # 回环触发
        self.assertNotIn("preview", app.last_trace)  # 未假成功进入预览

    def test_local_executor_writes_files_and_builds(self):
        import shutil

        ws = os.path.join(_TMP, "ws_local")
        shutil.rmtree(ws, ignore_errors=True)
        state = None
        try:
            ck = _ckpt("ck_local.db")
            app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
            ctx = {
                "executor": "local",
                "workspace": ws,
                "build_command": "python -c \"import sys; sys.exit(0)\"",
                "preview": True,
            }
            state = asyncio.run(app.invoke({"user_request": "做一个网页"}, thread_id="wf_local", ctx=ctx))
            # 真实文件写入
            for name in ("index.html", "style.css", "script.js"):
                self.assertTrue(os.path.exists(os.path.join(ws, name)), name)
            self.assertFalse(state["build_failed"])
            self.assertTrue(state["preview_ok"])
            self.assertIn("127.0.0.1", state["preview_url"])
            # 预览服务器真实可访问
            import urllib.request

            body = urllib.request.urlopen(state["preview_url"], timeout=5).read().decode()
            self.assertIn("<title>做一个网页</title>", body)
        finally:
            from aivyos_core.workflow.workflows import stop_preview_server

            if state is not None:
                stop_preview_server(state)
            shutil.rmtree(ws, ignore_errors=True)

    def test_local_executor_build_failure_gives_up(self):
        import shutil

        ws = os.path.join(_TMP, "ws_local_fail")
        shutil.rmtree(ws, ignore_errors=True)
        try:
            ck = _ckpt("ck_local_fail.db")
            app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
            ctx = {
                "executor": "local",
                "workspace": ws,
                "build_command": "python -c \"import sys; sys.exit(1)\"",
                "preview": True,
            }
            state = asyncio.run(app.invoke({"user_request": "项目X"}, thread_id="wf_local_fail", ctx=ctx))
            self.assertTrue(state["build_failed"])
            self.assertEqual(state["retry_count"], 2)
            self.assertTrue(state["errors"])
            self.assertNotIn("preview", app.last_trace)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

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

    def test_preview_console_error_retry_loop(self):
        """§11 预览验证回环：console 错误 → 回 generate 修复 → 超限 give_up（不假成功）。"""
        import shutil

        from aivyos_core.codegen import CodeGenService
        from aivyos_core.codegen.preview import PreviewController
        from aivyos_core.mcp.types import ToolResult
        from aivyos_core.workflow.workflows import stop_preview_server

        class _ErrorBrowser:
            """browser server：始终报告 console error（模拟预览发现问题）。"""

            async def _monitor(self, args):
                return ToolResult(True, data={"events": {"console": [{"type": "error", "text": "TypeError: x is not a function"}], "network": []}, "backend": "stub"})

            async def _screenshot(self, args):
                return ToolResult(True, data={"image": None, "backend": "stub"})

        ws = os.path.join(_TMP, "ws_preview_retry")
        shutil.rmtree(ws, ignore_errors=True)
        state = None
        try:
            ck = _ckpt("ck_preview_retry.db")
            app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
            ctx = {
                "executor": "local",
                "workspace": ws,
                "codegen": CodeGenService(),
                "preview_controller": PreviewController(browser_server=_ErrorBrowser()),
                "preview": True,
                "build_command": None,  # 跳过构建（先过 build）
            }
            state = asyncio.run(app.invoke({"user_request": "做一个静态网页"}, thread_id="wf_preview_retry", ctx=ctx))
            # 预览验证持续失败 → 回环 generate 至上限后 give_up 终止
            self.assertTrue(state["preview_failed"])
            self.assertEqual(state["retry_count"], 2)  # MAX_BUILD_RETRIES
            self.assertGreater(app.last_trace.count("generate"), 1)  # 回环触发
            self.assertNotIn("save_memory", app.last_trace)  # 未假成功
        finally:
            if state is not None:
                stop_preview_server(state)
            shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
