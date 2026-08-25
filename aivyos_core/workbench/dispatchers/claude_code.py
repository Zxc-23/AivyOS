"""Claude Code CLI 分发器：注入 cc-switch 环境变量，prompt 走 stdin。

Windows 上 claude 是 npm .cmd shim，必须经 create_subprocess_shell 解析。
cc-switch 的自定义模型名（如 kimi-k2.7-code）会触发 Claude Code 的
"unknown model" 警告段混入 stdout，这里过滤掉已知噪音行。

关键修复：添加 --dangerously-skip-permissions 参数，使 Claude Code 在非交互
子进程中自动通过写入权限确认（否则 Claude 只会"描述"要做什么而不真正写文件）。
同时增加文件快照机制，在执行前后对比工作区文件以检测实际产出。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from aivyos_core.workbench.dispatchers.base import run_cli
from aivyos_core.workbench.models import AgentResult, AgentTask, ProviderEnv

_NOISE_MARKERS = ("not a model this version", "CLAUDE_CODE_")

# 需要跳过的目录和文件（不纳入文件快照对比）
_SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".aivyos_workspace"}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".cache", ".sqlite", ".db",
                  ".exe", ".dll", ".so", ".dylib", ".class"}

# AIVY-REPORT-001 Task2: before 文件内容缓存（500KB 上限，大文件不缓存 diff）
_CONTENT_CACHE_MAX_BYTES = 500_000
_BEFORE_CONTENT_CACHE: Dict[str, str] = {}


def get_before_content_cache() -> Dict[str, str]:
    """功能描述：导出执行前文件内容缓存的只读副本（供 service.py 读 before 文本）。

    参数类型：无

    返回值类型：
        - Dict[str, str] — {相对路径: utf-8 replace 解码后的文件内容} 的浅拷贝，调用方修改不影响模块级全局
    """
    return dict(_BEFORE_CONTENT_CACHE)


def _strip_noise(text: str) -> str:
    """移除 Claude Code 输出中的噪音行（模型警告、内部标记等）。"""
    lines = [l for l in text.splitlines() if not any(m in l for m in _NOISE_MARKERS)]
    return "\n".join(lines).strip()


def _take_snapshot(cwd: Optional[str]) -> Dict[str, float]:
    """对工作区取文件快照：{相对路径: mtime}。

    副作用（AIVY-REPORT-001 Task2）：在 return 之前，将 <=500KB 的文本文件读入
    模块级全局 _BEFORE_CONTENT_CACHE，key=相对路径（相对 cwd），value=utf-8 replace 解码文本；
    先 _BEFORE_CONTENT_CACHE.clear() 再填充，零破坏既有 Dict[str, float] 返回契约。

    返回当前工作区所有文件的路径和修改时间戳，用于前后对比检测变更。
    """
    if not cwd:
        _BEFORE_CONTENT_CACHE.clear()
        return {}
    root = Path(cwd).resolve()
    if not root.is_dir():
        _BEFORE_CONTENT_CACHE.clear()
        return {}
    snapshot: Dict[str, float] = {}
    temp_cache: Dict[str, str] = {}
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                fp = Path(dirpath) / fname
                if fp.suffix.lower() in _SKIP_SUFFIXES:
                    continue
                rel = str(fp.relative_to(root))
                try:
                    st = fp.stat()
                    snapshot[rel] = st.st_mtime
                    # AIVY-REPORT-001 Task2: <=500KB 则缓存文本内容
                    if st.st_size <= _CONTENT_CACHE_MAX_BYTES:
                        try:
                            raw = fp.read_bytes()
                            temp_cache[rel] = raw.decode("utf-8", errors="replace")
                        except OSError:
                            pass
                except OSError:
                    pass
    except OSError:
        pass
    _BEFORE_CONTENT_CACHE.clear()
    _BEFORE_CONTENT_CACHE.update(temp_cache)
    return snapshot


def _detect_changes(before: Dict[str, float], after: Dict[str, float]) -> List[str]:
    """对比前后快照，返回新增或修改的文件列表（相对路径）。"""
    changed: List[str] = []
    for path, mtime in after.items():
        if path not in before:
            changed.append(path)
        elif before[path] != mtime:
            changed.append(path)
    return sorted(changed)


def _build_review_prompt_with_files(output_text: str, files_created: List[str],
                                     max_file_content: int = 4000) -> str:
    """构建包含实际文件内容的审查 prompt。
    
    当有文件产出时，读取文件实际内容附加到 Claude 的文本输出之后，
    使 Codex 能审查真实代码而非仅依赖 Claude 的文字描述。
    """
    parts = [f"以下是 Claude Code 的实现输出（文字描述）：\n\n{output_text[:3000]}"]
    
    if files_created:
        parts.append(f"\n\n## 实际创建/修改的文件（{len(files_created)} 个）：")
        for fpath in files_created[:20]:
            parts.append(f"\n### {fpath}")
            try:
                p = Path(fpath)
                if p.is_file():
                    content = p.read_text(encoding="utf-8", errors="replace")
                    if len(content) > max_file_content:
                        content = content[:max_file_content] + "\n...(文件内容已截断)"
                    parts.append(f"```\n{content}\n```")
                else:
                    parts.append(f"（目录：{fpath}）")
            except Exception as e:
                parts.append(f"（无法读取：{e}）")
        if len(files_created) > 20:
            parts.append(f"\n... 还有 {len(files_created) - 20} 个文件未列出")
    
    return "\n".join(parts)


class ClaudeCodeDispatcher:
    """Claude Code CLI 分发器。
    
    关键特性：
    1. --dangerously-skip-permissions：非交互模式下自动批准写入请求
    2. 文件快照：执行前后对比工作区，检测实际产出文件
    3. 噪音过滤：移除模型警告等干扰输出
    """

    def __init__(self, cli_path: str = "claude", max_output: int = 32768,
                 skip_permissions: bool = True) -> None:
        """初始化分发器。

        Args:
            cli_path: Claude Code CLI 可执行文件路径
            max_output: 输出最大字节数（截断保护）
            skip_permissions: 是否跳过写入权限确认（非交互模式必须启用）
        """
        self.cli_path = cli_path
        self.max_output = max_output
        self.skip_permissions = skip_permissions

    async def run(self, task: AgentTask, penv: ProviderEnv) -> AgentResult:
        """执行 Claude Code 任务。

        Args:
            task: 包含 prompt、cwd、timeout 等的任务对象
            penv: 提供商环境变量

        Returns:
            AgentResult: 包含输出、耗时、创建的文件列表
        """
        # 1. 执行前取文件快照
        before_snapshot = _take_snapshot(task.cwd)

        # 2. 构建命令（添加 --dangerously-skip-permissions）
        cmd_parts = [self.cli_path, "-p", "--output-format", "text"]
        if self.skip_permissions:
            cmd_parts.append("--dangerously-skip-permissions")
        cmd_parts.extend(task.extra_args)

        # 3. 执行（使用参数列表，避免 shell 注入）
        result = await run_cli(
            cmd_parts,
            agent="claude",
            env_extra=penv.env,
            cwd=task.cwd,
            timeout_s=task.timeout_s,
            input_text=task.prompt,
            max_output=self.max_output,
        )

        # 4. 执行后取快照并检测变更
        after_snapshot = _take_snapshot(task.cwd)
        result.files_created = _detect_changes(before_snapshot, after_snapshot)

        # 5. 噪音过滤
        if result.ok and result.output:
            result.output = _strip_noise(result.output)

        # 6. 语义检测：如果 Claude 说"等待权限确认"，标记为需注意
        if result.output and "等待你的写入权限确认" in result.output:
            result.output += "\n\n[系统检测] Claude Code 请求了写入权限但处于非交互模式，" \
                           "已通过 --dangerously-skip-permissions 自动批准。"

        return result