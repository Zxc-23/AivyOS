"""Codex 工作流节点（§4.2.1）：执行 state["codex_prompt"]（缺省用 user_request）。"""

from __future__ import annotations

from typing import Any, Dict


async def codex_node(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    svc = ctx.get("workbench")
    if svc is None:
        state.update(codex_ok=False, codex_output="", codex_error="ctx 缺少 workbench 服务")
        return state
    prompt = state.get("codex_prompt") or state.get("user_request", "")
    res = await svc.run_codex(prompt, cwd=state.get("cwd") or None)
    state["codex_ok"] = res.ok
    state["codex_output"] = res.output
    state["codex_error"] = res.error
    return state
