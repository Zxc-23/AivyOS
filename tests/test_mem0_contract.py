"""MemoryBackend 合约接口测试：覆盖 SimpleFileMemory / Mem0Backend / MemoryManager.try_extract。"""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from aivyos_core.memory.base import MemoryBackend, MemoryHit
from aivyos_core.memory.manager import MemoryManager
from aivyos_core.memory.mem0_backend import Mem0Backend, Mem0Unavailable
from aivyos_core.memory.simple import SimpleFileMemory


def _mem0_available() -> bool:
    """检测 mem0 包是否可用且可初始化（用于 skipIf 条件）。"""
    try:
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            Mem0Backend(persist_path=tmp)
            return True
        except Mem0Unavailable:
            return False
        except Exception:
            return False
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        return False


_MEM0_OK = _mem0_available()


class TestSimpleFileMemoryContract(unittest.TestCase):
    """SimpleFileMemory 后端合约测试（7 tests）。"""

    def _make(self, tmp_path: Path) -> SimpleFileMemory:
        """构造一个新的 SimpleFileMemory 实例。"""
        return SimpleFileMemory(tmp_path / "m.jsonl")

    def test_add_returns_nonempty_id(self):
        """T1：add 返回非空记忆 id。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            rid = asyncio.run(mem.add("我叫小明"))
            self.assertIsInstance(rid, str)
            self.assertGreater(len(rid), 0)

    def test_search_matching_word_returns_at_least_1(self):
        """T2：关键词匹配的 search 至少返回 1 条。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            asyncio.run(mem.add("喜欢吃苹果和香蕉"))
            hits = asyncio.run(mem.search("喜欢苹果", top_k=5))
            self.assertGreaterEqual(len(hits), 1)

    def test_search_irrelevant_query_returns_0(self):
        """T3：无关查询的 search 返回 0 条。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            asyncio.run(mem.add("今天天气真好"))
            hits = asyncio.run(mem.search("python 编程", top_k=5))
            self.assertEqual(len(hits), 0)

    def test_get_all_after_3_adds_returns_3_items(self):
        """T4：add 3 条后 get_all 返回 3 条记录。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            asyncio.run(mem.add("第一条"))
            asyncio.run(mem.add("第二条"))
            asyncio.run(mem.add("第三条"))
            all_hits = asyncio.run(mem.get_all())
            self.assertEqual(len(all_hits), 3)

    def test_metadata_preserved_in_hit(self):
        """T5：metadata 在 search 结果中完整保留。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            asyncio.run(mem.add(text="x", metadata={"user": "alice", "thread": "123"}))
            hits = asyncio.run(mem.search("x"))
            self.assertGreaterEqual(len(hits), 1)
            hit = hits[0]
            self.assertEqual(hit.metadata.get("user"), "alice")
            self.assertEqual(hit.metadata.get("thread"), "123")

    def test_update_returns_new_id_and_appends_supersedes(self):
        """T6：update 返回新 id 且追加记录 metadata.supersedes 指向旧 id，或抛 NotImplementedError。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            id_old = asyncio.run(mem.add("v1"))
            try:
                id_new = asyncio.run(mem.update(id_old, "v2"))
                self.assertNotEqual(id_new, id_old)
                all_hits = asyncio.run(mem.get_all())
                found = any(h.metadata.get("supersedes") == id_old for h in all_hits)
                self.assertTrue(found, "未找到 supersedes 标记的更新记录")
            except NotImplementedError:
                pass

    def test_empty_text_still_adds(self):
        """T7：空文本 add 不抛异常（search 查不到属正常）。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            rid = asyncio.run(mem.add(""))
            self.assertIsInstance(rid, str)
            self.assertGreater(len(rid), 0)


@unittest.skipIf(not _MEM0_OK, "mem0 未安装或初始化失败")
class TestMem0BackendContract(unittest.TestCase):
    """Mem0Backend 后端合约测试（4 tests，mem0 不可用时全 skip）。"""

    def _make(self, tmp_path: Path) -> Mem0Backend:
        """构造一个新的 Mem0Backend 实例。"""
        return Mem0Backend(persist_path=str(tmp_path / "memory_db"))

    def test_mem0_add_search_roundtrip(self):
        """M1：mem0 add 后 search 可回检索到（roundtrip）。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            rid = asyncio.run(mem.add("我喜欢咖啡"))
            self.assertGreater(len(rid), 0)
            hits = asyncio.run(mem.search("喝咖啡", top_k=3))
            self.assertGreaterEqual(len(hits), 1)

    def test_mem0_get_all_has_added_item(self):
        """M2：mem0 get_all 至少包含一条已 add 的文本。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            asyncio.run(mem.add("记忆测试 x"))
            all_hits = asyncio.run(mem.get_all())
            self.assertGreaterEqual(len(all_hits), 1)
            self.assertTrue(any("记忆测试 x" in h.text for h in all_hits))

    def test_mem0_metadata_preserved(self):
        """M3：mem0 metadata 在 search 结果中保留。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            asyncio.run(mem.add(text="y", metadata={"user": "bob"}))
            hits = asyncio.run(mem.search("y"))
            self.assertGreaterEqual(len(hits), 1)
            self.assertEqual(hits[0].metadata.get("user"), "bob")

    def test_mem0_update(self):
        """M4：mem0 update 正常执行或抛 NotImplementedError（均算 pass）。"""
        with tempfile.TemporaryDirectory() as td:
            mem = self._make(Path(td))
            id_old = asyncio.run(mem.add("old text"))
            try:
                id_new = asyncio.run(mem.update(id_old, "new text"))
                self.assertIsInstance(id_new, str)
                self.assertGreater(len(id_new), 0)
            except NotImplementedError:
                pass


class TestMemoryManagerExtract(unittest.TestCase):
    """MemoryManager.try_extract 规则抽取测试（3 tests）。"""

    def test_rules_extract_我叫_触发记忆(self):
        """E1：rules 模式下含"我叫"触发自动抽取并写入记忆。"""
        with tempfile.TemporaryDirectory() as td:
            cfg = {"backend": "simple", "auto_extract": True, "extract_backend": "rules"}
            mgr = MemoryManager(cfg=cfg, home=Path(td), router=None)
            result = asyncio.run(mgr.try_extract("我叫小红，喜欢茶", metadata={}))
            self.assertIsNotNone(result)
            all_hits = asyncio.run(mgr.get_all())
            self.assertGreaterEqual(len(all_hits), 1)
            self.assertTrue(any("我叫小红" in h.text for h in all_hits))

    def test_rules_extract_寒暄_不触发(self):
        """E2：寒暄类文本（今天天气不错啊）不触发抽取，返回 None。"""
        with tempfile.TemporaryDirectory() as td:
            cfg = {"backend": "simple", "auto_extract": True, "extract_backend": "rules"}
            mgr = MemoryManager(cfg=cfg, home=Path(td), router=None)
            result = asyncio.run(mgr.try_extract("今天天气不错啊", metadata={}))
            self.assertIsNone(result)

    def test_disabled_auto_extract_never_extracts(self):
        """E3：auto_extract=False 时即使含"我叫"也不抽取，返回 None。"""
        with tempfile.TemporaryDirectory() as td:
            cfg = {"backend": "simple", "auto_extract": False, "extract_backend": "rules"}
            mgr = MemoryManager(cfg=cfg, home=Path(td), router=None)
            result = asyncio.run(mgr.try_extract("我叫张三", metadata={}))
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
