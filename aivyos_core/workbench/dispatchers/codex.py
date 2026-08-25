"""Codex CLI 分发器：注入 OPENAI_API_KEY / OPENAI_BASE_URL，prompt 走 stdin。

codex exec 的 stdout 混杂 banner/推理过程/token 统计，最终答复用
`-o <file>`（--output-last-message）单独落盘，优先取其为干净输出。
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from aivyos_core.workbench.dispatchers.base import run_cli
from aivyos_core.workbench.models import AgentResult, AgentTask, ProviderEnv


class CodexDispatcher:
    def __init__(self, cli_path: str = "codex", max_output: int = 32768) -> None:
        self.cli_path = cli_path
        self.max_output = max_output

    async def run(self, task: AgentTask, penv: ProviderEnv) -> AgentResult:
        last_msg = Path(tempfile.gettempdir()) / f"aivyos_codex_{uuid.uuid4().hex[:8]}.md"
        cmd = [self.cli_path, "exec", "-o", str(last_msg), *task.extra_args]
        try:
            result = await run_cli(
                cmd,
                agent="codex",
                env_extra=penv.env,
                cwd=task.cwd,
                timeout_s=task.timeout_s,
                input_text=task.prompt,
                max_output=self.max_output,
            )
            if result.ok and last_msg.exists():
                clean = last_msg.read_text(encoding="utf-8", errors="replace").strip()
                if clean:
                    result.output = clean
            return result
        finally:
            try:
                last_msg.unlink()
            except OSError:
                pass
