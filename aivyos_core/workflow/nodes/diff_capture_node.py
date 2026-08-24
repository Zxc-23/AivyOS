"""Diff 捕获工作流节点（§4.2.1）：git diff 写入 state["diff_text"]。"""

from __future__ import annotations

from typing import Any, Dict

from aivyos_core.workbench.diff import build_review_prompt, capture_diff


async def diff_capture_node(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    res = await capture_diff(state.get("cwd") or ".")
    state["diff_ok"] = res.ok
    state["diff_text"] = res.output
    state["diff_error"] = res.error
    if res.ok:
        state["codex_prompt"] = build_review_prompt(res.output)
    return state
