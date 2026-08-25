"""唤醒词检测强化测试：去重逻辑 + 谐音扩展 + 边界验证（HC-5/HC-7）。"""

import time
import unittest

from aivyos_core.wake import WakeWordDetector

from tests import AivyTestCase


class TestWakeHardening(AivyTestCase):
    def test_same_text_within_1s_returns_false(self):
        """相同文本 1 秒内重复触发应被去重，返回 False（防抖动）。"""
        w = WakeWordDetector()
        self.assertTrue(w.detect("Aivy 帮我查天气"))
        self.assertFalse(w.detect("Aivy 帮我查天气"))

    def test_same_text_after_1_1s_returns_true(self):
        """相同文本间隔 ≥1.1 秒后应允许再次触发。"""
        w = WakeWordDetector()
        self.assertTrue(w.detect("贾维斯早上好"))
        time.sleep(1.1)
        self.assertTrue(w.detect("贾维斯早上好"))

    def test_different_text_within_1s_still_true(self):
        """1 秒内不同文本（不同唤醒词内容）不被去重。"""
        w = WakeWordDetector()
        self.assertTrue(w.detect("Aivy 帮我查天气"))
        self.assertTrue(w.detect("艾薇 打开音乐"))

    def test_homophone_jia_weisi_hits_jiawei(self):
        """谐音扩展：'嘉维斯'和'加维斯'应命中'贾维斯'。"""
        w = WakeWordDetector(["贾维斯"])
        self.assertTrue(w.detect("嘉维斯你好"))
        self.assertTrue(w.detect("加维斯早上好"))
        self.assertTrue(w.detect("甲维斯帮我"))

    def test_single_char_weixin_does_not_hit(self):
        """单字排除（HC-7 验证）：单独一个'微'字不触发艾薇唤醒词。"""
        w = WakeWordDetector(["艾薇"])
        self.assertFalse(w.detect("微信消息来了"))
        self.assertFalse(w.detect("微风拂面"))

    def test_english_boundary_jarvis_aivory(self):
        """英文边界（HC-5 三层验证）：jarvis/aivory 等不触发对应唤醒词。"""
        w = WakeWordDetector(["Aivy", "贾维斯"])
        self.assertFalse(w.detect("aivory 这个词不错"))
        self.assertFalse(w.detect("jarvis is a common name"))
        self.assertTrue(w.detect("hello aivy, how are you"))


if __name__ == "__main__":
    unittest.main()
