"""简单记忆后端测试。"""

import asyncio
import os
import unittest

from aivyos_core.memory.simple import SimpleFileMemory

from tests import _TMP, AivyTestCase


class TestSimpleMemory(AivyTestCase):
    def setUp(self):
        self.path = os.path.join(_TMP, "mem_test.jsonl")
        if os.path.exists(self.path):
            os.remove(self.path)
        self.mem = SimpleFileMemory(self.path)

    def test_add_and_get_all(self):
        asyncio.run(self.mem.add("用户喜欢喝咖啡"))
        asyncio.run(self.mem.add("用户的猫叫咪咪"))
        hits = asyncio.run(self.mem.get_all())
        self.assertEqual(len(hits), 2)

    def test_search_relevance(self):
        asyncio.run(self.mem.add("用户喜欢喝咖啡"))
        asyncio.run(self.mem.add("用户每天九点起床"))
        hits = asyncio.run(self.mem.search("咖啡", top_k=5))
        self.assertTrue(hits)
        self.assertIn("咖啡", hits[0].text)
        self.assertGreater(hits[0].score, 0)

    def test_persistence_across_reopen(self):
        asyncio.run(self.mem.add("记住这个事实"))
        mem2 = SimpleFileMemory(self.path)  # 重新打开，模拟重启
        hits = asyncio.run(mem2.get_all())
        self.assertEqual(len(hits), 1)

    def test_search_empty_query(self):
        hits = asyncio.run(self.mem.search("", top_k=5))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
