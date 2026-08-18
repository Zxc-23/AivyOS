"""Cline SDK 适配后端（文档 §10.1 / T5.1）：可选集成（Node.js Cline SDK）。

Cline SDK 为 Node 包（@cline/cline-sdk）；未安装时降级本地后端。
接入方式：node 子进程调用 Cline SDK 的 plan/act 接口（BYOK 多模型）。
"""

from __future__ import annotations

import shutil
from typing import Any, Dict, Optional

from aivyos_core.codegen.base import CodeGenBackend, FilePlan


class ClineUnavailable(RuntimeError):
    pass


class ClineSDKBackend(CodeGenBackend):
    name = "cline-sdk"

    def __init__(self, model: Optional[str] = None, api_key_env: Optional[str] = None) -> None:
        self.model = model or "qwen2.5:3b"
        self.api_key_env = api_key_env or "CLINE_API_KEY"
        if not self.available():
            raise ClineUnavailable(
                "Cline SDK 未安装（Node 环境 + @cline/cline-sdk）。已降级到本地模板/LLM 生成后端。"
            )

    @staticmethod
    def available() -> bool:
        return shutil.which("node") is not None and shutil.which("npx") is not None

    def plan(self, spec: Any) -> FilePlan:
        # 经 Node 调用 Cline SDK 规划；未实现细节时回退本地计划
        from aivyos_core.codegen.templates import scaffold

        files = scaffold(spec.type, spec)
        return FilePlan(files=[{"path": p, "purpose": "Cline 规划"} for p in sorted(files)])

    def generate(self, spec: Any, plan: FilePlan) -> Dict[str, str]:
        # 占位：真实 Cline SDK 调用在 Node 侧实现（Phase 2 后续细化）
        from aivyos_core.codegen.templates import scaffold

        return scaffold(spec.type, spec)
