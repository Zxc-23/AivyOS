"""悬浮输入框测试（T1.5）：模块可导入；无 GUI 环境应抛 FloatingInputUnavailable。"""

import unittest

from aivyos_core.floating_input import FloatingInputBox, FloatingInputUnavailable

from tests import AivyTestCase


class TestFloatingInput(AivyTestCase):
    def test_module_importable(self):
        self.assertTrue(callable(FloatingInputBox))

    def test_construct_safe_in_any_env(self):
        """有 tkinter → 构造后立即销毁；无 tkinter/GUI → 抛 FloatingInputUnavailable。"""
        async def noop(text):
            pass

        try:
            box = FloatingInputBox(noop, title="test")
        except FloatingInputUnavailable:
            return  # 无 GUI 环境：符合预期
        self.assertIsNotNone(box.entry)
        box.root.destroy()


if __name__ == "__main__":
    unittest.main()
