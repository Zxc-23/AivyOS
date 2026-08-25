"""知识卡片语义搜索测试（TDD：先红后绿）。"""

import unittest
from pathlib import Path

from aivyos_core.knowledge.service import KnowledgeService
from aivyos_core.knowledge.store import KnowledgeStore
from aivyos_core.vector.base import MockInMemoryVectorStore

from tests import AivyTestCase, _TMP


def _make_3_cards(store: KnowledgeStore):
    """插入 3 张固定卡片，返回按插入顺序的 id 列表 [py_list, py_dict, java]。"""
    c1 = store.create(
        title="Python 列表操作教程",
        summary="列表常用方法",
        content="append/pop/sort/slice 等操作",
        category="编程教程",
        tags=["python", "list"],
    )
    c2 = store.create(
        title="Python 字典方法大全",
        summary="字典常用方法",
        content="get/keys/values/items/update 等",
        category="编程教程",
        tags=["python", "dict"],
    )
    c3 = store.create(
        title="Java 面向对象基础",
        summary="Java OOP 概念",
        content="类/对象/继承/多态/封装",
        category="编程教程",
        tags=["java", "oop"],
    )
    return [c1.id, c2.id, c3.id]


class TestKnowledgeSemantic(AivyTestCase):
    """知识卡片语义搜索 4 tests。"""

    def test_semantic_search_uses_vector_store_when_provided(self):
        path = Path(_TMP) / "semantic_vs.jsonl"
        if path.exists():
            path.unlink()
        try:
            store = KnowledgeStore(path)
            ids = _make_3_cards(store)
            vs = MockInMemoryVectorStore()
            results = store.semantic_search("python list", top_k=5, min_score=0.1, vector_store=vs)
            py_ids = set(ids[:2])
            returned_ids = [r["card"]["id"] for r in results]
            self.assertGreaterEqual(len(results), 2)
            self.assertIn(returned_ids[0], py_ids)
            self.assertIn(returned_ids[1], py_ids)
            for r in results[:2]:
                self.assertGreater(r["score"], 0.2)
        finally:
            if path.exists():
                path.unlink()

    def test_semantic_search_falls_back_when_vector_scores_too_low(self):
        path = Path(_TMP) / "semantic_fb.jsonl"
        if path.exists():
            path.unlink()
        try:
            store = KnowledgeStore(path)
            _make_3_cards(store)
            vs = MockInMemoryVectorStore()
            results = store.semantic_search("python list", top_k=5, min_score=0.99, vector_store=vs)
            self.assertTrue(len(results) >= 1)
        finally:
            if path.exists():
                path.unlink()

    def test_semantic_search_no_vector_store_uses_find_similar(self):
        path = Path(_TMP) / "semantic_nvs.jsonl"
        if path.exists():
            path.unlink()
        try:
            store = KnowledgeStore(path)
            _make_3_cards(store)
            a = store.semantic_search("Python", vector_store=None)
            b = store.find_similar("Python", limit=5, min_score=0.1)
            self.assertEqual(
                [r["card"]["id"] for r in a],
                [r["card"]["id"] for r in b],
            )
        finally:
            if path.exists():
                path.unlink()

    def test_service_recall_without_vector_store_compatible(self):
        path = Path(_TMP) / "semantic_svc.jsonl"
        if path.exists():
            path.unlink()
        try:
            store = KnowledgeStore(path)
            svc = KnowledgeService(store)
            _make_3_cards(store)
            hits = svc.recall("Python list", limit=2)
            self.assertIsInstance(hits, list)
            self.assertEqual(len(hits), 2)
            for h in hits:
                self.assertIsInstance(h, dict)
                self.assertIn("card", h)
                self.assertIn("score", h)
        finally:
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    unittest.main()
