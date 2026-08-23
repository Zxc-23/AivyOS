"""子进程执行基座：复用 mcp/servers/shell.py 的沙箱兼容范式。

- stdout/stderr 重定向到临时文件（沙箱禁止 piped-stdio），读回后删除
- prompt 经 stdin 传入，避免 Windows cmd 字符串拼接的引号/百分号转义问题
- env_extra 只合并进子进程环境（{**os.environ, **env_extra}），不污染父进程
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from aivyos_core.workbench.models import AgentResult


async def run_cli(
    command: str,
    *,
    agent: str = "",
    env_extra: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    timeout_s: float = 300.0,
    input_text: Optional[str] = None,
    max_output: int = 32768,
) -> AgentResult:
    started = time.monotonic()
    out_path = Path(tempfile.gettempdir()) / f"aivyos_wb_{uuid.uuid4().hex[:8]}.txt"
    env = {**os.environ, **(env_extra or {})}
    proc = None
    try:
        with open(out_path, "wb") as f:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE if input_text is not None else None,
                stdout=f,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                env=env,
            )
            try:
                data = input_text.encode("utf-8") if input_text is not None else None
                await asyncio.wait_for(proc.communicate(data), timeout_s)
            except asyncio.TimeoutError:
                proc.kill()
                return AgentResult(
                    agent=agent, error=f"命令超时（>{timeout_s:.0f}s）: {command[:80]}",
                    elapsed_s=time.monotonic() - started,
                )
        text = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
        truncated = len(text) > max_output
        if truncated:
            text = text[:max_output] + "\n…(截断)"
        code = proc.returncode if proc.returncode is not None else -1
        return AgentResult(
            agent=agent,
            ok=code == 0,
            output=text,
            exit_code=code,
            elapsed_s=time.monotonic() - started,
            error="" if code == 0 else f"退出码 {code}",
        )
    except FileNotFoundError:
        return AgentResult(
            agent=agent, error=f"CLI 不可用（不在 PATH）: {command.split()[0]}",
            elapsed_s=time.monotonic() - started,
        )
    except Exception as e:
        return AgentResult(agent=agent, error=str(e), elapsed_s=time.monotonic() - started)
    finally:
        try:
            out_path.unlink()
        except OSError:
            pass  # 子进程可能仍持有句柄，忽略
