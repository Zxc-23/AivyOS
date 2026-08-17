"""预置工作流（文档 §4.5.2 / §7.4 VibeCoding 状态图；§10 一句话做软件）。

两种执行器（ctx.executor）：
- demo：节点产出明确标注的 mock 结果（默认，零依赖演示/测试）
- local：真实本地执行 —— 生成可用代码骨架、写入工作区文件、
  运行构建命令（subprocess）、启动本地 HTTP 预览服务器

构建失败回环（§10.1 阶段 6）：build 失败 → generate（≤MAX_BUILD_RETRIES 次）
→ 仍失败则 give_up 终止（不会无限循环，也不会假成功）。
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any, Dict, Optional
from pathlib import Path

from aivyos_core.workflow.checkpointer import SqliteCheckpointer
from aivyos_core.workflow.mini_graph import END, StateGraph, WorkflowError

log = logging.getLogger(__name__)

MAX_BUILD_RETRIES = 2  # 构建失败回环上限（§10.1 阶段 6 修复）

# ---- VibeCoding 节点（§4.5.2 VibeCodingState）----

DEMO_FILES = {
    "index.html": "<!-- demo: Cline Act 模式占位 -->\n<title>AivyOS</title>",
    "style.css": "/* demo */",
    "script.js": "// demo",
}


def _real_skeleton(title: str) -> Dict[str, str]:
    """local 执行器：生成可用的最小网页骨架（真实文件）。"""
    return {
        "index.html": f"<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>{title}</title>\n  <link rel=\"stylesheet\" href=\"style.css\">\n</head>\n<body>\n  <h1>{title}</h1>\n  <main id=\"app\"></main>\n  <script src=\"script.js\"></script>\n</body>\n</html>\n",
        "style.css": "body { font-family: system-ui; margin: 2rem; color: #222; }\nh1 { color: #3b82f6; }\n",
        "script.js": "// AivyOS 生成骨架\nconsole.log('AivyOS workspace ready');\n",
    }


async def _understand(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    request = state.get("user_request", "")
    state["spec"] = {"type": "web_app", "title": request[:40], "source": ctx.get("executor", "demo")}
    state["note_understand"] = f"已解析需求: {request[:40]}"
    return state


async def _plan(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    state["plan"] = [
        {"file": "index.html", "role": "页面结构"},
        {"file": "style.css", "role": "样式"},
        {"file": "script.js", "role": "逻辑"},
    ]
    state["note_plan"] = "已规划文件树" + ("（Cline Plan 模式适配待 Phase 2）" if ctx.get("executor") == "local" else "（Cline Plan 模式占位）")
    return state


async def _generate(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    state["files"] = _real_skeleton(state.get("user_request", "AivyOS App")) if ctx.get("executor") == "local" else dict(DEMO_FILES)
    state.setdefault("retry_count", 0)
    state["note_generate"] = f"已生成代码（第 {state['retry_count']} 轮，{ctx.get('executor', 'demo')} 执行器）"
    return state


async def _deliver(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    workspace = ctx.get("workspace")
    if ctx.get("executor") == "local" and workspace is not None:
        ws = Path(workspace)
        ws.mkdir(parents=True, exist_ok=True)
        for name, content in (state.get("files") or {}).items():
            (ws / name).write_text(content, encoding="utf-8")
        state["delivered_to"] = str(ws)
        state["note_deliver"] = f"已写入工作区 {ws}"
    else:
        state["delivered_to"] = "workspace_demo/" + (state.get("user_request", "app")[:20])
        state["note_deliver"] = "已写入 IDE（MCP filesystem 占位）"
    return state


async def _build(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.get("executor") == "local" and ctx.get("build_command"):
        ws = Path(ctx["workspace"]) if ctx.get("workspace") else Path(".")
        try:
            proc = subprocess.run(
                ctx["build_command"], shell=True, cwd=ws,
                capture_output=True, text=True, timeout=60,
            )
            failed = proc.returncode != 0
            error = (proc.stderr or proc.stdout or "").strip()[-300:]
        except subprocess.TimeoutExpired:
            failed, error = True, "构建超时"
        except Exception as e:
            failed, error = True, f"构建异常: {e}"
        if failed:
            state["retry_count"] = state.get("retry_count", 0) + 1
            state["build_failed"] = True
            state["errors"] = [f"构建错误 #{state['retry_count']}: {error}"]
        else:
            state["build_failed"] = False
            state["errors"] = []
        state["note_build"] = "构建失败 → 回环 generate" if state["build_failed"] else "构建通过"
        return state

    # demo 执行器
    request = state.get("user_request", "").lower()
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
    workspace = ctx.get("workspace")
    if ctx.get("executor") == "local" and ctx.get("preview", True) and workspace is not None:
        srv, port = _start_preview_server(Path(workspace))
        state["preview_url"] = f"http://127.0.0.1:{port}/"
        state["_preview_server"] = srv
        state["preview_ok"] = True
        state["note_preview"] = f"本地预览已启动: {state['preview_url']}"
    else:
        state["preview_url"] = "http://127.0.0.1:8080/preview"
        state["preview_ok"] = True
        state["note_preview"] = "已打开预览（browser-use 占位）"
    return state


async def _save_memory(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    memfs = ctx.get("memfs")
    if memfs is not None:
        memfs.remember(f"完成项目: {state.get('user_request', '')[:40]}", category="tasks.md")
    state["note_save"] = "已保存项目记忆（Mem0/MemFS 通道）"
    return state


def _build_condition(state: Dict[str, Any]) -> str:
    if not state.get("build_failed"):
        return "ok"
    if state.get("retry_count", 0) < MAX_BUILD_RETRIES:
        return "retry"
    return "give_up"


def build_vibe_coding_graph(checkpointer: Optional[SqliteCheckpointer] = None) -> StateGraph:
    """§4.5.2 / §7.4 VibeCoding 状态图：understand→plan→generate→deliver→build→(retry?generate|ok:preview|give_up:END)→save_memory→END。"""
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
    g.add_conditional_edges("build", _build_condition, {"retry": "generate", "ok": "preview", "give_up": END})
    g.add_edge("preview", "save_memory")
    g.add_edge("save_memory", END)
    return g


def _start_preview_server(workspace: Path):
    """启动本地 HTTP 预览服务器（§7.4 自动预览），返回 (server, port)。"""
    import functools
    import http.server
    import threading

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(workspace))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def stop_preview_server(state: Dict[str, Any]) -> None:
    """停止预览服务器（工作流结束后清理）。"""
    srv = state.pop("_preview_server", None)
    if srv is not None:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass


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
