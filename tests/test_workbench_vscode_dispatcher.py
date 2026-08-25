"""VS Code 分发器测试：CLI 缺失优雅降级、命令构建。"""

import asyncio
import unittest
from unittest import mock

from tests import AivyTestCase
from aivyos_core.workbench.dispatchers.vscode import VSCodeDispatcher


class TestVSCodeDispatcher(AivyTestCase):
    def test_missing_cli_graceful_error(self):
        """code 不在 PATH → ok=False + 中文提示，不抛异常。"""
        with mock.patch("shutil.which", return_value=None):
            disp = VSCodeDispatcher()
            self.assertFalse(disp.available())
            res = asyncio.run(disp.open("F:/some/path"))
        self.assertFalse(res.ok)
        self.assertIn("VS Code CLI 不可用", res.error)

    def test_command_built_as_list(self):
        """命令构建：使用参数列表，路径作为独立元素（Windows 空格路径安全）。"""
        captured: dict = {}

        async def _fake_run_cli(cmd, **kwargs):
            captured["cmd"] = cmd
            from aivyos_core.workbench.models import AgentResult

            return AgentResult(agent="vscode", ok=True, exit_code=0)

        with mock.patch("shutil.which", return_value="C:/Tools/code.cmd"), \
             mock.patch("aivyos_core.workbench.dispatchers.vscode.run_cli", _fake_run_cli):
            res = asyncio.run(VSCodeDispatcher().open("F:/My Dir/file.py"))
        self.assertTrue(res.ok)
        self.assertEqual(captured["cmd"], ["code", "F:/My Dir/file.py"])


if __name__ == "__main__":
    unittest.main()
