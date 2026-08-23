"""Codex CLI 分发器：注入 OPENAI_API_KEY / OPENAI_BASE_URL，prompt 走 stdin。"""

from __future__ import annotations

from aivyos_core.workbench.dispatchers.base import run_cli
from aivyos_core.workbench.models import AgentResult, AgentTask, ProviderEnv


class CodexDispatcher:
    def __init__(self, cli_path: str = "codex", max_output: int = 32768) -> None:
        self.cli_path = cli_path
        self.max_output = max_output

    async def run(self, task: AgentTask, penv: ProviderEnv) -> AgentResult:
        cmd = " ".join([self.cli_path, "exec", *task.extra_args])
        return await run_cli(
            cmd,
            agent="codex",
            env_extra=penv.env,
            cwd=task.cwd,
            timeout_s=task.timeout_s,
            input_text=task.prompt,
            max_output=self.max_output,
        )
