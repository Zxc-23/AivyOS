"""协作模板测试：串行/并行编排、短路、未知模板。"""

import asyncio
import unittest
from unittest import mock

from tests import AivyTestCase
from aivyos_core.workbench.models import AgentResult
from aivyos_core.workbench.templates import run_template


def _ok(agent, output):
    return AgentResult(agent=agent, ok=True, output=output, exit_code=0, elapsed_s=0.1)


def _fail(agent, error):
    return AgentResult(agent=agent, ok=False, error=error, elapsed_s=0.1)


class TestTemplates(AivyTestCase):
    def test_implement_then_review_chain(self):
        """Claude 实现 → Codex 审查：审查 prompt 含实现输出，两步全记录。"""
        claude = mock.AsyncMock(return_value=_ok("claude", "实现了天气网页"))
        codex = mock.AsyncMock(return_value=_ok("codex", "审查通过，建议补测试"))
        r = asyncio.run(run_template("implement_then_review", "写天气网页", claude, codex))
        self.assertTrue(r["ok"])
        self.assertEqual([s["name"] for s in r["steps"]], ["claude 实现", "codex 审查"])
        codex_prompt = codex.call_args.args[0]
        self.assertIn("实现了天气网页", codex_prompt)

    def test_implement_then_review_short_circuit(self):
        """Claude 失败 → 不调 Codex，模板失败。"""
        claude = mock.AsyncMock(return_value=_fail("claude", "CLI 不可用"))
        codex = mock.AsyncMock()
        r = asyncio.run(run_template("implement_then_review", "x", claude, codex))
        self.assertFalse(r["ok"])
        codex.assert_not_awaited()
        self.assertEqual(len(r["steps"]), 1)
        self.assertIn("CLI 不可用", r["error"])

    def test_parallel_design_fusion(self):
        """双模型并行 → Codex 融合 prompt 含双方输出，三步全记录。"""
        claude = mock.AsyncMock(return_value=_ok("claude", "方案A：微服务"))
        codex = mock.AsyncMock(side_effect=[_ok("codex", "方案B：单体"), _ok("codex", "【共识】...【分歧】...")])
        r = asyncio.run(run_template("parallel_design", "架构怎么选", claude, codex))
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["steps"]), 3)
        fusion_prompt = codex.call_args.args[0]
        self.assertIn("方案A：微服务", fusion_prompt)
        self.assertIn("方案B：单体", fusion_prompt)

    def test_parallel_design_partial_failure(self):
        """任一模型失败 → 不融合。"""
        claude = mock.AsyncMock(return_value=_fail("claude", "超时"))
        codex = mock.AsyncMock(return_value=_ok("codex", "方案B"))
        r = asyncio.run(run_template("parallel_design", "x", claude, codex))
        self.assertFalse(r["ok"])
        self.assertEqual(codex.await_count, 1)  # 只有并行那次，没有融合调用

    def test_doc_after_api_chain(self):
        """Claude 设计 → Codex 生成 Swagger：codex prompt 含设计稿。"""
        claude = mock.AsyncMock(return_value=_ok("claude", "GET /weather 返回温度"))
        codex = mock.AsyncMock(return_value=_ok("codex", "openapi: 3.0.0 ..."))
        r = asyncio.run(run_template("doc_after_api", "天气接口", claude, codex))
        self.assertTrue(r["ok"])
        self.assertIn("GET /weather 返回温度", codex.call_args.args[0])

    def test_unknown_template(self):
        """未知模板名 → 诚实报错并列出可选。"""
        r = asyncio.run(run_template("no_such", "x", mock.AsyncMock(), mock.AsyncMock()))
        self.assertFalse(r["ok"])
        self.assertIn("未知模板", r["error"])


if __name__ == "__main__":
    unittest.main()
