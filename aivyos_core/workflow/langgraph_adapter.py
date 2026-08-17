"""真实 langgraph 可选适配（文档 §4.5：LangGraph 为正式编排框架）。

mini_graph 提供零依赖语义等价实现；安装 langgraph 后可通过本适配器切换真实引擎。
未安装时 available()=False，实例化抛 WorkflowUnavailable（调用方保持 mini_graph）。
"""

from __future__ import annotations

from typing import Optional

from aivyos_core.workflow.checkpointer import SqliteCheckpointer


class WorkflowUnavailable(RuntimeError):
    pass


class LangGraphAdapter:
    @staticmethod
    def available() -> bool:
        try:
            import langgraph  # noqa: F401

            return True
        except ImportError:
            return False

    def __init__(self, checkpoint_path: Optional[str] = None) -> None:
        if not self.available():
            raise WorkflowUnavailable(
                "langgraph 未安装：pip install langgraph（见 requirements-ml.txt）。"
                "当前使用零依赖 mini_graph 引擎。"
            )
        from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: F401
        from langgraph.graph import END, StateGraph  # noqa: F401

        self._langgraph = __import__("langgraph.graph", fromlist=["StateGraph"])
        self._checkpoint_path = checkpoint_path

    def build_vibe_coding_graph(self, nodes: dict, edges: dict, entry: str, conditional: Optional[dict] = None):
        """用真实 langgraph 构建同构 VibeCoding 图（接入后与 mini_graph 行为一致）。"""
        from typing import TypedDict

        class VibeCodingState(TypedDict):
            user_request: str
            spec: dict
            files: dict
            preview_url: str
            build_failed: bool
            errors: list

        g = self._langgraph.StateGraph(VibeCodingState)
        for name, fn in nodes.items():
            g.add_node(name, fn)
        g.set_entry_point(entry)
        for src, dst in edges.items():
            g.add_edge(src, dst)
        if conditional:
            for src, (cond, path_map) in conditional.items():
                g.add_conditional_edges(src, cond, path_map)
        return g.compile()
