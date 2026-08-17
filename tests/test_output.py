"""输出策略测试（§6.3 多模态输出路由，T4.3）。"""

import unittest

from aivyos_core.output import OutputChannel, OutputRouter

from tests import AivyTestCase


class TestOutputRouter(AivyTestCase):
    def setUp(self):
        self.router = OutputRouter({"default_channel": "text", "output_dir": ".aivyos_test/out"})

    def test_text_default(self):
        plan = self.router.decide("普通回复内容", modality_hint="text")
        self.assertEqual(plan.channel, OutputChannel.TEXT)

    def test_voice_hint(self):
        plan = self.router.decide("语音回答", modality_hint="voice")
        self.assertEqual(plan.channel, OutputChannel.VOICE)

    def test_code_routed_to_file(self):
        plan = self.router.decide("```python\nprint(1)\n```")
        self.assertEqual(plan.channel, OutputChannel.FILE)

    def test_notification_urgency(self):
        plan = self.router.decide("系统出现异常", modality_hint="notification")
        self.assertEqual(plan.channel, OutputChannel.VOICE)  # 高紧急 → 语音播报
        self.assertEqual(plan.level, "urgent")
        plan2 = self.router.decide("新邮件提醒", modality_hint="notification")
        self.assertEqual(plan2.channel, OutputChannel.NOTIFICATION)
        self.assertEqual(plan2.level, "important")

    def test_deliver_file_writes(self):
        plan = self.router.decide("```\ncode\n```")
        result = self.router.deliver(plan)
        self.assertIn("path", result)
        import os

        self.assertTrue(os.path.exists(result["path"]))


if __name__ == "__main__":
    unittest.main()
