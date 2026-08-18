# -*- coding: utf-8 -*-
"""冒烟：一句话做软件（§10 全链路）+ 真实 LLM 增强 + 预览验证。"""
import asyncio
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 仓库根入 path

from aivyos_core.codegen import CodeGenService
from aivyos_core.codegen.preview import PreviewController
from aivyos_core.config import load_config
from aivyos_core.llm.router import ModelRouter

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".aivyos_workspace", "smoke_gen")
shutil.rmtree(WS, ignore_errors=True)
os.makedirs(WS, exist_ok=True)

cfg = load_config()
router = ModelRouter(cfg["llm"])
print("LLM 本地可用:", router._local_available())

svc = CodeGenService(parser=__import__("aivyos_core.requirement", fromlist=["RequirementParser"]).RequirementParser(router=router))

async def main():
    # 1) 规则解析 + 模板生成
    spec = svc.parser.parse("做一个待办事项管理的命令行工具")
    plan = svc.plan(spec)
    files = svc.generate(spec, plan)
    print(f"[规则] type={spec.type} title={spec.title} files={list(files)}")

    # 2) 真实 LLM 增强解析（Ollama 在线时）
    spec2 = await svc.parser.parse_enhanced("做一个每日天气查询的网页应用，支持城市搜索")
    print(f"[增强] type={spec2.type} title={spec2.title} features={spec2.features} source={spec2.source}")

    # 3) 交付到工作区
    d = await svc.deliver(files, __import__("pathlib").Path(WS))
    print(f"[交付] {d['count']} 个文件 via {d['via']} → {WS}")

    # 4) 预览 + 截图（mock 回退）
    ctl = PreviewController()
    url = ctl.start(WS, spec.type)
    print("[预览]", url)
    shot = await ctl.capture_viewport(url, "desktop")
    print("[截图]", shot["backend"], shot["viewport"])
    ctl.stop()
    print("SMOKE_OK")

asyncio.run(main())
