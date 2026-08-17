"""记忆管理器：按配置选择后端（mem0 优先，缺失自动降级 simple）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from aivyos_core.memory.base import MemoryBackend, MemoryHit
from aivyos_core.memory.mem0_backend import Mem0Backend, Mem0Unavailable
from aivyos_core.memory.simple import SimpleFileMemory

log = logging.getLogger(__name__)

# 触发自动记忆抽取的句式（Week 1 朴素规则；Week 3 由 Mem0 LLM 抽取替代）
_EXTRACT_PATTERNS = (
    ("记住", 0.8),
    ("我喜欢", 0.9),
    ("我讨厌", 0.9),
    ("我叫", 1.0),
    ("我是", 0.7),
    ("我的名字", 1.0),
    ("别忘了", 0.9),
    ("记得", 0.7),
)


class MemoryManager:
    """统一记忆入口：add / search / get_all / try_extract / backend_name。"""

    def __init__(self, cfg: Dict[str, Any], home: Path) -> None:
        self.cfg = cfg
        self.home = home
        self._backend: Optional[MemoryBackend] = None

    @property
    def backend(self) -> MemoryBackend:
        if self._backend is None:
            self._backend = self._create_backend()
        return self._backend

    def _create_backend(self) -> MemoryBackend:
        mode = self.cfg.get("backend", "auto")
        if mode == "mem0" or mode == "auto":
            try:
                b = Mem0Backend(
                    persist_path=str(self.home / "memory_db"),
                    collection_name=self.cfg.get("mem0_collection", "aivyos_memory"),
                    embedder_model=self.cfg.get("mem0_embedder_model", "BAAI/bge-m3"),
                    llm_model=self.cfg.get("mem0_llm_model", "qwen2.5:7b"),
                )
                log.info("记忆后端：Mem0 + ChromaDB（文档 §4.2）")
                return b
            except Mem0Unavailable as e:
                if mode == "mem0":
                    log.warning("配置要求 mem0 但不可用：%s", e)
                else:
                    log.info("mem0 不可用，回退 simple：%s", e)
        return SimpleFileMemory(self.home / self.cfg.get("simple_path", "memory.jsonl"))

    @property
    def backend_name(self) -> str:
        return self.backend.name

    async def add(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        return await self.backend.add(text, metadata)

    async def search(self, query: str, top_k: int = 5) -> List[MemoryHit]:
        return await self.backend.search(query, top_k=top_k)

    async def get_all(self) -> List[MemoryHit]:
        return await self.backend.get_all()

    async def try_extract(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """朴素规则抽取（Week 1）：命中句式则写入记忆，返回记忆 id。"""
        if not self.cfg.get("auto_extract", True):
            return None
        for pattern, _ in _EXTRACT_PATTERNS:
            if pattern in text:
                return await self.add(f"[自动抽取] {text.strip()}", metadata)
        return None
