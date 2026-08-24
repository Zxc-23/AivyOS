"""Claude 工作流节点（§4.2.1）：执行用户请求，结果写入 state。

checkpoint 兼容：state 只写 JSON 可序列化值；WorkbenchService 经 ctx 注入。
"""

from __future__ import annotations

from typing import Any, Dict

_REVIEW_MAX = 6000


async def claude_node(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    svc = ctx.get("workbench")
    if svc is None:
        state.update(claude_ok=False, claude_output="", claude_error="ctx 缺少 workbench 服务")
        return state
    res = await svc.run_claude(state.get("user_request", ""), cwd=state.get("cwd") or None)
    state["claude_ok"] = res.ok
    state["claude_output"] = res.output
    state["claude_error"] = res.error
    if res.ok:
        # 为下游 codex 审查节点准备输入
        state["codex_prompt"] = (
            "请审查以下 Claude Code 的实现输出，指出问题与改进建议：\n\n"
            f"{res.output[:_REVIEW_MAX]}"
        )
    return state
