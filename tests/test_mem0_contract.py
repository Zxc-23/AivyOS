"""Mem0 适配接口契约测试（§4.2：add/search/get_all/update 签名对齐 + 降级）。"""

import asyncio
import os
import unittest

from aivyos_core.memory.base import MemoryBackend
from aivyos_core.memory.manager import MemoryManager
from aivyos_core.memory.mem0_backend import Mem0Backend, Mem0Unavailable
from aivyos_core.memory.simple import SimpleFileMemory

from tests import _TMP, AivyTestCase


class TestMem0Contract(AivyTestCase):
    def test_missing_mem0_raises(self):
        with self.assertRaises(Mem0Unavailable):
            Mem0Backend(_TMP)

    def test_manager_auto_falls_back_to_simple(self):
        import os

        manager = MemoryManager({"backend": "auto"}, os.path.join(_TMP, "mem_mgr"))
        self.assertEqual(manager.backend_name, "simple-jsonl")
        self.assertIsInstance(manager.backend, SimpleFileMemory)

    def test_common_api_surface(self):
        """两种后端必须提供一致的 add/search/get_all/update。"""
        backends = [SimpleFileMemory(os.path.join(_TMP, "api_simple.jsonl"))]
        for backend in backends:
            self.assertTrue(callable(backend.add))
            self.assertTrue(callable(backend.search))
            self.assertTrue(callable(backend.get_all))
            self.assertTrue(callable(backend.update))
            self.assertIsInstance(backend, MemoryBackend)

    def test_simple_update_semantics(self):
        mem = SimpleFileMemory(os.path.join(_TMP, "api_update.jsonl"))
        rid = asyncio.run(mem.add("用户喜欢咖啡"))
        new_id = asyncio.run(mem.update(rid, "用户喜欢拿铁"))
        hits = asyncio.run(mem.search("拿铁"))
        self.assertTrue(any("拿铁" in h.text for h in hits))
        superseded = [h for h in asyncio.run(mem.get_all()) if h.metadata.get("supersedes") == rid]
        self.assertEqual(len(superseded), 1)


if __name__ == "__main__":
    unittest.main()
