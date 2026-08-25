"""Claude Code 分发器测试：env 注入 / 不污染父进程 / 超时 kill / 真实子进程解码。

新增测试：--dangerously-skip-permissions 标志、文件快照机制、文件变更检测、
        _build_review_prompt_with_files 审查 prompt 构建。
"""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import AivyTestCase
from aivyos_core.workbench.dispatchers.base import run_cli
from aivyos_core.workbench.dispatchers.claude_code import (
    ClaudeCodeDispatcher,
    _build_review_prompt_with_files,
    _detect_changes,
    _take_snapshot,
)
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
        self.assertNotEqual(os.environ.get("ANTHROPIC_AUTH_TOKEN"), "tok-secret")
        self.assertTrue(res.ok)
        self.assertIn("ok-output", res.output)
        self.assertEqual(proc.stdin_data, b"hi")

    def test_skip_permissions_flag_added(self):
        """skip_permissions=True 时命令包含 --dangerously-skip-permissions。"""
        recorder: dict = {}
        proc = _FakeProc(output=b"ok")
        penv = ProviderEnv(app_type="claude", name="Kimi", env={})
        dispatcher = ClaudeCodeDispatcher(skip_permissions=True)
        with mock.patch("asyncio.create_subprocess_shell", _fake_shell_factory(recorder, proc)):
            asyncio.run(dispatcher.run(AgentTask(agent="claude", prompt="hi"), penv))
        self.assertIn("--dangerously-skip-permissions", recorder["cmd"])

    def test_skip_permissions_flag_absent_when_disabled(self):
        """skip_permissions=False 时命令不含 --dangerously-skip-permissions。"""
        recorder: dict = {}
        proc = _FakeProc(output=b"ok")
        penv = ProviderEnv(app_type="claude", name="Kimi", env={})
        dispatcher = ClaudeCodeDispatcher(skip_permissions=False)
        with mock.patch("asyncio.create_subprocess_shell", _fake_shell_factory(recorder, proc)):
            asyncio.run(dispatcher.run(AgentTask(agent="claude", prompt="hi"), penv))
        self.assertNotIn("--dangerously-skip-permissions", recorder["cmd"])

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

    def test_strip_noise_removes_unknown_model_warning(self):
        """unknown-model 警告段被过滤，正文保留。"""
        from aivyos_core.workbench.dispatchers.claude_code import _strip_noise

        noisy = (
            '"kimi-k2.7-code" is not a model this version of Claude Code recognizes, so auto-compact...\n'
            'set CLAUDE_CODE_MAX_CONTEXT_TOKENS to its real window\n'
            '我是正经回答。'
        )
        self.assertEqual(_strip_noise(noisy), "我是正经回答。")

    def test_snapshot_detects_new_files(self):
        """文件快照机制：检测新增和修改的文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "old_file.txt").write_text("original")
            
            before = _take_snapshot(str(root))
            self.assertIn("old_file.txt", before)
            
            # 新建文件
            (root / "new_file.html").write_text("<html></html>")
            
            after = _take_snapshot(str(root))
            changes = _detect_changes(before, after)
            
            self.assertIn("new_file.html", changes)
            self.assertNotIn("old_file.txt", changes)

    def test_snapshot_detects_modified_files(self):
        """文件快照机制：检测已有文件的修改。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            f = root / "code.py"
            f.write_text("version 1")
            
            before = _take_snapshot(str(root))
            
            # 修改文件（需要等待以确保 mtime 不同）
            import time
            time.sleep(0.1)
            f.write_text("version 2 - modified")
            
            after = _take_snapshot(str(root))
            changes = _detect_changes(before, after)
            
            self.assertIn("code.py", changes)

    def test_snapshot_skips_internal_dirs(self):
        """文件快照：跳过 .git、__pycache__ 等内部目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "real_file.txt").write_text("keep")
            (root / ".git").mkdir(exist_ok=True)
            (root / ".git" / "config").write_text("skip")
            
            snapshot = _take_snapshot(str(root))
            
            self.assertIn("real_file.txt", snapshot)
            self.assertNotIn(".git/config", snapshot)

    def test_snapshot_handles_missing_dir(self):
        """文件快照：目录不存在时返回空字典。"""
        self.assertEqual(_take_snapshot(None), {})
        self.assertEqual(_take_snapshot("/nonexistent/path"), {})

    def test_build_review_prompt_with_files(self):
        """审查 prompt 构建：有文件时包含文件内容。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            test_file = root / "test.py"
            test_file.write_text("print('hello')")
            
            prompt = _build_review_prompt_with_files(
                "Claude 实现了一个函数",
                [str(test_file)],
            )
            
            self.assertIn("Claude 实现了一个函数", prompt)
            self.assertIn("test.py", prompt)
            self.assertIn("print('hello')", prompt)

    def test_build_review_prompt_without_files(self):
        """审查 prompt 构建：无文件时仅用文字描述。"""
        prompt = _build_review_prompt_with_files("简单描述", [])
        self.assertIn("简单描述", prompt)
        self.assertNotIn("实际创建", prompt)


if __name__ == "__main__":
    unittest.main()