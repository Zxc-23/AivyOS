"""Mem0 记忆后端（文档 §4.2.1/§4.2.2）：自动抽取事实、混合检索。

未安装 mem0 时导入本模块不报错；实例化时抛出 Mem0Unavailable。
配置示例见文档 §4.2.2：vector_store=chroma（本地 .aivyos/memory_db）、
embedder=BAAI/bge-m3、llm=ollama qwen2.5:7b。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from aivyos_core.memory.base import MemoryBackend, MemoryHit


class Mem0Unavailable(RuntimeError):
    """mem0 未安装或初始化失败。"""


def _load_mem0():
    try:
        from mem0 import Memory  # type: ignore

        return Memory
    except ImportError as e:
        raise Mem0Unavailable(
            "mem0 未安装：pip install mem0 chromadb（见 requirements-ml.txt）。"
            "当前已自动回退到 simple 记忆后端。"
        ) from e


class Mem0Backend(MemoryBackend):
    name = "mem0"

    def __init__(
        self,
        persist_path: str,
        collection_name: str = "aivyos_memory",
        embedder_model: str = "BAAI/bge-m3",
        llm_model: str = "qwen2.5:7b",
        user_id: str = "owner",
    ) -> None:
        Memory = _load_mem0()
        self.user_id = user_id
        try:
            self.memory = Memory.from_config(
                {
                    "vector_store": {
                        "provider": "chroma",
                        "config": {"collection_name": collection_name, "path": persist_path},
                    },
                    "embedder": {"provider": "huggingface", "config": {"model": embedder_model}},
                    "llm": {"provider": "ollama", "config": {"model": llm_model}},
                }
            )
        except Exception as e:
            raise Mem0Unavailable(f"Mem0 初始化失败: {e}") from e

    async def add(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        # 文档 §4.2.2：memory.add(messages=text, user_id=owner, metadata=...)
        return self.memory.add(messages=text, user_id=self.user_id, metadata=metadata or {})

    async def search(self, query: str, top_k: int = 5) -> List[MemoryHit]:
        results = self.memory.search(query=query, user_id=self.user_id, limit=top_k)
        hits = []
        for r in results or []:
            score = float(r.get("score", 0.0))
            text = r.get("memory", "")
            if not text and r.get("metadata"):
                text = str(r.get("metadata"))
            hits.append(
                MemoryHit(
                    id=str(r.get("id", "")),
                    text=text,
                    score=score,
                    metadata=r.get("metadata") or {},
                    created_at=str(r.get("created_at", "")),
                )
            )
        return hits

    async def get_all(self) -> List[MemoryHit]:
        return await self.search("", top_k=100)
