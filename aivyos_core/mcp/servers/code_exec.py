"""MCP code-exec Server（文档 §5.1.2 / T3.5）：Python 本地执行（L2，MRTR）。

- 默认：subprocess python 运行，受限环境（scratch cwd、剥离敏感 env、超时、输出上限）
- Docker 沙箱（可选）：配置 docker_image 且 docker 可用时，在容器内运行（§19.3 代码执行沙箱）
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from aivyos_core.mcp.types import PermissionLevel, Tool, ToolResult, make_tool


class CodeExecServer:
    def __init__(
        self,
        scratch_dir: Path,
        timeout_s: float = 20.0,
        max_output: int = 8192,
        docker_image: Optional[str] = "python:3.11-slim",
    ) -> None:
        self.scratch = Path(scratch_dir)
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.max_output = max_output
        self.docker_image = docker_image

    def _docker_available(self) -> bool:
        if not self.docker_image:
            return False
        return shutil.which("docker") is not None

    async def _run(self, args: Dict[str, Any]) -> ToolResult:
        code = args.get("code", "")
        timeout = float(args.get("timeout_s", self.timeout_s))
        if not code:
            return ToolResult(False, error="code 为空")
        workdir = self.scratch / "run"
        workdir.mkdir(parents=True, exist_ok=True)
        script = workdir / "main.py"
        script.write_text(code, encoding="utf-8")
        out_path = self.scratch / f"out_{uuid.uuid4().hex[:8]}.txt"

        if self._docker_available():
            cmd = [
                "docker", "run", "--rm", "--network", "none",
                "-v", f"{workdir}:/work", "-w", "/work",
                self.docker_image, "python", "main.py",
            ]
        else:
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
            cmd = [sys.executable, "main.py"]
        try:
            with open(out_path, "wb") as f:
                # 输出写文件而非管道（沙箱限制）
                proc = await asyncio.create_subprocess_exec(
                    *cmd, cwd=str(workdir), stdout=f, stderr=subprocess.STDOUT,
                    env=env if not self._docker_available() else None,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout)
                except asyncio.TimeoutError:
                    proc.kill()
                    return ToolResult(False, error=f"执行超时（>{timeout:.0f}s）")
            text = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
            truncated = len(text) > self.max_output
            ok = proc.returncode == 0
            return ToolResult(
                ok,
                content=(text[: self.max_output] + "\n…(截断)") if truncated else text,
                error="" if ok else f"执行失败（exit code {proc.returncode}）",
                data={"exit_code": proc.returncode, "sandbox": "docker" if self._docker_available() else "subprocess"},
            )
        except Exception as e:
            return ToolResult(False, error=str(e))
        finally:
            if out_path.exists():
                out_path.unlink()

    def tools(self) -> list[Tool]:
        return [
            make_tool(
                "code_exec", "执行 Python 代码（L2，需确认，沙箱运行）",
                {"type": "object", "properties": {
                    "code": {"type": "string"}, "timeout_s": {"type": "number"}},
                    "required": ["code"]},
                self._run, PermissionLevel.L2,
                impact=lambda a: f"执行 Python 代码（{len(a.get('code', ''))} 字符，沙箱）",
                server="code_exec",
            ),
        ]
