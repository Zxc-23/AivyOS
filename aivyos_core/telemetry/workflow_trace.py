"""工作流追踪（文档 §21.2 / T10.3）：节点耗时 span + 检查点回放 + 本地可视化。

- trace_workflow_run：包装一次工作流执行，返回 trace（节点顺序 + 耗时 + 分支条件）
- replay_workflow：从检查点回放执行轨迹（§21.2 图执行轨迹回放，本地不上云）
- 可视化：Mermaid sequenceDiagram（本地文本，可贴 Typora/网页渲染）
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def trace_workflow_run(app, input_state: Dict[str, Any], thread_id: str = "default", ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """执行工作流并返回追踪数据（§21.2：节点顺序 + 耗时 + 状态快照）。"""
    import asyncio

    t0 = time.monotonic()
    state = asyncio.run(app.invoke(input_state, thread_id=thread_id, ctx=ctx))
    total_ms = round((time.monotonic() - t0) * 1000, 2)
    timings = getattr(app, "node_timings_ms", {})
    return {
        "thread_id": thread_id,
        "trace": list(getattr(app, "last_trace", [])),
        "node_timings_ms": timings,
        "total_ms": total_ms,
        "final_state_keys": sorted(state.keys()),
    }


def replay_workflow(checkpointer, thread_id: str) -> Optional[Dict[str, Any]]:
    """从检查点回放：返回该线程全部检查点序列（节点 + 状态键 + 时间）。"""
    rows = checkpointer.list_threads()  # 或专用遍历
    latest = checkpointer.latest(thread_id)
    if latest is None:
        return None
    node, state = latest
    return {
        "thread_id": thread_id,
        "last_node": node,
        "state_keys": sorted(state.keys()),
        "threads": rows,
    }


def to_mermaid(trace: Dict[str, Any]) -> str:
    """本地可视化（§21.2）：Mermaid sequenceDiagram。"""
    lines = ["sequenceDiagram", "    participant U as 用户", "    participant W as 工作流"]
    for i, node in enumerate(trace.get("trace", [])):
        ms = trace.get("node_timings_ms", {}).get(node, "?")
        lines.append(f"    W->>W: {i}. {node} ({ms}ms)")
    lines.append(f"    Note over W: 总耗时 {trace.get('total_ms', '?')}ms")
    return "\n".join(lines)
