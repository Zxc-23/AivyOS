"""预置工作流（文档 §4.5.2 / §7.4 VibeCoding 状态图；§10 一句话做软件）。

节点在演示模式（未接入 Cline/MCP）下产出明确标注的 mock 结果；
LangGraph 语义由 mini_graph 提供：检查点、条件边回环（build 失败 → generate）、续传。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from aivyos_core.workflow.checkpointer import SqliteCheckpointer
from aivyos_core.workflow.mini_graph import END, StateGraph, WorkflowError

log = logging.getLogger(__name__)

MAX_BUILD_RETRIES = 2  # 构建失败回环上限（§10.1 阶段 6 修复）

# ---- VibeCoding 节点（§4.5.2 VibeCodingState）----


async def _understand(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    request = state.get("user_request", "")
    state["spec"] = {"type": "web_app", "title": request[:40], "source": "demo"}
    state["note_understand"] = f"已解析需求: {request[:40]}"
    return state


async def _plan(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    state["plan"] = [
        {"file": "index.html", "role": "页面结构"},
        {"file": "style.css", "role": "样式"},
        {"file": "script.js", "role": "逻辑"},
    ]
    state["note_plan"] = "已规划文件树（Cline Plan 模式占位）"
    return state


async def _generate(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    state["files"] = {
        "index.html": "<!-- demo: Cline Act 模式占位 -->\n<title>AivyOS</title>",
        "style.css": "/* demo */",
        "script.js": "// demo",
    }
    state.setdefault("retry_count", 0)
    state["note_generate"] = f"已生成代码（第 {state['retry_count']} 轮）"
    return state


async def _deliver(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    state["delivered_to"] = "workspace_demo/weather_app"
    state["note_deliver"] = "已写入 IDE（MCP filesystem 占位）"
    return state


async def _build(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    request = state.get("user_request", "").lower()
    # 演示/测试：请求含"失败"或环境变量强制时构建失败，触发回环
    fail = ("失败" in request or "fail" in request) and state.get("retry_count", 0) < MAX_BUILD_RETRIES
    if fail:
        state["build_failed"] = True
        state["retry_count"] = state.get("retry_count", 0) + 1
        state["errors"] = [f"构建错误 #{state['retry_count']}（demo）"]
    else:
        state["build_failed"] = False
        state["errors"] = []
    state["note_build"] = "构建失败 → 回环 generate" if state["build_failed"] else "构建通过"
    return state


async def _preview(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    state["preview_url"] = "http://127.0.0.1:8080/preview"
    state["preview_ok"] = True
    state["note_preview"] = "已打开预览（browser-use 占位）"
    return state


async def _save_memory(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    memfs = ctx.get("memfs")
    if memfs is not None:
        memfs.remember(f"完成项目: {state.get('user_request', '')[:40]}", category="tasks.md")
    state["note_save"] = "已保存项目记忆（Mem0/MemFS 占位）"
    return state


def _build_condition(state: Dict[str, Any]) -> str:
    return "retry" if state.get("build_failed") else "ok"


def build_vibe_coding_graph(checkpointer: Optional[SqliteCheckpointer] = None) -> StateGraph:
    """§4.5.2 / §7.4 VibeCoding 状态图：understand→plan→generate→deliver→build→(retry?generate|preview)→save_memory→END。"""
    g = StateGraph({"user_request": "", "retry_count": 0})
    g.add_node("understand", _understand)
    g.add_node("plan", _plan)
    g.add_node("generate", _generate)
    g.add_node("deliver", _deliver)
    g.add_node("build", _build)
    g.add_node("preview", _preview)
    g.add_node("save_memory", _save_memory)
    g.set_entry_point("understand")
    g.add_edge("understand", "plan")
    g.add_edge("plan", "generate")
    g.add_edge("generate", "deliver")
    g.add_edge("deliver", "build")
    g.add_conditional_edges("build", _build_condition, {"retry": "generate", "ok": "preview"})
    g.add_edge("preview", "save_memory")
    g.add_edge("save_memory", END)
    return g


# ---- ChatFlow：对话工作流（集成 ChatEngine，检查点化）----


def build_chat_flow_graph(checkpointer: Optional[SqliteCheckpointer] = None) -> StateGraph:
    """对话工作流：route → respond（ChatEngine）→ save_memory（MemFS）。"""

    async def route(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        engine = ctx["engine"]
        decision = engine.router.route(state["text"])
        state["route"] = decision.to_dict()
        return state

    async def respond(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        engine = ctx["engine"]
        reply = await engine.send(state["text"], session_id=state.get("session_id"))
        state["reply"] = reply.text
        state["session_id"] = reply.session_id
        state["model"] = reply.model
        return state

    async def save_memory(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        memfs = ctx.get("memfs")
        if memfs is not None:
            memfs.remember(f"对话: {state.get('text', '')[:40]} → {state.get('reply', '')[:40]}", category="facts.md")
        state["memory_saved"] = True
        return state

    g = StateGraph({"text": "", "session_id": None})
    g.add_node("route", route)
    g.add_node("respond", respond)
    g.add_node("save_memory", save_memory)
    g.set_entry_point("route")
    g.add_edge("route", "respond")
    g.add_edge("respond", "save_memory")
    g.add_edge("save_memory", END)
    return g
