"""知识卡片系统（Phase 3 升级：记忆管理 → 知识卡片）。

- card：卡片数据模型（版本/关联/收藏）
- store：存储 + CRUD + 查询 + 备份
- extract：自动知识提取（LLM 可选 + 规则回退）
- service：沉淀/调用编排
"""

from aivyos_core.knowledge.card import KnowledgeCard, card_from_dict
from aivyos_core.knowledge.extract import KnowledgeExtractor
from aivyos_core.knowledge.service import KnowledgeService
from aivyos_core.knowledge.store import KnowledgeStore

__all__ = [
    "KnowledgeCard", "card_from_dict",
    "KnowledgeStore", "KnowledgeExtractor", "KnowledgeService",
]
