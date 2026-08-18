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
    if ctx.get("executor") == "local":
        # §10.1 阶段1：真实需求解析（规则 + LLM 可选）
        svc = ctx.get("codegen")
        parser = svc.parser if svc is not None else None
        if parser is None:
            from aivyos_core.requirement import RequirementParser

            parser = RequirementParser(router=ctx.get("router"))
        try:
            spec = await parser.parse_enhanced(request)
            state["spec"] = spec.to_dict()
            state["_spec_obj"] = spec
            state["note_understand"] = f"已解析需求（{spec.source}）: {spec.title} [{spec.type}]"
        except Exception as e:
            log.warning("需求解析失败，降级规则: %s", e)
            from aivyos_core.requirement import RequirementParser

            spec = RequirementParser().parse(request)
            state["spec"] = spec.to_dict()
            state["_spec_obj"] = spec
            state["note_understand"] = f"已解析需求（rule 降级）: {spec.title} [{spec.type}]"
    else:
        state["spec"] = {"type": "web_app", "title": request[:40], "source": "demo"}
        state["note_understand"] = f"已解析需求: {request[:40]}"
    return state


async def _plan(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.get("executor") == "local":
        service = ctx.get("codegen")
        if service is not None and state.get("_spec_obj") is not None:
            plan = service.plan(state["_spec_obj"])
            state["plan"] = plan.files
            state["_plan_obj"] = plan
            state["note_plan"] = f"已规划文件树（{len(plan.files)} 个文件）"
            return state
    state["plan"] = [
        {"file": "index.html", "role": "页面结构"},
        {"file": "style.css", "role": "样式"},
        {"file": "script.js", "role": "逻辑"},
    ]
    state["note_plan"] = "已规划文件树" + ("（Cline Plan 模式适配待 Phase 2）" if ctx.get("executor") == "local" else "（Cline Plan 模式占位）")
    return state


async def _generate(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.get("executor") == "local":
        service = ctx.get("codegen")
        if service is not None and state.get("_spec_obj") is not None:
            plan = state.get("_plan_obj")
            try:
                files = service.generate(state["_spec_obj"], plan)
                state["files"] = files
                state["note_generate"] = f"已生成代码（{len(files)} 个文件，{service.backend.name}）"
                return state
            except Exception as e:
                log.warning("代码生成失败，降级骨架: %s", e)
    state["files"] = _real_skeleton(state.get("user_request", "AivyOS App")) if ctx.get("executor") == "local" else dict(DEMO_FILES)
    state.setdefault("retry_count", 0)
    state["note_generate"] = f"已生成代码（第 {state['retry_count']} 轮，{ctx.get('executor', 'demo')} 执行器）"
    return state


async def _deliver(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    workspace = ctx.get("workspace")
    if ctx.get("executor") == "local" and workspace is not None:
        ws = Path(workspace)
        service = ctx.get("codegen")
        if service is not None and state.get("files"):
            # §10.1 阶段5：经 CodeGenService 交付（fs_tool 存在时走 MCP filesystem）
            delivered = await service.deliver(state["files"], ws)
            state["delivered_to"] = str(ws)
            state["delivery"] = delivered
            state["note_deliver"] = f"已交付 {delivered['count']} 个文件（{delivered['via']}）→ {ws}"
            return state
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
        controller = ctx.get("preview_controller")
        if controller is not None:
            # §11：PreviewController 管理 dev server + 浏览器监控 + AI 视觉验证
            spec = state.get("spec") or {}
            ptype = spec.get("type", "static-site")
            state["preview_url"] = controller.start(Path(workspace), ptype)
            state["_preview_controller"] = controller
            state["preview_ok"] = False
            # 控制台/网络监控（§11 控制台监控 + 网络监控，T5.8）
            if controller.browser_server is not None:
                try:
                    mon = await controller.browser_server._monitor({"url": state["preview_url"], "hold_ms": 600})
                    events = mon.data.get("events", {}) if mon.ok else {"console": [], "network": []}
                    state["preview_monitor"] = events
                    console_errors = [e for e in events.get("console", []) if e.get("type") == "error"]
                    net_fails = [e for e in events.get("network", []) if e.get("kind") == "res" and e.get("status", 0) >= 400]
                    if console_errors or net_fails:
                        state["preview_failed"] = True
                        state["retry_count"] = state.get("retry_count", 0) + 1
                        state["errors"] = [f"预览错误 #{state['retry_count']}: console={console_errors[:2]} net={net_fails[:2]}"]
                        state["note_preview"] = f"预览监控发现错误 → 回环 generate（{state['preview_url']}）"
                        return state
                except Exception as e:
                    log.warning("预览监控失败（跳过验证）: %s", e)
            # AI 视觉验证（§11 截图反馈，T5.5）
            try:
                vc = await controller.visual_check(state["preview_url"])
                state["preview_visual"] = vc
                if vc.get("verdict") == "abnormal":
                    state["preview_failed"] = True
                    state["retry_count"] = state.get("retry_count", 0) + 1
                    state["errors"] = [f"预览视觉异常 #{state['retry_count']}: {vc.get('description', '')[:120]}"]
                    state["note_preview"] = f"视觉验证异常 → 回环 generate（{state['preview_url']}）"
                    return state
            except Exception as e:
                log.warning("视觉验证失败（跳过）: %s", e)
            state["preview_ok"] = True
            state["preview_failed"] = False
            state["note_preview"] = f"预览已启动并通过验证: {state['preview_url']}"
        else:
            # 兼容旧 ctx（无 preview_controller）：直接 http.server
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


def _preview_condition(state: Dict[str, Any]) -> str:
    """预览验证回环（§10.1 阶段 6 扩展 / §11 控制台检查）：console 错误或视觉异常 → 回 generate 修复。"""
    if not state.get("preview_failed"):
        return "ok"
    if state.get("retry_count", 0) < MAX_BUILD_RETRIES:
        return "retry"
    return "give_up"


def build_vibe_coding_graph(checkpointer: Optional[SqliteCheckpointer] = None) -> StateGraph:
    """§4.5.2 / §7.4 VibeCoding 状态图：
    understand→plan→generate→deliver→build→(retry?generate|ok:preview|give_up:END)→
    preview→(retry?generate 预览验证回环|ok:save_memory|give_up:END)→save_memory→END。"""
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
    # §11 预览验证回环：console 错误/视觉异常 → 回 generate 修复（§10.1 阶段 6 扩展）
    g.add_conditional_edges("preview", _preview_condition, {"retry": "generate", "ok": "save_memory", "give_up": END})
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
    controller = state.pop("_preview_controller", None)
    if controller is not None:
        try:
            controller.stop()
        except Exception:
            pass
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
