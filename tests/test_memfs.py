"""MemFS 测试（§8.1：类文件系统记忆，跨重启持久化）。"""

import os
import unittest

from aivyos_core.memfs import MemFSError, MemFS

from tests import _TMP, AivyTestCase


def memfs_root(name: str) -> str:
    path = os.path.join(_TMP, name)
    return path


class TestMemFS(AivyTestCase):
    def setUp(self):
        self.root = memfs_root("memfs_test")
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)
        self.mfs = MemFS(self.root)

    def test_defaults_created(self):
        self.assertTrue(os.path.exists(os.path.join(self.root, "facts.md")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "projects")))
        self.assertIn("facts.md", self.mfs.list())

    def test_write_read_append(self):
        self.mfs.write("user_prefs.md", "用户喜欢简洁回复", append=True)
        content = self.mfs.read("user_prefs.md")
        self.assertIn("用户喜欢简洁回复", content)
        self.assertIn("- [", content)  # 时间戳条目

    def test_remember_and_get_relevant(self):
        self.mfs.remember("用户喜欢喝咖啡", category="user_prefs.md")
        self.mfs.remember("用户讨厌雨天", category="user_prefs.md")
        hits = self.mfs.get_relevant("咖啡")
        self.assertTrue(any("咖啡" in h["text"] for h in hits))

    def test_path_traversal_blocked(self):
        with self.assertRaises(MemFSError):
            self.mfs.read("../secret.txt")
        with self.assertRaises(MemFSError):
            self.mfs.write("../escape.txt", "x")

    def test_persistence_across_reopen(self):
        self.mfs.remember("重启也要记住这个")
        mfs2 = MemFS(self.root)  # 模拟重启
        content = mfs2.read("user_prefs.md")
        self.assertIn("重启也要记住这个", content)

    def test_snapshot_restore_roundtrip(self):
        self.mfs.remember("快照内容甲", category="facts.md")
        snap = self.mfs.snapshot()
        self.assertIn("facts.md", snap["files"])
        # 重建
        mfs2 = MemFS(os.path.join(_TMP, "memfs_test2"))
        mfs2.restore(snap)
        self.assertIn("快照内容甲", mfs2.read("facts.md"))

    def test_remove(self):
        self.mfs.write("tmp_note.md", "临时")
        self.assertTrue(self.mfs.remove("tmp_note.md"))
        self.assertNotIn("tmp_note.md", self.mfs.list())


if __name__ == "__main__":
    unittest.main()
