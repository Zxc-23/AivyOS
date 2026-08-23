"""Diff 捕获与审查测试。"""

import asyncio
import unittest
from unittest import mock

from tests import AivyTestCase
from aivyos_core.workbench.diff import build_review_prompt, capture_diff
from aivyos_core.workbench.models import AgentResult
from aivyos_core.workbench.service import WorkbenchService
from tests import make_config


def _res(ok, output="", error=""):
    return AgentResult(agent="git", ok=ok, output=output, error=error, exit_code=0 if ok else 1)


class TestDiffCapture(AivyTestCase):
    def test_capture_diff_ok(self):
        """git diff HEAD 有输出 → ok，内容透传。"""
        with mock.patch("aivyos_core.workbench.diff.run_cli",
                        mock.AsyncMock(return_value=_res(ok=True, output="diff --git a/x.py ..."))) as m:
            r = asyncio.run(capture_diff("F:/repo"))
        self.assertTrue(r.ok)
        self.assertIn("diff --git", r.output)
        self.assertEqual(m.call_args.kwargs.get("cwd") or m.call_args.args[1], "F:/repo")

    def test_capture_diff_empty(self):
        """无改动 → ok=False 且提示为空。"""
        with mock.patch("aivyos_core.workbench.diff.run_cli",
                        mock.AsyncMock(return_value=_res(ok=True, output="  \n"))):
            r = asyncio.run(capture_diff("."))
        self.assertFalse(r.ok)
        self.assertIn("没有改动", r.error)

    def test_capture_diff_not_a_repo(self):
        """git 失败 → 诚实报错。"""
        with mock.patch("aivyos_core.workbench.diff.run_cli",
                        mock.AsyncMock(return_value=_res(ok=False, error="exit 128"))):
            r = asyncio.run(capture_diff("C:/not-repo"))
        self.assertFalse(r.ok)
        self.assertIn("git diff 失败", r.error)

    def test_review_diff_sends_to_codex(self):
        """service.review_diff：diff 进入 codex 审查 prompt。"""
        svc = WorkbenchService(make_config())
        svc.run_codex = mock.AsyncMock(return_value=AgentResult(agent="codex", ok=True, output="审查结论"))
        with mock.patch("aivyos_core.workbench.diff.run_cli",
                        mock.AsyncMock(return_value=_res(ok=True, output="diff --git a/x.py +1行"))):
            r = asyncio.run(svc.review_diff("."))
        self.assertTrue(r.ok)
        self.assertIn("diff --git a/x.py +1行", svc.run_codex.call_args.args[0])

    def test_review_diff_no_changes(self):
        """无改动时 review_diff 直接报错，不调 codex。"""
        svc = WorkbenchService(make_config())
        svc.run_codex = mock.AsyncMock()
        with mock.patch("aivyos_core.workbench.diff.run_cli",
                        mock.AsyncMock(return_value=_res(ok=True, output=""))):
            r = asyncio.run(svc.review_diff("."))
        self.assertFalse(r.ok)
        svc.run_codex.assert_not_awaited()

    def test_review_prompt_truncates(self):
        """超长 diff 截断到 _DIFF_MAX。"""
        from aivyos_core.workbench.diff import _DIFF_MAX

        prompt = build_review_prompt("x" * (_DIFF_MAX * 3))
        self.assertLessEqual(len(prompt), _DIFF_MAX + 200)


if __name__ == "__main__":
    unittest.main()
