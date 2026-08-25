"""向量数据库模块单元测试（TDD，14 tests）。"""

import os
import shutil
import tempfile
import unittest

from tests import AivyTestCase, _TMP


def _chroma_available() -> bool:
    """检测 chromadb 是否已安装。"""
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


class TestMockInMemoryVectorStore(AivyTestCase):
    """MockInMemoryVectorStore 测试（9 tests）。"""

    def setUp(self):
        from aivyos_core.vector import MockInMemoryVectorStore
        self.store = MockInMemoryVectorStore()

    def test_upsert_3_query_hello_top_2_returns_2_ids_in_set(self):
        """upsert 3 条，query 'hello' top 2，返回 2 条且 id 在集合中。"""
        import asyncio
        items = [
            {"id": "d1", "text": "hello world", "metadata": {"tag": "a"}},
            {"id": "d2", "text": "hello python", "metadata": {"tag": "b"}},
            {"id": "d3", "text": "goodbye java", "metadata": {"tag": "c"}},
        ]
        asyncio.run(self.store.upsert_batch(items))
        results = asyncio.run(self.store.query("hello", top_k=2))
        self.assertEqual(len(results), 2)
        ids = {r.id for r in results}
        self.assertTrue(ids.issubset({"d1", "d2", "d3"}))

    def test_delete_id_disappears(self):
        """delete 后 id 消失，query 不再返回。"""
        import asyncio
        items = [
            {"id": "d1", "text": "hello world", "metadata": {}},
            {"id": "d2", "text": "hello python", "metadata": {}},
        ]
        asyncio.run(self.store.upsert_batch(items))
        ok = asyncio.run(self.store.delete("d1"))
        self.assertTrue(ok)
        results = asyncio.run(self.store.query("hello", top_k=5))
        ids = {r.id for r in results}
        self.assertNotIn("d1", ids)
        self.assertIn("d2", ids)

    def test_score_in_0_1_range(self):
        """query 返回的 score 全部在 [0, 1] 区间。"""
        import asyncio
        items = [
            {"id": "d1", "text": "apple banana", "metadata": {}},
            {"id": "d2", "text": "cat dog", "metadata": {}},
            {"id": "d3", "text": "hello world", "metadata": {}},
        ]
        asyncio.run(self.store.upsert_batch(items))
        results = asyncio.run(self.store.query("apple", top_k=3))
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertGreaterEqual(r.score, 0.0)
            self.assertLessEqual(r.score, 1.0)

    def test_cosine_self_is_1(self):
        """完全相同文本的余弦相似度应接近 1。"""
        import asyncio
        text = "this is a unique test sentence for self similarity"
        asyncio.run(self.store.upsert_batch([
            {"id": "d1", "text": text, "metadata": {}}
        ]))
        results = asyncio.run(self.store.query(text, top_k=1))
        self.assertEqual(len(results), 1)
        self.assertGreaterEqual(results[0].score, 0.99)

    def test_empty_query_returns_empty_list(self):
        """空库 query 返回空列表。"""
        import asyncio
        results = asyncio.run(self.store.query("anything", top_k=5))
        self.assertEqual(results, [])

    def test_upsert_overwrite_same_id_updates_metadata(self):
        """同 id upsert 应覆盖（更新 metadata）。"""
        import asyncio
        asyncio.run(self.store.upsert_batch([
            {"id": "d1", "text": "hello", "metadata": {"v": 1}}
        ]))
        asyncio.run(self.store.upsert_batch([
            {"id": "d1", "text": "hello", "metadata": {"v": 2}}
        ]))
        results = asyncio.run(self.store.query("hello", top_k=1))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata.get("v"), 2)

    def test_upsert_batch_empty_list_noop(self):
        """upsert_batch 空列表不抛异常。"""
        import asyncio
        try:
            asyncio.run(self.store.upsert_batch([]))
        except Exception as e:
            self.fail(f"upsert_batch([]) raised {type(e).__name__}: {e}")

    def test_get_abc_then_c_def_result_len_ok(self):
        """先 upsert abc 3 条，再 upsert cdef 3 条（覆盖 c），最终 5 条。"""
        import asyncio
        asyncio.run(self.store.upsert_batch([
            {"id": "a", "text": "text a", "metadata": {}},
            {"id": "b", "text": "text b", "metadata": {}},
            {"id": "c", "text": "text c", "metadata": {}},
        ]))
        asyncio.run(self.store.upsert_batch([
            {"id": "c", "text": "text c new", "metadata": {"overwritten": True}},
            {"id": "d", "text": "text d", "metadata": {}},
            {"id": "e", "text": "text e", "metadata": {}},
            {"id": "f", "text": "text f", "metadata": {}},
        ]))
        results = asyncio.run(self.store.query("text", top_k=10))
        self.assertEqual(len(results), 6)
        ids = {r.id for r in results}
        self.assertEqual(ids, {"a", "b", "c", "d", "e", "f"})
        c_meta = next(r.metadata for r in results if r.id == "c")
        self.assertTrue(c_meta.get("overwritten"))

    def test_metadata_is_preserved_in_result(self):
        """metadata 字段完整保存在 QueryResult 中。"""
        import asyncio
        meta = {"author": "alice", "year": 2024, "tags": ["nlp", "ai"]}
        asyncio.run(self.store.upsert_batch([
            {"id": "d1", "text": "metadata test", "metadata": meta}
        ]))
        results = asyncio.run(self.store.query("metadata test", top_k=1))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata, meta)


@unittest.skipIf(not _chroma_available(), "chroma 未装")
class TestChromaVectorStore(AivyTestCase):
    """ChromaVectorStore 测试（5 tests，chroma 未装自动 skip）。"""

    def setUp(self):
        from aivyos_core.vector import ChromaVectorStore
        self.store = ChromaVectorStore(
            collection_name="test_aivyos_knowledge",
            in_memory=True,
        )

    def test_smoke_upsert_query_delete_smoke(self):
        """冒烟测试：upsert/query/delete 不抛异常即通过。"""
        import asyncio
        asyncio.run(self.store.upsert_batch([
            {"id": "c1", "text": "hello chroma", "metadata": {}},
            {"id": "c2", "text": "goodbye chroma", "metadata": {}},
        ]))
        asyncio.run(self.store.query("hello", top_k=2))
        asyncio.run(self.store.delete("c1"))

    def test_upsert_5_query_top3_returns_3(self):
        """upsert 5 条，query top 3 返回 3 条。"""
        import asyncio
        items = [
            {"id": f"c{i}", "text": f"document number {i} about topic", "metadata": {"i": i}}
            for i in range(5)
        ]
        asyncio.run(self.store.upsert_batch(items))
        results = asyncio.run(self.store.query("document number", top_k=3))
        self.assertEqual(len(results), 3)

    def test_score_after_normalize_in_0_1(self):
        """chroma L2 distance 归一化后的 score 在 [0,1]。"""
        import asyncio
        items = [
            {"id": "s1", "text": "foo bar baz", "metadata": {}},
            {"id": "s2", "text": "qux quux corge", "metadata": {}},
            {"id": "s3", "text": "alpha beta gamma", "metadata": {}},
        ]
        asyncio.run(self.store.upsert_batch(items))
        results = asyncio.run(self.store.query("foo bar", top_k=3))
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertGreaterEqual(r.score, 0.0)
            self.assertLessEqual(r.score, 1.0)

    def test_delete_after_query_returns_not(self):
        """delete 后再次 query 不再出现该 id。"""
        import asyncio
        asyncio.run(self.store.upsert_batch([
            {"id": "x1", "text": "keep this one", "metadata": {}},
            {"id": "x2", "text": "delete this one", "metadata": {}},
        ]))
        asyncio.run(self.store.delete("x2"))
        results = asyncio.run(self.store.query("this one", top_k=10))
        ids = {r.id for r in results}
        self.assertIn("x1", ids)
        self.assertNotIn("x2", ids)

    def test_persist_dir_works(self):
        """persist_dir 持久化：close 后重开仍能查到。"""
        import asyncio
        persist_path = os.path.join(_TMP, "chroma_persist_test")
        shutil.rmtree(persist_path, ignore_errors=True)
        from aivyos_core.vector import ChromaVectorStore

        store1 = ChromaVectorStore(
            collection_name="persist_col",
            in_memory=False,
            persist_dir=persist_path,
        )
        asyncio.run(store1.upsert_batch([
            {"id": "p1", "text": "persisted data here", "metadata": {"saved": True}},
        ]))
        del store1

        store2 = ChromaVectorStore(
            collection_name="persist_col",
            in_memory=False,
            persist_dir=persist_path,
        )
        results = asyncio.run(store2.query("persisted data", top_k=5))
        self.assertGreaterEqual(len(results), 1)
        ids = {r.id for r in results}
        self.assertIn("p1", ids)


if __name__ == "__main__":
    unittest.main()
