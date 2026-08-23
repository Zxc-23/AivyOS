"""WorkbenchService：双模型协同统一入口。

链路：cc-switch 读取（优先）→ 手动配置降级 → dispatcher 子进程 → 内存态结果。
机密只进子进程 env；last_claude_result 仅内存持有（供 /review），不落盘。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from aivyos_core.workbench.cc_switch.reader import CCSwitchReader
from aivyos_core.workbench.dispatchers.claude_code import ClaudeCodeDispatcher
from aivyos_core.workbench.dispatchers.codex import CodexDispatcher
from aivyos_core.workbench.dispatchers.vscode import VSCodeDispatcher
from aivyos_core.workbench.models import AgentResult, AgentTask, ProviderEnv

_REVIEW_MAX = 8000  # 发给 codex 审查的 Claude 输出截断长度


class WorkbenchService:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        wb = cfg.get("workbench", {})
        self.cfg = wb
        self.timeout_s = float(wb.get("timeout_s", 300))
        ccs = wb.get("cc_switch", {})
        self.cc_switch_enabled = bool(ccs.get("enabled", True))
        self.reader = CCSwitchReader(Path(ccs["db_path"]).expanduser() if ccs.get("db_path") else None)
        agents = wb.get("agents", {})
        claude_cfg = agents.get("claude_code", {})
        codex_cfg = agents.get("codex", {})
        self.agent_enabled = {
            "claude": bool(claude_cfg.get("enabled", True)),
            "codex": bool(codex_cfg.get("enabled", True)),
        }
        self.manual = {
            "claude": claude_cfg.get("manual", {}),
            "codex": codex_cfg.get("manual", {}),
        }
        self.claude = ClaudeCodeDispatcher(cli_path=claude_cfg.get("cli_path", "claude"))
        self.codex = CodexDispatcher(cli_path=codex_cfg.get("cli_path", "codex"))
        self.vscode = VSCodeDispatcher()
        collab = wb.get("collaboration", {})
        self.auto_open_vscode = bool(collab.get("auto_open_vscode", True))
        self.last_claude_result: Optional[AgentResult] = None  # 仅内存，供 review 使用
        self.last_notice: str = ""

    # ------------------------------------------------------------------
    # 凭据解析：cc-switch 优先，手动配置降级
    # ------------------------------------------------------------------
    def _resolve_env(self, app_type: str) -> Tuple[Optional[ProviderEnv], str]:
        if self.cc_switch_enabled:
            penv = self.reader.read_provider(app_type)
            if penv is not None:
                return penv, ""
        manual = self.manual.get(app_type, {})
        if manual.get("api_key"):
            env: Dict[str, str] = {}
            if app_type == "claude":
                env["ANTHROPIC_AUTH_TOKEN"] = str(manual["api_key"])
                if manual.get("base_url"):
                    env["ANTHROPIC_BASE_URL"] = str(manual["base_url"])
                if manual.get("model"):
                    env["ANTHROPIC_MODEL"] = str(manual["model"])
            else:
                env["OPENAI_API_KEY"] = str(manual["api_key"])
                if manual.get("base_url"):
                    env["OPENAI_BASE_URL"] = str(manual["base_url"])
            return (
                ProviderEnv(app_type=app_type, name="手动配置", env=env, source="aivyos-config"),
                "未检测到 cc-switch 可用配置，已使用 AivyOS 手动配置",
            )
        section = "claude_code" if app_type == "claude" else app_type
        return None, (
            f"未检测到 cc-switch 的 {app_type} provider，且未配置 "
            f"workbench.agents.{section}.manual 手动凭据"
        )

    # ------------------------------------------------------------------
    # 运行入口
    # ------------------------------------------------------------------
    async def run_claude(self, prompt: str, cwd: Optional[str] = None,
                         timeout_s: Optional[float] = None) -> AgentResult:
        if not self.agent_enabled["claude"]:
            return AgentResult(agent="claude", error="claude_code agent 已禁用（workbench.agents.claude_code.enabled=false）")
        penv, notice = self._resolve_env("claude")
        self.last_notice = notice
        if penv is None:
            return AgentResult(agent="claude", error=notice)
        task = AgentTask(agent="claude", prompt=prompt, cwd=cwd,
                         timeout_s=timeout_s or self.timeout_s)
        result = await self.claude.run(task, penv)
        if result.ok:
            self.last_claude_result = result
            if self.auto_open_vscode and result.output_files:
                await self.open_vscode(result.output_files[0])
        return result

    async def run_codex(self, prompt: str, cwd: Optional[str] = None,
                        timeout_s: Optional[float] = None) -> AgentResult:
        if not self.agent_enabled["codex"]:
            return AgentResult(agent="codex", error="codex agent 已禁用（workbench.agents.codex.enabled=false）")
        penv, notice = self._resolve_env("codex")
        self.last_notice = notice
        if penv is None:
            return AgentResult(agent="codex", error=notice)
        task = AgentTask(agent="codex", prompt=prompt, cwd=cwd,
                         timeout_s=timeout_s or self.timeout_s)
        return await self.codex.run(task, penv)

    async def review(self, cwd: Optional[str] = None) -> AgentResult:
        """用 Codex 审查最近一次 Claude 的输出（内存态）。"""
        if self.last_claude_result is None or not self.last_claude_result.output.strip():
            return AgentResult(agent="codex", error="没有可审查的 Claude 输出，请先运行 /claude")
        snippet = self.last_claude_result.output[:_REVIEW_MAX]
        prompt = f"请审查以下 Claude Code 的输出，指出问题与改进建议：\n\n{snippet}"
        return await self.run_codex(prompt, cwd=cwd)

    async def compare(self, prompt: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """并行调用 Claude 与 Codex，输出各自结果供对比。"""
        claude_res, codex_res = await asyncio.gather(
            self.run_claude(prompt, cwd=cwd), self.run_codex(prompt, cwd=cwd)
        )
        return {"claude": claude_res.to_dict(), "codex": codex_res.to_dict()}

    async def open_vscode(self, path: str) -> AgentResult:
        return await self.vscode.open(path)

    async def run_template(self, template: str, prompt: str,
                           cwd: Optional[str] = None) -> Dict[str, Any]:
        """运行预置协作模板（§4.2.2）：implement_then_review / parallel_design / doc_after_api。"""
        from aivyos_core.workbench.templates import run_template

        return await run_template(template, prompt, self.run_claude, self.run_codex, cwd=cwd)

    async def review_diff(self, cwd: str) -> AgentResult:
        """捕获 cwd 的 git diff 并交 Codex 审查（§4.2.3 人工确认闭环）。"""
        from aivyos_core.workbench.diff import build_review_prompt, capture_diff

        diff = await capture_diff(cwd)
        if not diff.ok:
            return AgentResult(agent="codex", error=diff.error)
        return await self.run_codex(build_review_prompt(diff.output), cwd=cwd)

    def status(self) -> Dict[str, Any]:
        return {
            "cc_switch": {"enabled": self.cc_switch_enabled, "db_path": str(self.reader.db_path)},
            "agents": {k: {"enabled": v} for k, v in self.agent_enabled.items()},
            "auto_open_vscode": self.auto_open_vscode,
            "vscode_available": self.vscode.available(),
            "last_notice": self.last_notice,
        }
