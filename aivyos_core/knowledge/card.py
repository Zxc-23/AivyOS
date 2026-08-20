"""知识卡片数据模型（知识卡片系统核心，§8 记忆连续性的知识化升级）。

卡片结构：
- id / title 标题 / summary 摘要 / content 正文
- tags 标签 / category 分类 / favorite 收藏
- created_at / updated_at / version / versions 历史
- links 关联卡片 id 列表 / usage 调用次数
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class KnowledgeCard:
    id: str
    title: str = ""
    summary: str = ""
    content: str = ""
    category: str = "未分类"
    tags: List[str] = field(default_factory=list)
    favorite: bool = False
    source: str = "manual"  # manual | auto | conversation
    created_at: str = ""
    updated_at: str = ""
    version: int = 1
    versions: List[Dict[str, Any]] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    usage: int = 0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now()
        if not self.updated_at:
            self.updated_at = self.created_at

    # ---- 版本管理（记录知识演变）----

    def snapshot(self) -> Dict[str, Any]:
        """当前状态快照（版本历史用）。"""
        return {
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "category": self.category,
            "tags": list(self.tags),
            "version": self.version,
            "ts": _now(),
        }

    def update(self, **changes: Any) -> bool:
        """更新字段；内容/标题/摘要/标签等变化时记录版本并递增。"""
        meaningful = False
        for key in ("title", "summary", "content", "category"):
            if key in changes and changes[key] != getattr(self, key):
                meaningful = True
                break
        if "tags" in changes and sorted(changes["tags"]) != sorted(self.tags):
            meaningful = True
        if not meaningful and not changes.get("_force"):
            return False
        # 记录历史版本
        self.versions.append(self.snapshot())
        if len(self.versions) > 20:
            self.versions = self.versions[-20:]
        for key, value in changes.items():
            if key == "_force":
                continue
            if hasattr(self, key):
                setattr(self, key, value)
        self.version += 1
        self.updated_at = _now()
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "category": self.category,
            "tags": self.tags,
            "favorite": self.favorite,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "versions": self.versions[-5:],
            "links": self.links,
            "usage": self.usage,
        }


def card_from_dict(d: Dict[str, Any]) -> KnowledgeCard:
    return KnowledgeCard(
        id=d.get("id", ""),
        title=d.get("title", ""),
        summary=d.get("summary", ""),
        content=d.get("content", ""),
        category=d.get("category", "未分类"),
        tags=list(d.get("tags", [])),
        favorite=bool(d.get("favorite", False)),
        source=d.get("source", "manual"),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
        version=int(d.get("version", 1)),
        versions=list(d.get("versions", [])),
        links=list(d.get("links", [])),
        usage=int(d.get("usage", 0)),
    )
