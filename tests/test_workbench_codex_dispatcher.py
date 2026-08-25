"""Codex 分发器测试：OPENAI_* 注入、非零退出码。"""

import asyncio
import unittest
from unittest import mock

from tests import AivyTestCase
from aivyos_core.workbench.dispatchers.codex import CodexDispatcher
from aivyos_core.workbench.models import AgentTask, ProviderEnv
from tests.test_workbench_claude_dispatcher import _FakeProc, _fake_shell_factory, _patch_subprocess


class TestCodexDispatcher(AivyTestCase):
    def test_env_injected(self):
        """OPENAI_API_KEY / OPENAI_BASE_URL 注入子进程 env，命令为 codex exec。"""
        recorder: dict = {}
        proc = _FakeProc(output=b"codex-out")
        penv = ProviderEnv(app_type="codex", name="Kimi",
                           env={"OPENAI_API_KEY": "ok-secret", "OPENAI_BASE_URL": "https://x/v1"})
        with _patch_subprocess(recorder, proc):
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
        with _patch_subprocess({}, proc):
            res = asyncio.run(CodexDispatcher().run(AgentTask(agent="codex", prompt="x"), penv))
        self.assertFalse(res.ok)
        self.assertEqual(res.exit_code, 2)
        self.assertIn("2", res.error)

    def test_output_last_message_preferred(self):
        """-o 落盘的最终答复优先于混杂 banner/推理的 stdout。"""
        import re

        async def _fake(*args, **kwargs):
            # Support both shell string and exec list
            if len(args) == 1 and isinstance(args[0], str):
                cmd_str = args[0]
            else:
                cmd_str = " ".join(str(a) for a in args)
            # Handle both quoted and unquoted -o path
            m = re.search(r'-o "([^"]+)"', cmd_str) or re.search(r'-o (\S+)', cmd_str)
            self.assertIsNotNone(m, "命令应包含 -o <file>")
            with open(m.group(1), "w", encoding="utf-8") as f:
                f.write("干净的最终答复")
            out = kwargs.get("stdout")
            out.write("OpenAI Codex v0.149.0\nbanner 噪音\ntokens used\n1,234".encode("utf-8"))
            out.flush()
            return _FakeProc()

        penv = ProviderEnv(app_type="codex", name="Kimi", env={"OPENAI_API_KEY": "k"})
        with mock.patch.multiple(
            "asyncio",
            create_subprocess_shell=_fake,
            create_subprocess_exec=_fake,
        ):
            res = asyncio.run(CodexDispatcher().run(AgentTask(agent="codex", prompt="x"), penv))
        self.assertTrue(res.ok)
        self.assertEqual(res.output, "干净的最终答复")


if __name__ == "__main__":
    unittest.main()
