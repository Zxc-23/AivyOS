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
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

from aivyos_core.workbench.models import AgentResult


def _resolve_command(command: List[str]) -> List[str]:
    """解析命令可执行文件路径。

    Windows 上 asyncio.create_subprocess_exec 不会自动追加 PATHEXT 扩展名，
    因此 npm 全局安装的 shim（如 claude.cmd、codex.cmd）无法通过 'claude'、'codex'
    直接启动。本函数使用 shutil.which 在 PATH 中查找完整路径（含扩展名）。

    Args:
        command: 原始命令参数列表。

    Returns:
        第一个元素已解析为完整可执行路径的命令列表；未解析到则原样返回。
    """
    if not command or sys.platform != "win32":
        return command
    cmd0 = command[0]
    p = Path(cmd0)
    # 已是绝对路径或带扩展名，无需解析
    if p.is_absolute() or p.suffix:
        return command
    resolved = shutil.which(cmd0)
    if resolved:
        return [resolved, *command[1:]]
    return command


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
    # Windows 上解析 npm shim 的 .cmd/.ps1 扩展名
    command = _resolve_command(command)
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

        # 构建错误信息：包含 CLI 实际输出帮助诊断
        error_msg = ""
        if code != 0:
            # 提取关键错误信息（取最后 500 字符）
            error_text = text.strip()
            if error_text:
                # 尝试提取第一行或关键错误信息
                lines = error_text.splitlines()
                key_line = ""
                for line in lines:
                    lower = line.lower()
                    if any(kw in lower for kw in ("error", "fail", "refused", "denied", "invalid", "unauthorized", "forbidden", "timeout", "connection")):
                        key_line = line.strip()
                        break
                if not key_line and lines:
                    key_line = lines[-1].strip()
                # 截断过长的错误行
                if len(key_line) > 200:
                    key_line = key_line[:200] + "..."
                error_msg = f"退出码 {code}: {key_line}"
            else:
                error_msg = f"退出码 {code}"

            # 常见错误的友好提示
            if "connection refused" in error_text.lower():
                error_msg += "\n[建议] API 端点不可达，请检查：1) 网络连接 2) API Base URL 是否正确 3) 防火墙/代理设置"
            elif "authentication" in error_text.lower() or "unauthorized" in error_text.lower() or "401" in error_text:
                error_msg += "\n[建议] API Key 无效或未配置，请在 cc-switch 或 AivyOS 手动配置中设置有效的 API Key"
            elif "not found" in error_text.lower() or "404" in error_text:
                error_msg += "\n[建议] API 端点或模型不存在，请检查 Base URL 和模型名称"
            elif "timed out" in error_text.lower() or "timeout" in error_text.lower():
                error_msg += "\n[建议] 请求超时，请检查网络连接或增加超时时间"
            elif "proxy" in error_text.lower() or "firewall" in error_text.lower():
                error_msg += "\n[建议] 检测到代理/防火墙问题，请检查网络代理配置"

        return AgentResult(
            agent=agent,
            ok=code == 0,
            output=text,
            exit_code=code,
            elapsed_s=time.monotonic() - started,
            error=error_msg,
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
