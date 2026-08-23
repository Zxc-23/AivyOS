"""VS Code 分发器：调用 `code` CLI 打开文件/目录。

code 不在 PATH 时优雅降级（返回 ok=False + 中文提示），不抛异常。
"""

from __future__ import annotations

import shutil
from typing import Optional

from aivyos_core.workbench.dispatchers.base import run_cli
from aivyos_core.workbench.models import AgentResult


class VSCodeDispatcher:
    def __init__(self, cli_path: str = "code") -> None:
        self.cli_path = cli_path

    def available(self) -> bool:
        return shutil.which(self.cli_path) is not None

    async def open(self, path: str, timeout_s: float = 30.0) -> AgentResult:
        if not self.available():
            return AgentResult(agent="vscode", error=f"VS Code CLI 不可用（{self.cli_path} 不在 PATH）")
        # Windows 路径含空格需双引号包裹；路径来自内部调用方，不来自 LLM 直接输入
        return await run_cli(f'"{self.cli_path}" "{path}"', agent="vscode", timeout_s=timeout_s)
