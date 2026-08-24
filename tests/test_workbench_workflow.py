"""workbench 工作流节点与图测试（§4.2.1）：节点行为、条件边、checkpoint 续传。"""

import asyncio
import os
import unittest
from unittest import mock

from tests import AivyTestCase, _TMP
from aivyos_core.workflow.checkpointer import SqliteCheckpointer
from aivyos_core.workflow.mini_graph import WorkflowError
from aivyos_core.workflow.nodes import (
    build_diff_review_graph,
    build_workbench_graph,
    claude_node,
    codex_node,
    diff_capture_node,
    vscode_open_node,
)
from aivyos_core.workbench.models import AgentResult


def _svc(claude=None, codex=None, vscode=None):
    svc = mock.Mock()
    svc.run_claude = mock.AsyncMock(return_value=claude or AgentResult(agent="claude", ok=True, output="实现完成"))
    svc.run_codex = mock.AsyncMock(return_value=codex or AgentResult(agent="codex", ok=True, output="审查通过"))
    svc.open_vscode = mock.AsyncMock(return_value=vscode if vscode is not None else AgentResult(agent="vscode", ok=True))
    return svc


class TestNodes(AivyTestCase):
    def test_claude_node_ok_prepares_review_prompt(self):
        """claude 成功：输出落 state，且为 codex 组装审查 prompt。"""
        state = {"user_request": "写代码", "cwd": ""}
        out = asyncio.run(claude_node(state, {"workbench": _svc()}))
        self.assertTrue(out["claude_ok"])
        self.assertEqual(out["claude_output"], "实现完成")
        self.assertIn("实现完成", out["codex_prompt"])

    def test_claude_node_missing_service(self):
        """ctx 无 workbench → 记录错误不抛异常。"""
        out = asyncio.run(claude_node({"user_request": "x"}, {}))
        self.assertFalse(out["claude_ok"])
        self.assertIn("workbench", out["claude_error"])

    def test_codex_node_uses_codex_prompt(self):
        """codex 优先用 codex_prompt，缺省回退 user_request。"""
        svc = _svc()
        asyncio.run(codex_node({"codex_prompt": "审查这个", "user_request": "原始"}, {"workbench": svc}))
        self.assertEqual(svc.run_codex.call_args.args[0], "审查这个")
        svc2 = _svc()
        asyncio.run(codex_node({"codex_prompt": "", "user_request": "原始"}, {"workbench": svc2}))
        self.assertEqual(svc2.run_codex.call_args.args[0], "原始")

    def test_diff_capture_node(self):
        """diff 捕获成功 → diff_text 落 state 且组装 codex 审查 prompt。"""
        with mock.patch("aivyos_core.workbench.diff.run_cli", mock.AsyncMock(
                return_value=AgentResult(agent="git", ok=True, output="diff --git a/x.py"))):
            out = asyncio.run(diff_capture_node({"cwd": "/repo"}, {}))
        self.assertTrue(out["diff_ok"])
        self.assertIn("diff --git", out["codex_prompt"])

    def test_vscode_node_skips_without_path(self):
        """无 vscode_path → 跳过并说明，不视为流程失败。"""
        out = asyncio.run(vscode_open_node({"vscode_path": ""}, {"workbench": _svc()}))
        self.assertFalse(out["vscode_ok"])
        self.assertIn("跳过", out["vscode_error"])


class TestGraphs(AivyTestCase):
    def test_workbench_graph_full_trace(self):
        """串行图全链路：claude → codex_review → open_vscode。"""
        graph = build_workbench_graph()
        state = asyncio.run(graph.invoke(
            {"user_request": "写天气网页", "vscode_path": "F:/out"},
            thread_id="t1", ctx={"workbench": _svc()},
        ))
        self.assertEqual(graph.last_trace, ["claude", "codex_review", "open_vscode"])
        self.assertTrue(state["claude_ok"] and state["codex_ok"] and state["vscode_ok"])

    def test_workbench_graph_claude_fail_short_circuits(self):
        """claude 失败 → 直接 END，不执行后续节点。"""
        svc = _svc(claude=AgentResult(agent="claude", ok=False, error="超时"))
        graph = build_workbench_graph()
        state = asyncio.run(graph.invoke({"user_request": "x"}, ctx={"workbench": svc}))
        self.assertEqual(graph.last_trace, ["claude"])
        self.assertFalse(state["codex_ok"])
        svc.run_codex.assert_not_awaited()

    def test_checkpoint_resume_after_codex_failure(self):
        """codex 节点抛异常 → invoke 失败；修复后 resume 从 codex 续跑（不重跑 claude）。"""
        ckpt_path = os.path.join(_TMP, "wb-ckpt.sqlite")
        ckpt = SqliteCheckpointer(ckpt_path)
        good = AgentResult(agent="codex", ok=True, output="审查通过")
        failing_svc = _svc()
        failing_svc.run_codex = mock.AsyncMock(side_effect=RuntimeError("codex 崩溃"))
        graph = build_workbench_graph(checkpointer=ckpt)
        with self.assertRaises(RuntimeError):
            asyncio.run(graph.invoke({"user_request": "x"}, thread_id="tt", ctx={"workbench": failing_svc}))
        # claude 已成功 → checkpoint 在 claude 节点
        node, _ = ckpt.latest("tt")
        self.assertEqual(node, "claude")
        # 修复 codex 后续传：claude 不应被重跑
        fixed_svc = _svc()
        state = asyncio.run(graph.resume("tt", ctx={"workbench": fixed_svc}))
        fixed_svc.run_claude.assert_not_awaited()
        fixed_svc.run_codex.assert_awaited_once()
        self.assertEqual(graph.last_trace, ["codex_review", "open_vscode"])
        ckpt.close()

    def test_diff_review_graph(self):
        """diff 审查图：capture → codex_review；无改动时短路。"""
        graph = build_diff_review_graph()
        with mock.patch("aivyos_core.workbench.diff.run_cli", mock.AsyncMock(
                return_value=AgentResult(agent="git", ok=True, output="diff --git a/x.py"))):
            state = asyncio.run(graph.invoke({"cwd": "/repo"}, ctx={"workbench": _svc()}))
        self.assertEqual(graph.last_trace, ["diff_capture", "codex_review"])
        self.assertTrue(state["codex_ok"])


if __name__ == "__main__":
    unittest.main()
