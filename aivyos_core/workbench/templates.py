"""双模型协作模板（计划书 §4.2.2）：串行/并行编排 Claude 与 Codex。

每个模板返回 {"template": ..., "ok": ..., "steps": [...]}，steps 记录每步
agent/输出/耗时，供 CLI 与前端面板展示进度。任一步失败即短路返回。
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from aivyos_core.workbench.models import AgentResult

_FUSION_MAX = 6000  # 融合时每个模型输出的截断长度

TEMPLATES = ("implement_then_review", "parallel_design", "doc_after_api")


def _step(name: str, res: AgentResult) -> Dict[str, Any]:
    return {"name": name, "agent": res.agent, "ok": res.ok,
            "output": res.output, "error": res.error, "elapsed_s": round(res.elapsed_s, 2)}


async def run_template(
    template: str,
    prompt: str,
    run_claude: Callable[..., Awaitable[AgentResult]],
    run_codex: Callable[..., Awaitable[AgentResult]],
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """模板统一入口；run_claude/run_codex 由 WorkbenchService 注入（便于测试 mock）。"""
    if template == "implement_then_review":
        return await _implement_then_review(prompt, run_claude, run_codex, cwd)
    if template == "parallel_design":
        return await _parallel_design(prompt, run_claude, run_codex, cwd)
    if template == "doc_after_api":
        return await _doc_after_api(prompt, run_claude, run_codex, cwd)
    return {"template": template, "ok": False, "steps": [],
            "error": f"未知模板: {template}（可选: {', '.join(TEMPLATES)}）"}


async def _implement_then_review(prompt, run_claude, run_codex, cwd) -> Dict[str, Any]:
    """Claude 实现 → Codex 审查（§3.1 串行协作）。"""
    steps: List[Dict[str, Any]] = []
    impl = await run_claude(prompt, cwd=cwd)
    steps.append(_step("claude 实现", impl))
    if not impl.ok:
        return {"template": "implement_then_review", "ok": False, "steps": steps,
                "error": f"Claude 实现失败: {impl.error}"}
    review = await run_codex(
        f"请审查以下 Claude Code 的实现输出，指出问题与改进建议：\n\n{impl.output[:_FUSION_MAX]}",
        cwd=cwd,
    )
    steps.append(_step("codex 审查", review))
    return {"template": "implement_then_review", "ok": review.ok, "steps": steps,
            "error": "" if review.ok else review.error}


async def _parallel_design(prompt, run_claude, run_codex, cwd) -> Dict[str, Any]:
    """双模型并行出方案 → Codex 融合为「共识 / 分歧」（§3.2 并行对比）。"""
    claude_res, codex_res = await asyncio.gather(
        run_claude(prompt, cwd=cwd), run_codex(prompt, cwd=cwd)
    )
    steps = [_step("claude 方案", claude_res), _step("codex 方案", codex_res)]
    if not (claude_res.ok and codex_res.ok):
        return {"template": "parallel_design", "ok": False, "steps": steps,
                "error": "至少一个模型失败，无法融合"}
    fusion = await run_codex(
        "以下是两个模型对同一问题的方案。请输出两部分：【共识】两者一致的核心结论；"
        "【分歧】两者不同的地方（不自动取舍，逐条列出供用户选择）。\n\n问题："
        f"{prompt}\n\n--- 模型 A ---\n{claude_res.output[:_FUSION_MAX]}\n\n"
        f"--- 模型 B ---\n{codex_res.output[:_FUSION_MAX]}",
        cwd=cwd,
    )
    steps.append(_step("codex 融合", fusion))
    return {"template": "parallel_design", "ok": fusion.ok, "steps": steps,
            "error": "" if fusion.ok else fusion.error}


async def _doc_after_api(prompt, run_claude, run_codex, cwd) -> Dict[str, Any]:
    """Claude 设计 API → Codex 生成 Swagger 文档。"""
    steps: List[Dict[str, Any]] = []
    design = await run_claude(f"请为以下需求设计 API（路径/方法/参数/响应结构）：\n{prompt}", cwd=cwd)
    steps.append(_step("claude 设计 API", design))
    if not design.ok:
        return {"template": "doc_after_api", "ok": False, "steps": steps,
                "error": f"Claude 设计失败: {design.error}"}
    doc = await run_codex(
        "请根据以下 API 设计生成 Swagger (OpenAPI 3.0) YAML 文档：\n\n"
        f"{design.output[:_FUSION_MAX]}",
        cwd=cwd,
    )
    steps.append(_step("codex 生成 Swagger", doc))
    return {"template": "doc_after_api", "ok": doc.ok, "steps": steps,
            "error": "" if doc.ok else doc.error}
