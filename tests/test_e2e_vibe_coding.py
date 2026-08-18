"""Phase 2 端到端 Vibe Coding 联调测试（§10 一句话做软件 + §11 自动预览 + §7.4 工作流）。

覆盖完整链路：需求解析 → 规划 → 生成 → 交付（工作区）→ 构建 → 预览（dev server）
→ 浏览器监控（console/网络）→ AI 视觉验证 → 保存记忆。
"""

import asyncio
import os
import shutil
import unittest

from aivyos_core.codegen import CodeGenService
from aivyos_core.codegen.preview import PreviewController
from aivyos_core.mcp.servers.browser import BrowserServer
from aivyos_core.workflow.checkpointer import SqliteCheckpointer
from aivyos_core.workflow.workflows import build_vibe_coding_graph, stop_preview_server

from tests import AivyTestCase, _TMP


class TestVibeCodingE2E(AivyTestCase):
    def _run(self, ws, memfs, request="做一个待办事项管理网页", extra_ctx=None):
        import uuid

        ck = SqliteCheckpointer(os.path.join(_TMP, "ck_e2e_" + uuid.uuid4().hex[:6] + ".db"))
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
        ctx = {
            "executor": "local",
            "workspace": ws,
            "codegen": CodeGenService(),
            "preview_controller": PreviewController(browser_server=BrowserServer()),
            "memfs": memfs,
            "build_command": "python -c \"import sys; sys.exit(0)\"",
            "preview": True,
        }
        if extra_ctx:
            ctx.update(extra_ctx)
        return asyncio.run(app.invoke({"user_request": request}, thread_id="wf_e2e", ctx=ctx))

    def test_full_vibe_coding_chain(self):
        from aivyos_core.memfs import MemFS

        ws = os.path.join(_TMP, "e2e_vibe_ws")
        mem = os.path.join(_TMP, "e2e_vibe_mem")
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(mem, ignore_errors=True)
        memfs = MemFS(mem)
        state = None
        try:
            state = self._run(ws, memfs)
            # 1) 需求解析（真实 rule）
            self.assertEqual(state["spec"]["source"], "rule")
            self.assertTrue(state["spec"]["title"])
            # 2) 生成 + 交付到工作区
            self.assertTrue(state["files"])
            self.assertTrue(os.path.exists(os.path.join(ws, "index.html")), "index.html 应写入工作区")
            # 3) 构建通过（exit 0）
            self.assertFalse(state["build_failed"])
            # 4) 预览：dev server 已启动且通过验证（无 console 错误 → ok）
            self.assertTrue(state["preview_ok"])
            self.assertIn("127.0.0.1", state["preview_url"])
            self.assertIn("preview_monitor", state)
            self.assertIn("preview_visual", state)
            # 5) 保存记忆
            self.assertIn("preview_monitor", state)
            self.assertIn("preview_visual", state)
        finally:
            if state is not None:
                stop_preview_server(state)
            shutil.rmtree(ws, ignore_errors=True)
            shutil.rmtree(mem, ignore_errors=True)

    def test_memory_saved_to_memfs(self):
        from aivyos_core.memfs import MemFS

        ws = os.path.join(_TMP, "e2e_vibe_ws2")
        mem = os.path.join(_TMP, "e2e_vibe_mem2")
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(mem, ignore_errors=True)
        memfs = MemFS(mem)
        state = None
        try:
            state = self._run(ws, memfs)
            # §10.1 阶段 7：Mem0/MemFS 记录"完成项目"
            tasks = memfs.read("tasks.md")
            self.assertIn("完成项目", tasks)
        finally:
            if state is not None:
                stop_preview_server(state)
            shutil.rmtree(ws, ignore_errors=True)
            shutil.rmtree(mem, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
