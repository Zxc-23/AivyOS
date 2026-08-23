"""MCP workbench Server：双模型协同工具（计划书 Phase 1 §4.1.2）。

- workbench_claude_run / workbench_codex_run：L3（外部进程 + 网络外发，需确认 + 审计）
- workbench_vscode_open：L1
返回内容只含脱敏信息（token 不出现在任何返回值里）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from aivyos_core.mcp.types import PermissionLevel, Tool, ToolResult, make_tool
from aivyos_core.workbench.service import WorkbenchService


def _result_content(res, notice: str = "") -> str:
    parts: List[str] = []
    if notice:
        parts.append(f"提示: {notice}")
    parts.append(res.output if res.ok and res.output else res.error or "（无输出）")
    return "\n".join(parts)


class WorkbenchServer:
    def __init__(self, service: Optional[WorkbenchService] = None) -> None:
        # 允许测试注入 mock service；默认惰性创建（首个调用时读配置）
        self._service = service

    @property
    def service(self) -> WorkbenchService:
        if self._service is None:
            from aivyos_core.config import load_config

            self._service = WorkbenchService(load_config())
        return self._service

    async def _claude_run(self, args: Dict[str, Any]) -> ToolResult:
        prompt = args.get("prompt", "")
        if not prompt:
            return ToolResult(False, error="prompt 为空")
        res = await self.service.run_claude(
            prompt, cwd=args.get("cwd") or None,
            timeout_s=float(args.get("timeout_s", 0)) or None,
        )
        return ToolResult(res.ok, content=_result_content(res, self.service.last_notice),
                          data={"exit_code": res.exit_code, "elapsed_s": round(res.elapsed_s, 2)},
                          error=res.error)

    async def _codex_run(self, args: Dict[str, Any]) -> ToolResult:
        prompt = args.get("prompt", "")
        if not prompt:
            return ToolResult(False, error="prompt 为空")
        res = await self.service.run_codex(
            prompt, cwd=args.get("cwd") or None,
            timeout_s=float(args.get("timeout_s", 0)) or None,
        )
        return ToolResult(res.ok, content=_result_content(res, self.service.last_notice),
                          data={"exit_code": res.exit_code, "elapsed_s": round(res.elapsed_s, 2)},
                          error=res.error)

    async def _vscode_open(self, args: Dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        if not path:
            return ToolResult(False, error="path 为空")
        res = await self.service.open_vscode(path)
        return ToolResult(res.ok, content=f"已在 VS Code 打开: {path}" if res.ok else "",
                          error=res.error)

    def tools(self) -> List[Tool]:
        prompt_schema = {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_s": {"type": "number"},
            },
            "required": ["prompt"],
        }
        return [
            make_tool(
                "workbench_claude_run", "调用 Claude Code CLI 执行任务（L3，需确认）",
                prompt_schema, self._claude_run, PermissionLevel.L3,
                impact=lambda a: f"Claude 执行: {a.get('prompt', '')[:80]}",
                server="workbench",
            ),
            make_tool(
                "workbench_codex_run", "调用 Codex / ChatGPT CLI 执行任务（L3，需确认）",
                prompt_schema, self._codex_run, PermissionLevel.L3,
                impact=lambda a: f"Codex 执行: {a.get('prompt', '')[:80]}",
                server="workbench",
            ),
            make_tool(
                "workbench_vscode_open", "在 VS Code 中打开文件/目录（L1）",
                {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                self._vscode_open, PermissionLevel.L1,
                server="workbench",
            ),
        ]
