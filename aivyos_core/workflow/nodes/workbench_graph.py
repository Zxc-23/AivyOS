"""Workbench 协同工作流图（§4.2.1）：claude → codex 审查 → vscode 打开。

复用 mini_graph + SqliteCheckpointer，支持断点续传：
任一节点失败即沿条件边到 END，checkpoint 已保存，可用 resume(thread_id) 续跑。

用法：
    graph = build_workbench_graph(checkpointer=SqliteCheckpointer(path))
    state = await graph.invoke({"user_request": "..."}, thread_id="t1",
                               ctx={"workbench": workbench_service})
"""

from __future__ import annotations

from typing import Optional

from aivyos_core.workflow.checkpointer import SqliteCheckpointer
from aivyos_core.workflow.mini_graph import END, CompiledGraph, StateGraph
from aivyos_core.workflow.nodes.claude_node import claude_node
from aivyos_core.workflow.nodes.codex_node import codex_node
from aivyos_core.workflow.nodes.diff_capture_node import diff_capture_node
from aivyos_core.workflow.nodes.vscode_open_node import vscode_open_node

STATE_DEFAULTS = {
    "user_request": "",
    "cwd": "",
    "claude_ok": False, "claude_output": "", "claude_error": "",
    "codex_prompt": "",
    "codex_ok": False, "codex_output": "", "codex_error": "",
    "diff_ok": False, "diff_text": "", "diff_error": "",
    "vscode_path": "", "vscode_ok": False, "vscode_error": "",
}


def build_workbench_graph(checkpointer: Optional[SqliteCheckpointer] = None) -> CompiledGraph:
    """串行协同：Claude 实现 → Codex 审查 → VS Code 打开（后者可跳过）。"""
    g = StateGraph(dict(STATE_DEFAULTS))
    g.add_node("claude", claude_node)
    g.add_node("codex_review", codex_node)
    g.add_node("open_vscode", vscode_open_node)
    g.set_entry_point("claude")
    g.add_conditional_edges(
        "claude", lambda s: "ok" if s.get("claude_ok") else "fail",
        {"ok": "codex_review", "fail": END},
    )
    g.add_conditional_edges(
        "codex_review", lambda s: "ok" if s.get("codex_ok") else "fail",
        {"ok": "open_vscode", "fail": END},
    )
    g.add_edge("open_vscode", END)
    return g.compile(checkpointer=checkpointer)


def build_diff_review_graph(checkpointer: Optional[SqliteCheckpointer] = None) -> CompiledGraph:
    """人工确认闭环：捕获 git diff → Codex 审查（§3.3）。"""
    g = StateGraph(dict(STATE_DEFAULTS))
    g.add_node("diff_capture", diff_capture_node)
    g.add_node("codex_review", codex_node)
    g.set_entry_point("diff_capture")
    g.add_conditional_edges(
        "diff_capture", lambda s: "ok" if s.get("diff_ok") else "fail",
        {"ok": "codex_review", "fail": END},
    )
    g.add_edge("codex_review", END)
    return g.compile(checkpointer=checkpointer)
