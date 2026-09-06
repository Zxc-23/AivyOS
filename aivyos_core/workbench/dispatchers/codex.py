"""Codex CLI 分发器：注入 OPENAI_API_KEY / OPENAI_BASE_URL，prompt 走 stdin。

codex exec 的 stdout 混杂 banner/推理过程/token 统计，最终答复用
`-o <file>`（--output-last-message）单独落盘，优先取其为干净输出。
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Optional

from aivyos_core.workbench.dispatchers.base import run_cli
from aivyos_core.workbench.models import AgentResult, AgentTask, ProviderEnv


class CodexDispatcher:
    def __init__(self, cli_path: str = "codex", max_output: int = 32768) -> None:
        self.cli_path = cli_path
        self.max_output = max_output

    @staticmethod
    async def _preflight_check(penv: ProviderEnv) -> Optional[str]:
        """执行前置检查：验证配置有效性。

        Args:
            penv: 提供商环境变量

        Returns:
            如果检查通过返回 None，否则返回错误消息。
        """
        base_url = penv.env.get("OPENAI_BASE_URL", "") or penv.env.get("OPENAI_API_BASE", "")
        if not base_url:
            return None

        api_key = penv.env.get("OPENAI_API_KEY", "")
        if not api_key:
            return "未配置 API Key：请在 cc-switch 或 AivyOS 手动配置中设置有效的 API Key"

        if api_key in ("ollama", "sk-ollama", "dummy", "test"):
            return (
                f"API Key 为占位符 '{api_key}'，Codex CLI 需要真实的 API Key。\n"
                f"[建议] 请在 cc-switch 中配置有效的 API Key，或使用 AivyOS 内置的 Ollama 支持"
            )

        return None

    async def run(self, task: AgentTask, penv: ProviderEnv) -> AgentResult:
        # 前置检查
        preflight_error = await self._preflight_check(penv)
        if preflight_error:
            return AgentResult(
                agent="codex",
                ok=False,
                error=preflight_error,
                elapsed_s=0,
            )

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
