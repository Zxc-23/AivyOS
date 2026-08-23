"""Codex 分发器测试：OPENAI_* 注入、非零退出码。"""

import asyncio
import unittest
from unittest import mock

from tests import AivyTestCase
from aivyos_core.workbench.dispatchers.codex import CodexDispatcher
from aivyos_core.workbench.models import AgentTask, ProviderEnv
from tests.test_workbench_claude_dispatcher import _FakeProc, _fake_shell_factory


class TestCodexDispatcher(AivyTestCase):
    def test_env_injected(self):
        """OPENAI_API_KEY / OPENAI_BASE_URL 注入子进程 env，命令为 codex exec。"""
        recorder: dict = {}
        proc = _FakeProc(output=b"codex-out")
        penv = ProviderEnv(app_type="codex", name="Kimi",
                           env={"OPENAI_API_KEY": "ok-secret", "OPENAI_BASE_URL": "https://x/v1"})
        with mock.patch("asyncio.create_subprocess_shell", _fake_shell_factory(recorder, proc)):
            res = asyncio.run(CodexDispatcher().run(AgentTask(agent="codex", prompt="review"), penv))
        self.assertEqual(recorder["env"]["OPENAI_API_KEY"], "ok-secret")
        self.assertEqual(recorder["env"]["OPENAI_BASE_URL"], "https://x/v1")
        self.assertTrue(recorder["cmd"].startswith("codex exec"))
        self.assertTrue(res.ok)
        self.assertEqual(proc.stdin_data, b"review")

    def test_nonzero_exit_code_not_ok(self):
        """退出码非零 → ok=False 且 error 含退出码。"""
        proc = _FakeProc(returncode=2, output=b"boom")
        penv = ProviderEnv(app_type="codex", name="Kimi", env={"OPENAI_API_KEY": "k"})
        with mock.patch("asyncio.create_subprocess_shell", _fake_shell_factory({}, proc)):
            res = asyncio.run(CodexDispatcher().run(AgentTask(agent="codex", prompt="x"), penv))
        self.assertFalse(res.ok)
        self.assertEqual(res.exit_code, 2)
        self.assertIn("2", res.error)


if __name__ == "__main__":
    unittest.main()
