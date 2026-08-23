"""Claude Code CLI 分发器：注入 cc-switch 环境变量，prompt 走 stdin。

Windows 上 claude 是 npm .cmd shim，必须经 create_subprocess_shell 解析。
cc-switch 的自定义模型名（如 kimi-k2.7-code）会触发 Claude Code 的
"unknown model" 警告段混入 stdout，这里过滤掉已知噪音行。
"""

from __future__ import annotations

from aivyos_core.workbench.dispatchers.base import run_cli
from aivyos_core.workbench.models import AgentResult, AgentTask, ProviderEnv

_NOISE_MARKERS = ("not a model this version", "CLAUDE_CODE_")


def _strip_noise(text: str) -> str:
    lines = [l for l in text.splitlines() if not any(m in l for m in _NOISE_MARKERS)]
    return "\n".join(lines).strip()


class ClaudeCodeDispatcher:
    def __init__(self, cli_path: str = "claude", max_output: int = 32768) -> None:
        self.cli_path = cli_path
        self.max_output = max_output

    async def run(self, task: AgentTask, penv: ProviderEnv) -> AgentResult:
        cmd = " ".join([self.cli_path, "-p", "--output-format", "text", *task.extra_args])
        result = await run_cli(
            cmd,
            agent="claude",
            env_extra=penv.env,
            cwd=task.cwd,
            timeout_s=task.timeout_s,
            input_text=task.prompt,
            max_output=self.max_output,
        )
        if result.ok and result.output:
            result.output = _strip_noise(result.output)
        return result
