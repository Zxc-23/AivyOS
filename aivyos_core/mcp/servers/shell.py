"""MCP shell Server（文档 §5.1.2 / T3.3）：命令执行，MRTR 确认（L2）。

注意：输出经临时文件重定向而非管道（沙箱环境禁止 piped-stdio 子进程）。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict

from aivyos_core.mcp.types import PermissionLevel, Tool, ToolResult, make_tool


class ShellServer:
    def __init__(self, timeout_s: float = 30.0, max_output: int = 8192) -> None:
        self.timeout_s = timeout_s
        self.max_output = max_output

    async def _run(self, args: Dict[str, Any]) -> ToolResult:
        command = args.get("command", "")
        timeout = float(args.get("timeout_s", self.timeout_s))
        cwd = args.get("cwd")
        if not command:
            return ToolResult(False, error="command 为空")
        out_path = Path(tempfile.gettempdir()) / f"aivyos_sh_{uuid.uuid4().hex[:8]}.txt"
        try:
            with open(out_path, "wb") as f:
                # 输出写文件而非管道（沙箱限制），stderr 并入 stdout
                proc = await asyncio.create_subprocess_shell(
                    command, stdout=f, stderr=subprocess.STDOUT, cwd=cwd,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout)
                except asyncio.TimeoutError:
                    proc.kill()
                    return ToolResult(False, error=f"命令超时（>{timeout:.0f}s）: {command[:80]}")
            text = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
            truncated = len(text) > self.max_output
            return ToolResult(
                True,
                content=(text[: self.max_output] + "\n…(截断)") if truncated else text,
                data={"exit_code": proc.returncode, "truncated": truncated},
            )
        except Exception as e:
            return ToolResult(False, error=str(e))
        finally:
            try:
                out_path.unlink()
            except OSError:
                pass  # 子进程可能仍持有句柄，忽略

    def tools(self) -> list[Tool]:
        return [
            make_tool(
                "shell_run", "执行系统命令（L2，需确认）",
                {"type": "object", "properties": {
                    "command": {"type": "string"}, "timeout_s": {"type": "number"}, "cwd": {"type": "string"}},
                    "required": ["command"]},
                self._run, PermissionLevel.L2,
                impact=lambda a: f"执行命令: {a.get('command', '')[:80]}",
                server="shell",
            ),
        ]
