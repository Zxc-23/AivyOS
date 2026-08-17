"""上下文管理器测试（文档 §4.4）。"""

import unittest

from aivyos_core.context import ARCHIVE_MARKER, ContextManager, estimate_tokens
from aivyos_core.models import ChatMessage

from tests import AivyTestCase


class TestContext(AivyTestCase):
    def test_estimate_tokens(self):
        self.assertEqual(estimate_tokens("你好世界"), 4)  # 4 个 CJK
        self.assertGreater(estimate_tokens("hello world"), 0)

    def test_budget_sums_within_window(self):
        cm = ContextManager(context_window=32768)
        b = cm.allocate_budget()
        self.assertEqual(b["total"], 32768)
        self.assertEqual(b["system"] + b["memory"] + b["history"] + b["input"] + b["output"], 32768)
        self.assertGreater(b["history"], 0)

    def test_build_messages_structure(self):
        cm = ContextManager(context_window=4096, history_turns=4)
        history = [
            ChatMessage(role="user", content="第一条"),
            ChatMessage(role="assistant", content="回复一"),
            ChatMessage(role="user", content="第二条"),
            ChatMessage(role="assistant", content="回复二"),
        ]
        messages, stats = cm.build_messages(
            persona_prompt="你是测试人格",
            memory_hits=[{"text": "用户喜欢咖啡", "score": 0.9, "created_at": "2026-01-01 00:00:00"}],
            history=history,
            current_input="第三条问题",
        )
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("用户喜欢咖啡", messages[0]["content"])
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(messages[-1]["content"], "第三条问题")
        self.assertIn(ARCHIVE_MARKER, [m["content"] for m in messages])
        self.assertEqual(stats["history_kept"], 4)

    def test_archive_callback_on_overflow(self):
        # 极小窗口强制触发远期归档
        cm = ContextManager(context_window=512, history_turns=2)
        history = [ChatMessage(role="user", content="轮次" + str(i) * 40) for i in range(20)]
        archived = []

        messages, stats = cm.build_messages(
            persona_prompt="p",
            memory_hits=[],
            history=history,
            current_input="新问题",
            archive_callback=lambda old: archived.extend(old),
        )
        self.assertGreater(stats["archived"], 0)
        self.assertGreater(len(archived), 0)
        self.assertEqual(messages[-1]["content"], "新问题")

    def test_compress_history(self):
        cm = ContextManager()
        history = [ChatMessage(role="user", content=f"消息{i}") for i in range(20)]
        out = cm.compress_history(history, max_turns=5)
        self.assertEqual(len(out), 6)  # 1 摘要 + 5 近期
        self.assertIn("[中期摘要", out[0].content)


if __name__ == "__main__":
    unittest.main()
