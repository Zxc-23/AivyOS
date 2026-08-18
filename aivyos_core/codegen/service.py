"""代码生成服务（§10.1 / T5.1-T5.4）：解析→规划→生成→交付 全流程编排。

- parse：需求解析（规则 + LLM 可选）
- generate：后端生成（本地模板 / Cline 可选）
- deliver：写入工作区（直接写；可选经 MCP filesystem Server，§5.1.2）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from aivyos_core.codegen.base import CodeGenBackend
from aivyos_core.codegen.cline_adapter import ClineSDKBackend, ClineUnavailable
from aivyos_core.codegen.local_backend import LocalCodeGen
from aivyos_core.requirement import ProjectSpec, RequirementParser

log = logging.getLogger(__name__)


class CodeGenService:
    def __init__(
        self,
        parser: Optional[RequirementParser] = None,
        backend: Optional[CodeGenBackend] = None,
        fs_tool=None,  # 可选 MCP filesystem 工具（fs_write handler）
    ) -> None:
        self.parser = parser or RequirementParser()
        self.backend = backend or LocalCodeGen()
        self.fs_tool = fs_tool

    # ---- 解析（§10.1 阶段1）----

    async def parse(self, text: str, enhanced: bool = True) -> ProjectSpec:
        if enhanced:
            return await self.parser.parse_enhanced(text)
        return self.parser.parse(text)

    # ---- 规划 + 生成（阶段2-4）----

    def plan(self, spec: ProjectSpec):
        return self.backend.plan(spec)

    def generate(self, spec: ProjectSpec, plan=None) -> Dict[str, str]:
        return self.backend.generate(spec, plan)

    # ---- 交付（§10.1 阶段5 / T5.4）----

    async def deliver(self, files: Dict[str, str], workspace: Path) -> Dict[str, Any]:
        """写入工作区（经 MCP fs_write 或直接写）。返回统计。"""
        written: List[str] = []
        if self.fs_tool is not None:
            for path, content in files.items():
                r = await self.fs_tool({"path": path, "content": content})
                if r.ok:
                    written.append(path)
            return {"via": "mcp-filesystem", "written": written, "count": len(written)}
        for path, content in files.items():
            p = workspace / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            written.append(path)
        return {"via": "direct", "workspace": str(workspace), "written": written, "count": len(written)}

    # ---- 一句话做软件（§10 全流程）----

    async def one_shot(self, text: str, workspace: Path) -> Dict[str, Any]:
        """需求 → 解析 → 规划 → 生成 → 交付（阶段1-5）。"""
        spec = await self.parse(text)
        plan = self.plan(spec)
        files = self.generate(spec, plan)
        delivered = await self.deliver(files, workspace)
        return {
            "spec": spec.to_dict(),
            "plan": [f["path"] for f in plan.files],
            "files": list(files.keys()),
            "delivery": delivered,
        }


def create_codegen(cfg: dict, router=None, fs_tool=None) -> CodeGenService:
    """按配置构建：backend=auto|local|cline；fs_tool 传 MCP filesystem 写工具。"""
    cg_cfg = cfg.get("codegen", {})
    backend_name = cg_cfg.get("backend", "auto")
    backend: CodeGenBackend
    if backend_name in ("cline", "auto"):
        try:
            backend = ClineSDKBackend(model=cg_cfg.get("model"))
        except ClineUnavailable:
            if backend_name == "cline":
                log.warning("Cline SDK 不可用，降级本地后端")
            backend = LocalCodeGen(router=router, llm_enhance=bool(cg_cfg.get("llm_enhance", False)))
    else:
        backend = LocalCodeGen(router=router, llm_enhance=bool(cg_cfg.get("llm_enhance", False)))
    return CodeGenService(
        parser=RequirementParser(router=router),
        backend=backend,
        fs_tool=fs_tool,
    )
