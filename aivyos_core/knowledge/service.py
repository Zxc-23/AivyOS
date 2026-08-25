"""知识卡片服务编排：提取 → 去重/更新 → 存储；相似调用。

- ingest_conversation：对话文本 → 提取知识 → 若已存在相似卡片则更新，否则新建
- recall：相似内容识别 → 返回相关卡片（对话中自动呈现）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from aivyos_core.knowledge.extract import KnowledgeExtractor
from aivyos_core.knowledge.store import KnowledgeStore

log = logging.getLogger(__name__)

# 相似度阈值：超过则视为"同一知识"更新旧卡，否则新建
DEDUP_THRESHOLD = 0.35


class KnowledgeService:
    def __init__(self, store: KnowledgeStore, extractor: Optional[KnowledgeExtractor] = None) -> None:
        self.store = store
        self.extractor = extractor or KnowledgeExtractor()

    # ---- 沉淀（自动提取 → 去重 → 建卡/更新）----

    async def ingest(self, text: str) -> Optional[Dict[str, Any]]:
        """从一段对话文本沉淀知识卡片。

        返回 {action: create|update|skip, card} 或 None。
        不阻塞对话：LLM 提取带超时，失败回退规则。
        """
        fields = await self.extractor.extract(text)
        if fields is None:
            return None
        # 去重：与现有卡片相似 → 更新旧卡（版本管理记录演变）
        similar = self.store.find_similar(fields["title"] + fields["content"], limit=1, min_score=DEDUP_THRESHOLD)
        if similar:
            best = similar[0]
            old = self.store.get(best["card"]["id"])
            if old is not None:
                old.update(
                    title=fields.get("title", old.title),
                    summary=fields.get("summary") or old.summary,
                    content=fields.get("content") or old.content,
                    category=fields.get("category", old.category),
                    tags=fields.get("tags", old.tags),
                    _force=True,
                )
                self.store._save()
                return {"action": "update", "card": old.to_dict(), "score": best["score"]}
        card = self.store.create(**fields)
        return {"action": "create", "card": card.to_dict()}

    # ---- 调用（相似内容识别 → 对话中呈现）----

    def recall(
        self, text: str, limit: int = 3, min_score: float = 0.05, vector_store: Any = None
    ) -> List[Dict[str, Any]]:
        """对话中自动调用相似知识卡片（带相似度）。

        兼容可选 vector_store：默认 None 时 semantic_search 内部走 find_similar，
        100% 向后兼容现有调用链（server 端 knowledge.recall 不传 vector_store）。
        """
        return self.store.semantic_search(
            text, top_k=limit, min_score=min_score, vector_store=vector_store
        )

    # ---- 透传 store 操作 ----

    def __getattr__(self, name: str):
        return getattr(self.store, name)
