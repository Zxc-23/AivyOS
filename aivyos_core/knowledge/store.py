"""知识卡片存储（JSONL 持久化）+ CRUD + 查询 + 备份恢复。

- 原子写入：tmp → os.replace（避免断电损坏）
- 查询：按标签/分类筛选、关键词搜索、排序（时间/相关性/使用频率/收藏）
- 备份恢复：导出全部卡片 JSON + 从备份导入
- 关联：links 双向维护
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from aivyos_core.knowledge.card import KnowledgeCard, card_from_dict

log = logging.getLogger(__name__)

_STOP = set("的了是在和与就都而及或一个你我他她它这那")


def _tokenize(text: str) -> set[str]:
    """CJK 1-gram + 英文词（朴素分词）。"""
    tokens: set[str] = set()
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" and ch not in _STOP:
            tokens.add(ch)
    tokens.update(re.findall(r"[a-zA-Z0-9_]{2,}", text.lower()))
    return tokens


class KnowledgeStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cards: Dict[str, KnowledgeCard] = {}
        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                card = card_from_dict(json.loads(line))
                self._cards[card.id] = card
            except (json.JSONDecodeError, KeyError):
                continue

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for card in self._cards.values():
                f.write(json.dumps(card.to_dict(), ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)  # 原子写

    # ---- CRUD ----

    def create(self, **fields: Any) -> KnowledgeCard:
        card = KnowledgeCard(id=uuid.uuid4().hex[:12], **{k: v for k, v in fields.items() if k != "id"})
        self._cards[card.id] = card
        self._save()
        return card

    def get(self, card_id: str) -> Optional[KnowledgeCard]:
        return self._cards.get(card_id)

    def update(self, card_id: str, **changes: Any) -> Optional[KnowledgeCard]:
        card = self._cards.get(card_id)
        if card is None:
            return None
        card.update(**changes)
        self._save()
        return card

    def delete(self, card_id: str) -> bool:
        card = self._cards.pop(card_id, None)
        if card is None:
            return False
        # 清理其它卡片的关联
        for c in self._cards.values():
            if card_id in c.links:
                c.links.remove(card_id)
        self._save()
        return True

    def toggle_favorite(self, card_id: str) -> Optional[KnowledgeCard]:
        card = self._cards.get(card_id)
        if card is None:
            return None
        card.favorite = not card.favorite
        self._save()
        return card

    # ---- 关联 ----

    def link(self, card_id: str, other_id: str) -> bool:
        """建立双向关联。"""
        a, b = self._cards.get(card_id), self._cards.get(other_id)
        if a is None or b is None or card_id == other_id:
            return False
        if other_id not in a.links:
            a.links.append(other_id)
        if card_id not in b.links:
            b.links.append(card_id)
        self._save()
        return True

    def unlink(self, card_id: str, other_id: str) -> bool:
        a, b = self._cards.get(card_id), self._cards.get(other_id)
        if a is None or b is None:
            return False
        if other_id in a.links:
            a.links.remove(other_id)
        if card_id in b.links:
            b.links.remove(card_id)
        self._save()
        return True

    # ---- 查询 ----

    def list_all(self, sort: str = "updated") -> List[KnowledgeCard]:
        cards = list(self._cards.values())
        return self._sort(cards, sort)

    def _sort(self, cards: List[KnowledgeCard], sort: str) -> List[KnowledgeCard]:
        if sort == "favorite":
            return sorted(cards, key=lambda c: (c.favorite, c.updated_at), reverse=True)
        if sort == "usage":
            return sorted(cards, key=lambda c: (c.usage, c.updated_at), reverse=True)
        if sort == "created":
            return sorted(cards, key=lambda c: c.created_at, reverse=True)
        return sorted(cards, key=lambda c: c.updated_at, reverse=True)

    def filter(self, category: str = "", tag: str = "", favorite_only: bool = False) -> List[KnowledgeCard]:
        cards = []
        for c in self._cards.values():
            if favorite_only and not c.favorite:
                continue
            if category and c.category != category:
                continue
            if tag and tag not in c.tags:
                continue
            cards.append(c)
        return self._sort(cards, "updated")

    def search(self, query: str, limit: int = 20) -> List[KnowledgeCard]:
        """关键词搜索（标题/摘要/内容/标签），按命中度排序。"""
        q = query.strip().lower()
        if not q:
            return self.list_all("updated")[:limit]
        q_tokens = _tokenize(q)
        scored = []
        for c in self._cards.values():
            score = 0
            if q in c.title.lower():
                score += 10
            if q in c.summary.lower():
                score += 6
            if q in c.content.lower():
                score += 4
            if any(q in t.lower() for t in c.tags):
                score += 5
            # 词重叠
            overlap = len(q_tokens & _tokenize(c.title + c.summary + c.content))
            score += overlap
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:limit]]

    def find_similar(self, text: str, limit: int = 3, min_score: float = 0.05) -> List[Dict[str, Any]]:
        """相似内容识别（自动调用知识卡片）。返回带相似度的卡片。"""
        q_tokens = _tokenize(text)
        if not q_tokens:
            return []
        scored = []
        for c in self._cards.values():
            c_tokens = _tokenize(c.title + c.summary + c.content)
            overlap = len(q_tokens & c_tokens)
            score = overlap / max(1, len(q_tokens))
            if score >= min_score:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, c in scored[:limit]:
            c.usage += 1
            out.append({"card": c.to_dict(), "score": round(score, 3)})
        if out:
            self._save()  # 持久化 usage
        return out

    # ---- 统计与备份 ----

    def categories(self) -> List[str]:
        cats = {c.category for c in self._cards.values()}
        return sorted(cats)

    def all_tags(self) -> List[str]:
        tags: set[str] = set()
        for c in self._cards.values():
            tags.update(c.tags)
        return sorted(tags)

    def stats(self) -> Dict[str, Any]:
        return {
            "total": len(self._cards),
            "favorites": sum(1 for c in self._cards.values() if c.favorite),
            "categories": self.categories(),
            "tags": self.all_tags(),
        }

    # ---- 知识图谱（可视化）----

    def graph(self) -> Dict[str, Any]:
        """知识图谱：节点（卡片）+ 边（关联）。供前端力导向图渲染。"""
        nodes = []
        for c in self._cards.values():
            nodes.append({
                "id": c.id, "title": c.title, "category": c.category,
                "favorite": c.favorite, "usage": c.usage,
            })
        edges = []
        seen = set()
        for c in self._cards.values():
            for lid in c.links:
                if lid not in self._cards:
                    continue
                key = tuple(sorted((c.id, lid)))
                if key in seen:
                    continue
                seen.add(key)
                edges.append({"source": c.id, "target": lid})
        return {"nodes": nodes, "edges": edges}

    # ---- 导出/分享 ----

    def export_card(self, card_id: str, fmt: str = "markdown") -> Dict[str, Any]:
        """导出单卡为 Markdown/JSON（分享用）。"""
        c = self._cards.get(card_id)
        if c is None:
            return {"error": "卡片不存在"}
        d = c.to_dict()
        if fmt == "json":
            import json

            return {"format": "json", "text": json.dumps(d, ensure_ascii=False, indent=2)}
        # markdown
        lines = [
            f"# {c.title}",
            "",
            f"> 分类：{c.category} ｜ 标签：{', '.join(c.tags) or '无'} ｜ 版本 v{c.version}",
            "",
            f"**摘要**：{c.summary or '（无）'}",
            "",
            f"**内容**：",
            c.content or "（无）",
            "",
            f"*创建 {c.created_at} ｜ 更新 {c.updated_at} ｜ 调用 {c.usage} 次*",
        ]
        return {"format": "markdown", "text": "\n".join(lines)}

    def export_backup(self, out_path: Path) -> Path:
        """导出全部卡片为 JSON 备份。"""
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "cards": [c.to_dict() for c in self._cards.values()],
        }
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_path

    def import_backup(self, in_path: Path, merge: bool = False) -> int:
        """从备份导入卡片。merge=True 合并（按 id 覆盖），否则仅导入不存在的。"""
        in_path = Path(in_path)
        data = json.loads(in_path.read_text(encoding="utf-8"))
        count = 0
        for item in data.get("cards", []):
            cid = item.get("id", "")
            if not cid:
                continue
            if cid in self._cards and not merge:
                continue
            self._cards[cid] = card_from_dict(item)
            count += 1
        self._save()
        return count

    def clear(self) -> int:
        n = len(self._cards)
        self._cards.clear()
        self._save()
        return n
