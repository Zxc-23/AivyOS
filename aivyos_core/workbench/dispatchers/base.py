"""子进程执行基座：复用 mcp/servers/shell.py 的沙箱兼容范式。

- stdout/stderr 重定向到临时文件（沙箱禁止 piped-stdio），读回后删除
- prompt 经 stdin 传入，避免 Windows cmd 字符串拼接的引号/百分号转义问题
- env_extra 只合并进子进程环境（{**os.environ, **env_extra}），不污染父进程
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

from aivyos_core.workbench.models import AgentResult


async def run_cli(
    command: List[str],
    *,
    agent: str = "",
    env_extra: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    timeout_s: float = 300.0,
    input_text: Optional[str] = None,
    max_output: int = 32768,
) -> AgentResult:
    """执行外部 CLI（参数列表形式，避免 shell 注入）。

    Args:
        command: 命令参数列表（第一个元素为可执行文件）。
        agent: Agent 标识，用于错误信息。
        env_extra: 额外环境变量（合并到子进程环境）。
        cwd: 子进程工作目录。
        timeout_s: 超时秒数。
        input_text: 通过 stdin 传入子进程的文本。
        max_output: 最大输出字符数，超出截断。

    Returns:
        AgentResult: 包含输出、退出码、耗时和错误信息。
    """
    started = time.monotonic()
    out_path = Path(tempfile.gettempdir()) / f"aivyos_wb_{uuid.uuid4().hex[:8]}.txt"
    env = {**os.environ, **(env_extra or {})}
    proc = None
    # Pre-compute display string so FileNotFoundError handler can reference it
    cmd_display = " ".join(shlex.quote(str(p)) for p in command)
    try:
        with open(out_path, "wb") as f:
            # 统一使用 create_subprocess_exec，杜绝 shell 注入
            proc = await asyncio.create_subprocess_exec(
                *command,
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
                    agent=agent, error=f"命令超时（>{timeout_s:.0f}s）: {cmd_display[:80]}",
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
            agent=agent, error=f"CLI 不可用（不在 PATH）: {command[0] if command else cmd_display}",
            elapsed_s=time.monotonic() - started,
        )
    except Exception as e:
        return AgentResult(agent=agent, error=str(e), elapsed_s=time.monotonic() - started)
    finally:
        try:
            out_path.unlink()
        except OSError:
            log.debug("清理临时输出文件失败: %s", out_path, exc_info=True)
