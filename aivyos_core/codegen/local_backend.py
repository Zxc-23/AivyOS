"""本地代码生成后端（T5.1 零依赖）：模板骨架 + LLM 可选增强。

- plan：按模板输出文件树
- generate：模板生成真实文件内容；llm_enhance 时对主要文件用 LLM 重写（可选）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from aivyos_core.codegen.base import CodeGenBackend, FilePlan
from aivyos_core.codegen.templates import scaffold

log = logging.getLogger(__name__)


class LocalCodeGen(CodeGenBackend):
    name = "local-template"

    def __init__(self, router=None, llm_enhance: bool = False) -> None:
        self.router = router
        self.llm_enhance = llm_enhance

    def plan(self, spec: Any) -> FilePlan:
        files = scaffold(spec.type, spec)
        return FilePlan(
            files=[
                {"path": p, "purpose": "脚手架文件（" + spec.type + "）"}
                for p in sorted(files.keys())
            ]
        )

    def generate(self, spec: Any, plan: FilePlan) -> Dict[str, str]:
        files = scaffold(spec.type, spec)
        if self.llm_enhance and self.router is not None:
            files = self._enhance_with_llm(spec, files)
        return files

    def _enhance_with_llm(self, spec: Any, files: Dict[str, str]) -> Dict[str, str]:
        """对入口文件用真实 LLM 按特性重写（§10.1 阶段3 增强；失败回退模板）。"""
        try:
            if not (self.router._local_available() or bool(self.router._cloud_api_key())):
                return files
            import asyncio

            entry = self._entry_file(spec.type)
            if entry not in files:
                return files
            prompt = (
                f"为项目「{spec.title}」（{spec.type}）重写入口文件 {entry}，"
                f"实现以下特性：{'、'.join(spec.features[:4]) or '基本功能'}。"
                "直接输出文件完整内容，不要解释。当前模板：\n" + files[entry][:500]
            )
            from aivyos_core.models import LLMRequest, RouteDecision, RouteMode

            decision = RouteDecision(
                mode=RouteMode.LOCAL if self.router._local_available() else RouteMode.CLOUD,
                model=self.router.cfg["local"]["model"] if self.router._local_available() else self.router.cfg["cloud"]["model"],
                reason="代码生成",
            )
            request = LLMRequest(messages=[{"role": "system", "content": prompt}], model=decision.model, max_tokens=800)
            resp = asyncio.run(self.router.complete(request, decision))
            if "mock" not in resp.model.lower() and resp.text.strip():
                files[entry] = resp.text
        except Exception as e:
            log.warning("LLM 增强失败，保留模板: %s", e)
        return files

    @staticmethod
    def _entry_file(project_type: str) -> str:
        return {
            "static-site": "index.html",
            "react-web-app": "src/App.jsx",
            "vue-web-app": "src/App.vue",
            "nextjs-app": "pages/index.js",
            "python-cli": "main.py",
            "python-api": "main.py",
            "tauri-desktop-app": "src/App.jsx",
        }.get(project_type, "index.html")
