"""极简状态图引擎（文档 §4.5：LangGraph 语义子集，零依赖）。

支持：节点 / 有向边 / 条件边 / 入口点 / 检查点（SQLite）/ 断点续传。
节点函数签名：fn(state: dict, ctx: dict) -> dict（可 sync 或 async）。
执行语义对齐 LangGraph：每节点执行成功 → 保存检查点 → 沿边继续 → END。
失败时从最后成功节点续传（§4.5.2 失败恢复/断点续传）。
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional

from aivyos_core.workflow.checkpointer import SqliteCheckpointer

END = "__end__"

NodeFn = Callable[[Dict[str, Any], Dict[str, Any]], Any]
CondFn = Callable[[Dict[str, Any]], str]


class WorkflowError(Exception):
    pass


class StateGraph:
    """状态图构建器（add_node / add_edge / add_conditional_edges / compile）。"""

    def __init__(self, state_schema: Optional[Dict[str, Any]] = None) -> None:
        self.state_schema = dict(state_schema or {})
        self._nodes: Dict[str, NodeFn] = {}
        self._edges: Dict[str, str] = {}
        self._conditional: Dict[str, tuple[CondFn, Dict[str, str]]] = {}
        self._entry: Optional[str] = None

    def add_node(self, name: str, fn: NodeFn) -> "StateGraph":
        self._nodes[name] = fn
        return self

    def set_entry_point(self, name: str) -> "StateGraph":
        if name not in self._nodes:
            raise WorkflowError(f"入口节点不存在: {name}")
        self._entry = name
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self._edges[src] = dst
        return self

    def add_conditional_edges(self, src: str, condition: CondFn, path_map: Dict[str, str]) -> "StateGraph":
        self._conditional[src] = (condition, path_map)
        return self

    def compile(self, checkpointer: Optional[SqliteCheckpointer] = None) -> "CompiledGraph":
        if self._entry is None:
            raise WorkflowError("未设置入口点（set_entry_point）")
        missing = [n for n in list(self._edges) + list(self._conditional) if n not in self._nodes]
        if missing:
            raise WorkflowError(f"边引用了未注册节点: {missing}")
        return CompiledGraph(self, checkpointer)


class CompiledGraph:
    def __init__(self, graph: StateGraph, checkpointer: Optional[SqliteCheckpointer]) -> None:
        self._nodes = graph._nodes
        self._edges = graph._edges
        self._conditional = graph._conditional
        self._entry = graph._entry
        self._schema = graph.state_schema
        self.checkpointer = checkpointer
        self.last_trace: List[str] = []
        self.node_timings_ms: Dict[str, float] = {}  # §21.2 工作流追踪：节点耗时

    # ---- 工具 ----

    def _next(self, node: str, state: Dict[str, Any]) -> str:
        if node in self._conditional:
            cond, path_map = self._conditional[node]
            key = cond(state)
            if key not in path_map:
                raise WorkflowError(f"条件结果无对应边: {node} → {key}")
            return path_map[key]
        if node in self._edges:
            return self._edges[node]
        raise WorkflowError(f"节点无出口边: {node}")

    async def _run_node(self, name: str, state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        fn = self._nodes[name]
        result = fn(state, ctx) if not inspect.iscoroutinefunction(fn) else await fn(state, ctx)
        if result is None:
            return dict(state)
        if not isinstance(result, dict):
            raise WorkflowError(f"节点 {name} 返回值必须是 dict 或 None")
        return result

    async def _loop(self, start: str, state: Dict[str, Any], thread_id: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        import time

        current = start
        while current != END:
            t0 = time.monotonic()
            state = await self._run_node(current, state, ctx)
            self.node_timings_ms[current] = round((time.monotonic() - t0) * 1000, 2)
            self.last_trace.append(current)
            if self.checkpointer is not None:
                # 剥离内部瞬态键（如 _preview_server），避免不可序列化对象入库
                saveable = {k: v for k, v in state.items() if not k.startswith("_")}
                self.checkpointer.save(thread_id, current, saveable)
            current = self._next(current, state)
        return state

    # ---- 执行 ----

    async def invoke(self, input_state: Dict[str, Any], thread_id: str = "default", ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """从入口执行到 END，返回最终状态。失败抛 WorkflowError（检查点已保存）。"""
        state = {**self._schema, **input_state}
        self.last_trace = []
        return await self._loop(self._entry, state, thread_id, ctx or {})

    async def resume(self, thread_id: str = "default", patch: Dict[str, Any] | None = None, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """断点续传（§4.5.2）：从最后检查点节点之后继续。"""
        if self.checkpointer is None:
            raise WorkflowError("未配置检查点，无法续传")
        latest = self.checkpointer.latest(thread_id)
        if latest is None:
            raise WorkflowError(f"无检查点可续传: {thread_id}")
        node, state = latest
        state = {**state, **(patch or {})}
        self.last_trace = []
        if node == END:
            return state
        nxt = self._next(node, state)
        if nxt == END:
            return state
        return await self._loop(nxt, state, thread_id, ctx or {})
