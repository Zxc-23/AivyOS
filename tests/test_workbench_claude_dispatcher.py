"""Claude Code 分发器测试：env 注入 / 不污染父进程 / 超时 kill / 真实子进程解码。"""

import asyncio
import os
import sys
import unittest
from unittest import mock

from tests import AivyTestCase
from aivyos_core.workbench.dispatchers.base import run_cli
from aivyos_core.workbench.dispatchers.claude_code import ClaudeCodeDispatcher
from aivyos_core.workbench.models import AgentTask, ProviderEnv


class _FakeProc:
    def __init__(self, returncode=0, output=b"", hang=False):
        self.returncode = returncode
        self._output = output
        self._hang = hang
        self.killed = False
        self.stdin_data = None

    async def communicate(self, data=None):
        self.stdin_data = data
        if self._hang:
            await asyncio.sleep(60)
        return (None, None)

    def kill(self):
        self.killed = True


def _fake_shell_factory(recorder, proc):
    async def _fake(cmd, **kwargs):
        recorder["cmd"] = cmd
        recorder["env"] = kwargs.get("env")
        recorder["cwd"] = kwargs.get("cwd")
        out = kwargs.get("stdout")
        if out is not None and proc._output:
            out.write(proc._output)
            out.flush()
        return proc

    return _fake


class TestClaudeDispatcher(AivyTestCase):
    def test_env_injected_and_parent_not_polluted(self):
        """ANTHROPIC_AUTH_TOKEN 注入子进程 env，且不写入 os.environ。"""
        recorder: dict = {}
        proc = _FakeProc(output=b"ok-output")
        penv = ProviderEnv(app_type="claude", name="Kimi",
                           env={"ANTHROPIC_AUTH_TOKEN": "tok-secret", "ANTHROPIC_BASE_URL": "https://x"})
        with mock.patch("asyncio.create_subprocess_shell", _fake_shell_factory(recorder, proc)):
            res = asyncio.run(ClaudeCodeDispatcher().run(AgentTask(agent="claude", prompt="hi"), penv))
        self.assertEqual(recorder["env"]["ANTHROPIC_AUTH_TOKEN"], "tok-secret")
        # 父进程环境不被注入值覆盖（本机本身可能有同名变量，只断言值未被改）
        self.assertNotEqual(os.environ.get("ANTHROPIC_AUTH_TOKEN"), "tok-secret")
        self.assertTrue(res.ok)
        self.assertIn("ok-output", res.output)
        self.assertEqual(proc.stdin_data, b"hi")  # prompt 走 stdin

    def test_timeout_kills_process(self):
        """超时后 proc.kill() 被调用，返回超时错误。"""
        proc = _FakeProc(hang=True)
        with mock.patch("asyncio.create_subprocess_shell", _fake_shell_factory({}, proc)):
            res = asyncio.run(run_cli("claude -p", agent="claude", timeout_s=0.05, input_text="x"))
        self.assertTrue(proc.killed)
        self.assertFalse(res.ok)
        self.assertIn("超时", res.error)

    def test_real_subprocess_stdin_roundtrip(self):
        """真实子进程（python -c）：stdin 输入被读取，输出 utf-8 解码。"""
        cmd = f'"{sys.executable}" -c "import sys; print(sys.stdin.read().upper())"'
        res = asyncio.run(run_cli(cmd, agent="claude", input_text="hello aivyos", timeout_s=30))
        self.assertTrue(res.ok, res.error)
        self.assertIn("HELLO AIVYOS", res.output)


if __name__ == "__main__":
    unittest.main()
