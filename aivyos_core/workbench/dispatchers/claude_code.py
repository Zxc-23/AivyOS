"""Claude Code CLI 分发器：注入 cc-switch 环境变量，prompt 走 stdin。

Windows 上 claude 是 npm .cmd shim，必须经 create_subprocess_shell 解析。
"""

from __future__ import annotations

from aivyos_core.workbench.dispatchers.base import run_cli
from aivyos_core.workbench.models import AgentResult, AgentTask, ProviderEnv


class ClaudeCodeDispatcher:
    def __init__(self, cli_path: str = "claude", max_output: int = 32768) -> None:
        self.cli_path = cli_path
        self.max_output = max_output

    async def run(self, task: AgentTask, penv: ProviderEnv) -> AgentResult:
        cmd = " ".join([self.cli_path, "-p", "--output-format", "text", *task.extra_args])
        return await run_cli(
            cmd,
            agent="claude",
            env_extra=penv.env,
            cwd=task.cwd,
            timeout_s=task.timeout_s,
            input_text=task.prompt,
            max_output=self.max_output,
        )
