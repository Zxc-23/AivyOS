"""简单记忆后端（零依赖回退）：JSONL 追加 + 词重叠检索。

用途：未安装 Mem0/ChromaDB 时保证记忆链路可运行；检索质量低于 Mem0 混合检索，
Week 3 接入 Mem0 后自动切换（backend=mem0）。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from aivyos_core.memory.base import MemoryBackend, MemoryHit

_STOP = set("的了是在和与就都而及或一个你我他她它这那")


def _tokenize(text: str) -> set[str]:
    """CJK 字符 1-gram + 英文词。足够做朴素检索。"""
    tokens: set[str] = set()
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" and ch not in _STOP:
            tokens.add(ch)
    tokens.update(re.findall(r"[a-zA-Z0-9_]{2,}", text.lower()))
    return tokens


class SimpleFileMemory(MemoryBackend):
    name = "simple-jsonl"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: List[Dict[str, Any]] = []
        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    self._records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    def _append(self, record: Dict[str, Any]) -> None:
        self._records.append(record)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---- MemoryBackend ----

    async def add(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        rid = "mem_" + uuid.uuid4().hex[:10]
        self._append(
            {
                "id": rid,
                "text": text,
                "metadata": metadata or {},
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        return rid

    async def search(self, query: str, top_k: int = 5) -> List[MemoryHit]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        scored = []
        for rec in self._records:
            text = rec["text"]
            r_tokens = _tokenize(text)
            overlap = len(q_tokens & r_tokens)
            if overlap:
                # 简单重合率 + 长度惩罚
                score = overlap / max(1, len(q_tokens)) * min(1.0, 8.0 / max(1, len(text) / 10))
                scored.append((score, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            MemoryHit(
                id=rec["id"],
                text=rec["text"],
                score=score,
                metadata=rec.get("metadata", {}),
                created_at=rec.get("created_at", ""),
            )
            for score, rec in scored[:top_k]
        ]

    async def get_all(self) -> List[MemoryHit]:
        return [
            MemoryHit(
                id=rec["id"], text=rec["text"],
                metadata=rec.get("metadata", {}),
                created_at=rec.get("created_at", ""),
            )
            for rec in self._records
        ]

    async def update(self, memory_id: str, text: str) -> str:
        """追加新版本并标记 supersedes（JSONL 追加式存储的更新语义）。"""
        rid = "mem_" + uuid.uuid4().hex[:10]
        self._append(
            {
                "id": rid,
                "text": text,
                "metadata": {"supersedes": memory_id},
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        return rid
