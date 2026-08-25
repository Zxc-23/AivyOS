"""唤醒词检测测试。"""

import time
import unittest

from aivyos_core.wake import WakeWordDetector

from tests import AivyTestCase


class TestWakeWord(AivyTestCase):
    def test_detect_default_words(self):
        w = WakeWordDetector()
        self.assertTrue(w.detect("Aivy，帮我查天气"))
        self.assertTrue(w.detect("贾维斯，早上好"))
        self.assertTrue(w.detect("你好 aivy"))

    def test_detect_miss(self):
        w = WakeWordDetector()
        self.assertFalse(w.detect("帮我查天气"))
        self.assertFalse(w.detect("随便聊聊"))

    def test_custom_words(self):
        w = WakeWordDetector(["小助手"])
        self.assertTrue(w.detect("小助手在吗"))
        self.assertFalse(w.detect("Aivy在吗"))

    def test_strip_prefix(self):
        w = WakeWordDetector()
        self.assertEqual(w.strip("Aivy，帮我查天气"), "帮我查天气")
        self.assertEqual(w.strip("贾维斯 早上好"), "早上好")
        self.assertEqual(w.strip("没有唤醒词"), "没有唤醒词")

    def test_case_insensitive(self):
        """大小写不敏感；注意两断言间绕过 1s 归一化去重窗口。"""
        w = WakeWordDetector()
        self.assertTrue(w.detect("aivy 你好"))
        time.sleep(1.1)
        self.assertTrue(w.detect("AIVY 你好"))


if __name__ == "__main__":
    unittest.main()
