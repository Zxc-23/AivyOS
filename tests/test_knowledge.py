"""知识卡片系统测试：卡片模型/存储 CRUD/提取/相似度/版本/备份/服务编排。"""

import asyncio
import os
import shutil
import unittest
from pathlib import Path

from aivyos_core.knowledge.card import KnowledgeCard
from aivyos_core.knowledge.extract import KnowledgeExtractor
from aivyos_core.knowledge.service import KnowledgeService
from aivyos_core.knowledge.store import KnowledgeStore

from tests import AivyTestCase, _TMP


class TestKnowledgeCard(AivyTestCase):
    def test_defaults_and_version(self):
        c = KnowledgeCard(id="c1", title="测试")
        self.assertEqual(c.version, 1)
        self.assertEqual(c.favorite, False)
        self.assertTrue(c.created_at)
        self.assertEqual(c.versions, [])

    def test_update_records_version(self):
        c = KnowledgeCard(id="c1", title="旧标题")
        c.update(title="新标题", content="内容")
        self.assertEqual(c.version, 2)
        self.assertEqual(len(c.versions), 1)
        self.assertEqual(c.versions[0]["title"], "旧标题")  # 历史记录旧值
        self.assertEqual(c.updated_at >= c.created_at, True)

    def test_update_no_change_no_version(self):
        c = KnowledgeCard(id="c1", title="标题", content="内容")
        ok = c.update(title="标题")  # 无实际变化
        self.assertFalse(ok)
        self.assertEqual(c.version, 1)

    def test_to_dict_roundtrip(self):
        c = KnowledgeCard(id="c1", title="T", tags=["a", "b"], favorite=True)
        d = c.to_dict()
        from aivyos_core.knowledge.card import card_from_dict

        c2 = card_from_dict(d)
        self.assertEqual(c2.title, "T")
        self.assertEqual(c2.tags, ["a", "b"])
        self.assertTrue(c2.favorite)


class TestKnowledgeStore(AivyTestCase):
    def setUp(self):
        self.path = Path(_TMP) / "knowledge_test.jsonl"
        if self.path.exists():
            self.path.unlink()
        self.store = KnowledgeStore(self.path)

    def tearDown(self):
        if self.path.exists():
            self.path.unlink()

    def test_crud(self):
        c = self.store.create(title="天气偏好", content="喜欢晴天", category="个人偏好", tags=["天气"])
        self.assertTrue(c.id)
        got = self.store.get(c.id)
        self.assertEqual(got.title, "天气偏好")
        self.assertTrue(self.store.update(c.id, content="喜欢晴天和微风"))
        self.assertEqual(self.store.get(c.id).content, "喜欢晴天和微风")
        self.assertEqual(self.store.get(c.id).version, 2)
        self.assertTrue(self.store.delete(c.id))
        self.assertIsNone(self.store.get(c.id))

    def test_favorite_toggle(self):
        c = self.store.create(title="t")
        self.store.toggle_favorite(c.id)
        self.assertTrue(self.store.get(c.id).favorite)
        self.store.toggle_favorite(c.id)
        self.assertFalse(self.store.get(c.id).favorite)

    def test_filter_and_search(self):
        self.store.create(title="咖啡偏好", content="每天一杯", category="个人偏好", tags=["咖啡", "习惯"])
        self.store.create(title="Python 定义", content="解释型语言", category="概念定义", tags=["编程"])
        self.assertEqual(len(self.store.filter(category="个人偏好")), 1)
        self.assertEqual(len(self.store.filter(tag="编程")), 1)
        hits = self.store.search("咖啡")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].title, "咖啡偏好")
        self.assertIn("个人偏好", self.store.categories())
        self.assertIn("咖啡", self.store.all_tags())

    def test_sort_modes(self):
        a = self.store.create(title="a", content="x")
        b = self.store.create(title="b", content="y")
        self.store.toggle_favorite(b.id)
        # favorite 排序：收藏在前
        fav = self.store.list_all(sort="favorite")
        self.assertEqual(fav[0].id, b.id)

    def test_find_similar(self):
        self.store.create(title="项目管理", content="使用敏捷开发方法管理项目进度", category="知识总结")
        hits = self.store.find_similar("项目如何管理进度", limit=3)
        self.assertTrue(len(hits) >= 1)
        self.assertGreater(hits[0]["score"], 0)
        # usage 增加
        self.assertGreater(self.store.get(hits[0]["card"]["id"]).usage, 0)

    def test_link_unlink(self):
        a = self.store.create(title="a")
        b = self.store.create(title="b")
        self.assertTrue(self.store.link(a.id, b.id))
        self.assertIn(b.id, self.store.get(a.id).links)
        self.assertIn(a.id, self.store.get(b.id).links)
        self.assertTrue(self.store.unlink(a.id, b.id))
        self.assertNotIn(b.id, self.store.get(a.id).links)

    def test_backup_restore(self):
        self.store.create(title="知识1", content="内容1")
        self.store.create(title="知识2", content="内容2")
        backup = Path(_TMP) / "knowledge_backup.json"
        self.store.export_backup(backup)
        # 清空后恢复
        self.store.clear()
        self.assertEqual(self.store.stats()["total"], 0)
        n = self.store.import_backup(backup)
        self.assertEqual(n, 2)
        self.assertEqual(self.store.stats()["total"], 2)

    def test_persistence_across_reload(self):
        self.store.create(title="持久化测试", content="重启后仍在")
        store2 = KnowledgeStore(self.path)
        self.assertEqual(store2.stats()["total"], 1)
        self.assertEqual(store2.list_all()[0].title, "持久化测试")


class TestKnowledgeExtractor(AivyTestCase):
    def test_rule_extract_preference(self):
        ex = KnowledgeExtractor()
        r = ex._rule_extract("我喜欢喝拿铁咖啡")
        self.assertIsNotNone(r)
        self.assertEqual(r["category"], "个人偏好")
        self.assertIn("拿铁", r["content"])

    def test_rule_extract_definition(self):
        ex = KnowledgeExtractor()
        r = ex._rule_extract("敏捷开发的意思是快速迭代")
        self.assertIsNotNone(r)
        self.assertEqual(r["category"], "概念定义")

    def test_no_knowledge_returns_none(self):
        ex = KnowledgeExtractor()
        r = ex._rule_extract("今天天气不错")
        self.assertIsNone(r)
        r2 = asyncio.run(ex.extract("嗯"))
        self.assertIsNone(r2)

    def test_rule_extract_remember(self):
        """'记得'句式（习惯/日程）应沉淀（修复漏抓）。"""
        ex = KnowledgeExtractor()
        r = ex._rule_extract("记得每周五下午三点开项目周会")
        self.assertIsNotNone(r)
        self.assertIn("每周五", r["content"])
        r2 = ex._rule_extract("记住要检查邮箱")
        self.assertIsNotNone(r2)

    def test_summarize(self):
        s = KnowledgeExtractor.summarize("这是第一句。这是第二句很长很长的内容需要被截断处理")
        self.assertLessEqual(len(s), 40)
        self.assertTrue(s.endswith("。") or len(s) == 40)


class TestKnowledgeService(AivyTestCase):
    def setUp(self):
        self.path = Path(_TMP) / "knowledge_svc.jsonl"
        if self.path.exists():
            self.path.unlink()
        self.svc = KnowledgeService(KnowledgeStore(self.path))

    def tearDown(self):
        if self.path.exists():
            self.path.unlink()

    def test_ingest_creates_card(self):
        result = asyncio.run(self.svc.ingest("我喜欢喝美式咖啡"))
        self.assertEqual(result["action"], "create")
        self.assertEqual(result["card"]["category"], "个人偏好")
        # 再次摄入相似内容 → 更新（去重）
        result2 = asyncio.run(self.svc.ingest("我喜欢喝美式咖啡，不加糖"))
        self.assertEqual(result2["action"], "update")

    def test_ingest_skip_non_knowledge(self):
        result = asyncio.run(self.svc.ingest("你好呀"))
        self.assertIsNone(result)

    def test_recall(self):
        self.svc.create(title="项目管理", content="敏捷开发方法管理项目进度")
        hits = self.svc.recall("项目进度如何管理", limit=2)
        self.assertTrue(hits)

    def test_graph(self):
        a = self.svc.create(title="a", content="x")
        b = self.svc.create(title="b", content="y")
        self.svc.link(a.id, b.id)
        g = self.svc.graph()
        self.assertEqual(len(g["nodes"]), 2)
        self.assertEqual(len(g["edges"]), 1)
        self.assertEqual(g["edges"][0]["source"], a.id)

    def test_export_card(self):
        c = self.svc.create(title="导出测试", content="内容", category="要点", tags=["t1"])
        md = self.svc.export_card(c.id, "markdown")
        self.assertEqual(md["format"], "markdown")
        self.assertIn("# 导出测试", md["text"])
        js = self.svc.export_card(c.id, "json")
        self.assertEqual(js["format"], "json")
        self.assertIn('"title"', js["text"])
        bad = self.svc.export_card("nonexistent", "markdown")
        self.assertIn("error", bad)


if __name__ == "__main__":
    unittest.main()
