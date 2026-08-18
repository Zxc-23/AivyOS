# -*- coding: utf-8 -*-
"""冒烟：一句话做软件（§10 全链路）+ 端到端 Vibe Coding（§11 预览验证回环）。"""
import asyncio
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 仓库根入 path

from aivyos_core.codegen import CodeGenService
from aivyos_core.codegen.preview import PreviewController
from aivyos_core.config import load_config
from aivyos_core.llm.router import ModelRouter
from aivyos_core.mcp.servers.browser import BrowserServer
from aivyos_core.workflow.checkpointer import SqliteCheckpointer
from aivyos_core.workflow.workflows import build_vibe_coding_graph, stop_preview_server

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".aivyos_workspace", "smoke_gen")
MEM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".aivyos_workspace", "smoke_mem")
for p in (WS, MEM):
    shutil.rmtree(p, ignore_errors=True)
os.makedirs(WS, exist_ok=True)

cfg = load_config()
router = ModelRouter(cfg["llm"])
print("LLM 本地可用:", router._local_available())

svc = CodeGenService(parser=__import__("aivyos_core.requirement", fromlist=["RequirementParser"]).RequirementParser(router=router))


async def main():
    # 1) 规则解析 + 模板生成 + 交付
    spec = svc.parser.parse("做一个待办事项管理的命令行工具")
    plan = svc.plan(spec)
    files = svc.generate(spec, plan)
    print(f"[规则] type={spec.type} title={spec.title} files={list(files)}")

    # 2) 真实 LLM 增强解析（Ollama 在线时）
    spec2 = await svc.parser.parse_enhanced("做一个每日天气查询的网页应用，支持城市搜索")
    print(f"[增强] type={spec2.type} title={spec2.title} features={spec2.features[:2]}... source={spec2.source}")

    d = await svc.deliver(files, __import__("pathlib").Path(WS))
    print(f"[交付] {d['count']} 个文件 via {d['via']}")

    # 3) 端到端 Vibe Coding 工作流（§7.4：解析→规划→生成→交付→构建→预览→监控→记忆）
    ck = SqliteCheckpointer(os.path.join(WS, "..", "ck_smoke.db"))
    app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
    ctx = {
        "executor": "local",
        "workspace": WS,
        "codegen": svc,
        "preview_controller": PreviewController(browser_server=BrowserServer()),
        "build_command": None,
        "preview": True,
        "memfs": __import__("aivyos_core.memfs", fromlist=["MemFS"]).MemFS(MEM),
    }
    state = await app.invoke({"user_request": "做一个静态个人主页"}, thread_id="wf_smoke", ctx=ctx)
    print("[工作流] trace:", app.last_trace)
    print("[工作流] spec:", state.get("spec", {}).get("type"), "| build_ok:", not state.get("build_failed"), "| preview_ok:", state.get("preview_ok"))
    print("[工作流] 预览:", state.get("preview_url"), "| 监控:", state.get("preview_monitor", {}).get("backend"), "| 视觉:", state.get("preview_visual", {}).get("verdict"))
    stop_preview_server(state)

    # 4) dev server 生命周期管理
    ctl = PreviewController()
    url = ctl.start(WS, "static-site")
    print("[预览]", url, "| servers:", len(ctl.list_servers()))
    ctl.stop()
    print("SMOKE_OK")


asyncio.run(main())
