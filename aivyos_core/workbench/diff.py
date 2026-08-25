"""Diff 捕获（计划书 §4.2.3）：读取用户在编辑器里的改动，交给模型二次审查。

经 `git diff HEAD` 捕获工作区改动（含已暂存）；非 git 仓库或无改动时诚实报错。
"""

from __future__ import annotations

from aivyos_core.workbench.dispatchers.base import run_cli
from aivyos_core.workbench.models import AgentResult

_DIFF_MAX = 12000  # 发给模型审查的 diff 截断长度


async def capture_diff(cwd: str, timeout_s: float = 30.0) -> AgentResult:
    """捕获 cwd 所在仓库的 git diff（工作区 + 暂存区 vs HEAD）。"""
    result = await run_cli(["git", "diff", "HEAD"], agent="git", cwd=cwd, timeout_s=timeout_s,
                           max_output=_DIFF_MAX * 2)
    if not result.ok:
        result.error = f"git diff 失败（{cwd} 不是 git 仓库或无 git）: {result.error}"
        return result
    if not result.output.strip():
        result.ok = False
        result.error = "工作区没有改动（git diff 为空）"
    return result


def build_review_prompt(diff_text: str) -> str:
    return (
        "请审查以下 git diff（用户在编辑器中的改动），指出潜在 bug、风格问题与改进建议：\n\n"
        f"{diff_text[:_DIFF_MAX]}"
    )
