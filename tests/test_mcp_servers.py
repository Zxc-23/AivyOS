"""MCP Server 测试：filesystem 白名单 / shell / code-exec / office / search。"""

import asyncio
import os
import shutil
import unittest
import zipfile

from aivyos_core.mcp.servers.code_exec import CodeExecServer
from aivyos_core.mcp.servers.filesystem import FilesystemServer
from aivyos_core.mcp.servers.office import OfficeServer
from aivyos_core.mcp.servers.search import SearchServer
from aivyos_core.mcp.servers.shell import ShellServer

from tests import _TMP, AivyTestCase


class TestFilesystemServer(AivyTestCase):
    def setUp(self):
        self.root = os.path.join(_TMP, "mcp_fs")
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(self.root)
        self.srv = FilesystemServer([os.path.join(_TMP, "mcp_fs")])
        self.tools = {t.name: t for t in self.srv.tools()}

    def test_write_read(self):
        r = asyncio.run(self.tools["fs_write"].handler({"path": "a.txt", "content": "hello"}))
        self.assertTrue(r.ok)
        r2 = asyncio.run(self.tools["fs_read"].handler({"path": "a.txt"}))
        self.assertEqual(r2.content, "hello")

    def test_path_escape_blocked(self):
        r = asyncio.run(self.tools["fs_read"].handler({"path": "../secret.txt"}))
        self.assertFalse(r.ok)
        self.assertIn("越界", r.error)

    def test_list_and_rm(self):
        asyncio.run(self.tools["fs_write"].handler({"path": "dir/b.txt", "content": "x"}))
        listed = asyncio.run(self.tools["fs_list"].handler({"path": "."}))
        self.assertIn("dir/b.txt", listed.data["files"])
        rm = asyncio.run(self.tools["fs_rm"].handler({"path": "dir"}))
        self.assertTrue(rm.ok)
        self.assertFalse(os.path.exists(os.path.join(self.root, "dir")))

    def test_permissions(self):
        from aivyos_core.mcp.types import PermissionLevel

        self.assertEqual(self.tools["fs_read"].permission, PermissionLevel.L0)
        self.assertEqual(self.tools["fs_write"].permission, PermissionLevel.L2)
        self.assertEqual(self.tools["fs_rm"].permission, PermissionLevel.L3)


class TestShellServer(AivyTestCase):
    def test_run_command(self):
        srv = ShellServer(timeout_s=10)
        tool = srv.tools()[0]
        r = asyncio.run(tool.handler({"command": "python -c \"print(42)\""}))
        self.assertTrue(r.ok)
        self.assertIn("42", r.content)
        self.assertEqual(r.data["exit_code"], 0)

    def test_timeout(self):
        srv = ShellServer(timeout_s=1)
        tool = srv.tools()[0]
        r = asyncio.run(tool.handler({"command": "python -c \"import time; time.sleep(10)\""}))
        self.assertFalse(r.ok)
        self.assertIn("超时", r.error)

    def test_mrtr_permission(self):
        from aivyos_core.mcp.types import PermissionLevel

        self.assertEqual(ShellServer().tools()[0].permission, PermissionLevel.L2)


class TestCodeExecServer(AivyTestCase):
    def setUp(self):
        self.scratch = os.path.join(_TMP, "mcp_exec")
        shutil.rmtree(self.scratch, ignore_errors=True)
        self.srv = CodeExecServer(os.path.join(_TMP, "mcp_exec"), docker_image=None)

    def test_run_python(self):
        tool = self.srv.tools()[0]
        r = asyncio.run(tool.handler({"code": "print(1 + 1)"}))
        self.assertTrue(r.ok)
        self.assertIn("2", r.content)
        self.assertEqual(r.data["sandbox"], "subprocess")

    def test_error_captured(self):
        tool = self.srv.tools()[0]
        r = asyncio.run(tool.handler({"code": "raise ValueError('boom')"}))
        self.assertFalse(r.ok)
        self.assertIn("boom", r.content)


class TestOfficeServer(AivyTestCase):
    def setUp(self):
        self.out = os.path.join(_TMP, "mcp_office")
        shutil.rmtree(self.out, ignore_errors=True)
        self.srv = OfficeServer(self.out)
        self.tools = {t.name: t for t in self.srv.tools()}

    def test_docx_valid_zip(self):
        r = asyncio.run(self.tools["office_docx"].handler({"text": "测试文档", "name": "t.docx"}))
        self.assertTrue(r.ok)
        with zipfile.ZipFile(r.data["path"]) as z:
            self.assertIn("word/document.xml", z.namelist())

    def test_xlsx_valid(self):
        r = asyncio.run(self.tools["office_xlsx"].handler({"cells": {"A1": "姓名", "B1": "年龄"}}))
        self.assertTrue(r.ok)
        with zipfile.ZipFile(r.data["path"]) as z:
            self.assertIn("xl/workbook.xml", z.namelist())

    def test_pptx_valid(self):
        r = asyncio.run(self.tools["office_pptx"].handler({"text": "标题"}))
        self.assertTrue(r.ok)
        with zipfile.ZipFile(r.data["path"]) as z:
            self.assertIn("ppt/slides/slide1.xml", z.namelist())


class TestSearchServer(AivyTestCase):
    def test_mock_fallback(self):
        srv = SearchServer()  # 无 searxng_url → mock
        tool = srv.tools()[0]
        r = asyncio.run(tool.handler({"query": "天气"}))
        self.assertTrue(r.ok)
        self.assertEqual(r.data["backend"], "mock")


if __name__ == "__main__":
    unittest.main()
