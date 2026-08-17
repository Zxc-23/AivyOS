"""LLM 摘要测试（§4.4.2：真实后端不可用 → 朴素回退，杜绝 mock 冒充）。"""

import asyncio
import copy
import unittest

from aivyos_core.llm.router import ModelRouter
from aivyos_core.models import ChatMessage
from aivyos_core.summary import LLMSummarizer, naive_summary

from tests import AivyTestCase


def _messages(n: int = 4) -> list:
    msgs = []
    for i in range(n):
        msgs.append(ChatMessage(role="user", content=f"问题{i}：用户提到喜欢喝咖啡"))
        msgs.append(ChatMessage(role="assistant", content=f"回答{i}"))
    return msgs


class TestNaiveSummary(AivyTestCase):
    def test_returns_joined_text(self):
        s = naive_summary(_messages(2))
        self.assertIn("问题0", s)
        self.assertIn("回答1", s)

    def test_truncation(self):
        long_msgs = [ChatMessage(role="user", content="很长的内容" * 100)]
        s = naive_summary(long_msgs, max_chars=50)
        self.assertLessEqual(len(s), 51)


class TestLLMSummarizer(AivyTestCase):
    def test_auto_without_real_backend_falls_back_to_naive(self):
        import copy

        from aivyos_core.config import DEFAULT_CONFIG

        cfg = copy.deepcopy(DEFAULT_CONFIG["llm"])
        cfg["local"]["base_url"] = "http://127.0.0.1:1/v1"  # 不可达 → 探测 False（确定性）
        cfg["local"]["probe_timeout_s"] = 1.0
        router = ModelRouter(cfg)
        summ = LLMSummarizer(router, backend="auto")
        self.assertFalse(summ._real_available())
        out = asyncio.run(summ.summarize(_messages(2)))
        self.assertIn("问题0", out)  # 朴素摘要

    def test_naive_backend_forced(self):
        from aivyos_core.config import DEFAULT_CONFIG

        summ = LLMSummarizer(ModelRouter(copy.deepcopy(DEFAULT_CONFIG["llm"])), backend="naive")
        self.assertFalse(summ._real_available())
        self.assertIn("问题0", asyncio.run(summ.summarize(_messages(1))))

    def test_empty_input(self):
        from aivyos_core.config import DEFAULT_CONFIG

        summ = LLMSummarizer(ModelRouter(copy.deepcopy(DEFAULT_CONFIG["llm"])), backend="auto")
        self.assertEqual(asyncio.run(summ.summarize([])), "")


if __name__ == "__main__":
    unittest.main()
