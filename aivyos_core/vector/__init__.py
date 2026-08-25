"""向量数据库模块（Core-F2）。

stdlib 优先，Chroma 为可选依赖，未安装时自动降级 Mock。
导出:
    - VectorStore: 抽象基类（ABC）。
    - QueryResult: 查询结果 dataclass。
    - get_default_vector_store: 工厂函数，prefer_chroma=True 时优先 Chroma，失败降级 Mock。
    - ChromaVectorStore: ChromaDB 实现（可选）。
    - MockInMemoryVectorStore: 内存 Mock 实现（stdlib 零依赖）。
"""

from typing import Optional

from .base import (
    MockInMemoryVectorStore,
    QueryResult,
    VectorStore,
)


def _chroma_available() -> bool:
    """内部检测 chromadb 是否可用。"""
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


def get_default_vector_store(
    prefer_chroma: bool = True,
    collection_name: str = "aivyos_knowledge",
    in_memory: bool = True,
    persist_dir: Optional[str] = None,
) -> VectorStore:
    """获取默认向量存储实例（Chroma 优先，失败自动降级 Mock）。

    功能: 工厂函数，根据 prefer_chroma 与 chroma 可用性返回合适实例。
    参数:
        prefer_chroma: 是否优先使用 Chroma，默认 True。
        collection_name: Chroma collection 名称。
        in_memory: Chroma 是否内存模式（True 不落盘）。
        persist_dir: Chroma 持久化目录，仅 in_memory=False 时生效。
    返回:
        VectorStore: ChromaVectorStore 或 MockInMemoryVectorStore 实例。
    异常: 无。
    """
    if prefer_chroma and _chroma_available():
        try:
            from .chroma_store import ChromaVectorStore
            return ChromaVectorStore(
                collection_name=collection_name,
                in_memory=in_memory,
                persist_dir=persist_dir,
            )
        except Exception:
            pass
    return MockInMemoryVectorStore()


__all__ = [
    "VectorStore",
    "QueryResult",
    "get_default_vector_store",
    "ChromaVectorStore",
    "MockInMemoryVectorStore",
]


def _export_chroma():
    """延迟导出 ChromaVectorStore（未装 chroma 时仍留名，实际 import 由工厂处理）。"""
    global ChromaVectorStore
    try:
        from .chroma_store import ChromaVectorStore as _CV
        ChromaVectorStore = _CV
    except ImportError:
        class ChromaVectorStore:  # type: ignore
            """占位：chroma 未装时 import 不报错但实例化抛 RuntimeError。"""
            def __init__(self, *args, **kwargs):
                raise RuntimeError("chroma 未安装")


_export_chroma()
