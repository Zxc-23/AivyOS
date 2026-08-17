"""记忆后端抽象（文档 §4.2）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MemoryHit:
    id: str
    text: str
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "score": self.score,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class MemoryBackend(ABC):
    """统一记忆接口：add / search / get_all / update。"""

    name: str = "base"

    @abstractmethod
    async def add(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str, top_k: int = 5) -> List[MemoryHit]:
        raise NotImplementedError

    @abstractmethod
    async def get_all(self) -> List[MemoryHit]:
        raise NotImplementedError

    async def update(self, memory_id: str, text: str) -> str:
        """更新一条记忆（后端可选实现；默认追加新版本并标记 supersedes）。"""
        raise NotImplementedError(f"{self.name} 不支持 update")
