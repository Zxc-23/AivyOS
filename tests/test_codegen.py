"""代码生成服务测试（§10.1 / T5.1-T5.4）：parse→plan→generate→deliver 全链路。

- 本地后端零依赖
- Cline 适配：node 缺失时优雅降级（ClineUnavailable）
- MCP filesystem 交付（§10.1 阶段5）
- VibeCoding 工作流 local 执行器接入真实代码生成（T5.6/T5.7）
"""

import asyncio
import os
import shutil
import unittest

from aivyos_core.codegen import CodeGenService, LocalCodeGen, list_templates
from aivyos_core.mcp.servers.filesystem import FilesystemServer

from tests import _TMP, AivyTestCase


class TestCodeGenService(AivyTestCase):
    def setUp(self):
        self.ws = os.path.join(_TMP, "cg_ws")
        shutil.rmtree(self.ws, ignore_errors=True)
        self.svc = CodeGenService()  # 零依赖本地后端

    def test_plan_lists_files(self):
        spec = self.svc.parser.parse("做一个天气查询网页")
        plan = self.svc.plan(spec)
        self.assertTrue(plan.files)
        for f in plan.files:
            self.assertIn("path", f)
            self.assertIn("purpose", f)

    def test_generate_produces_files(self):
        spec = self.svc.parser.parse("写一个 python cli 工具")
        plan = self.svc.plan(spec)
        files = self.svc.generate(spec, plan)
        self.assertIn("main.py", files)
        self.assertTrue(files["main.py"].strip())

    def test_one_shot_delivers_to_workspace(self):
        spec = asyncio.run(self.svc.parse("做一个静态个人主页"))
        plan = self.svc.plan(spec)
        files = self.svc.generate(spec, plan)
        delivered = asyncio.run(self.svc.deliver(files, __import__("pathlib").Path(self.ws)))
        self.assertEqual(delivered["count"], len(files))
        for name in files:
            p = os.path.join(self.ws, name)
            self.assertTrue(os.path.exists(p), name)
            with open(p, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), files[name])

    def test_one_shot_full_pipeline(self):
        result = asyncio.run(self.svc.one_shot("做一个 python api 服务", __import__("pathlib").Path(self.ws)))
        self.assertEqual(result["spec"]["type"], "python-api")
        self.assertIn("main.py", result["files"])
        self.assertEqual(result["delivery"]["count"], len(result["files"]))

    def test_deliver_via_mcp_filesystem(self):
        # §10.1 阶段5：经 MCP filesystem fs_write 交付
        root = os.path.join(_TMP, "cg_mcp_root")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)
        fs = FilesystemServer([root])
        tools = {t.name: t for t in fs.tools()}
        svc = CodeGenService(fs_tool=tools["fs_write"].handler)
        files = {"sub/hello.txt": "hi"}
        delivered = asyncio.run(svc.deliver(files, __import__("pathlib").Path(self.ws)))
        self.assertEqual(delivered["via"], "mcp-filesystem")
        self.assertTrue(os.path.exists(os.path.join(root, "sub", "hello.txt")))


class TestClineAdapter(AivyTestCase):
    def test_cline_backend_selection_falls_back(self):
        # node/npx 缺失时：cline 后端抛 ClineUnavailable；create_codegen auto 降级本地
        from aivyos_core.codegen.cline_adapter import ClineSDKBackend, ClineUnavailable
        from aivyos_core.codegen.service import create_codegen

        try:
            backend = ClineSDKBackend(model="qwen2.5:3b")
        except ClineUnavailable:
            backend = LocalCodeGen()
        # 无论哪条路，都能产出真实骨架
        from aivyos_core.requirement import RequirementParser

        spec_obj = RequirementParser().parse("做一个 react 网页")
        plan = backend.plan(spec_obj)
        self.assertTrue(plan.files)

        svc = create_codegen({"codegen": {"backend": "auto"}})
        self.assertIsInstance(svc.backend, (LocalCodeGen, ClineSDKBackend))


class TestVibeCodingWithCodeGen(AivyTestCase):
    def test_local_executor_uses_real_codegen(self):
        from aivyos_core.workflow.workflows import build_vibe_coding_graph, stop_preview_server

        ws = os.path.join(_TMP, "ws_codegen")
        shutil.rmtree(ws, ignore_errors=True)
        state = None
        try:
            from aivyos_core.workflow.checkpointer import SqliteCheckpointer

            ck = SqliteCheckpointer(os.path.join(_TMP, "ck_codegen.db"))
            app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
            svc = CodeGenService()
            ctx = {
                "executor": "local",
                "workspace": ws,
                "codegen": svc,
                "build_command": "python -c \"import sys; sys.exit(0)\"",
                "preview": True,
            }
            state = asyncio.run(app.invoke({"user_request": "做一个天气查询网页"}, thread_id="wf_cg", ctx=ctx))
            # 真实解析 + 模板生成 + 交付
            self.assertEqual(state["spec"]["source"], "rule")
            self.assertEqual(state["spec"]["type"], "react-web-app")
            self.assertIn("天气查询", state["spec"]["title"])
            self.assertTrue(os.path.exists(os.path.join(ws, "index.html")))
            self.assertIn("local-template", state["note_generate"])
            self.assertFalse(state["build_failed"])
        finally:
            if state is not None:
                stop_preview_server(state)
            shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
