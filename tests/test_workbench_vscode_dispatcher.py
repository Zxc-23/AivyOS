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

    def test_command_built_with_quoted_path(self):
        """命令构建：code 与路径均加双引号（Windows 空格路径）。"""
        captured: dict = {}

        async def _fake_run_cli(cmd, **kwargs):
            captured["cmd"] = cmd
            from aivyos_core.workbench.models import AgentResult

            return AgentResult(agent="vscode", ok=True, exit_code=0)

        with mock.patch("shutil.which", return_value="C:/Tools/code.cmd"), \
             mock.patch("aivyos_core.workbench.dispatchers.vscode.run_cli", _fake_run_cli):
            res = asyncio.run(VSCodeDispatcher().open("F:/My Dir/file.py"))
        self.assertTrue(res.ok)
        self.assertIn('"F:/My Dir/file.py"', captured["cmd"])


if __name__ == "__main__":
    unittest.main()
