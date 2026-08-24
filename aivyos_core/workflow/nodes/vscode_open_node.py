"""VS Code 打开工作流节点（§4.2.1）：打开 state["vscode_path"]，可优雅跳过。"""

from __future__ import annotations

from typing import Any, Dict


async def vscode_open_node(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    path = state.get("vscode_path") or ""
    if not path:
        state.update(vscode_ok=False, vscode_error="未指定 vscode_path，跳过")
        return state
    svc = ctx.get("workbench")
    if svc is None:
        state.update(vscode_ok=False, vscode_error="ctx 缺少 workbench 服务")
        return state
    res = await svc.open_vscode(path)
    state["vscode_ok"] = res.ok
    state["vscode_error"] = res.error  # code 不在 PATH 时这里是降级提示，不算流程失败
    return state
