"""ASR 层测试：mock 后端 + funasr 缺失降级。"""

import unittest

from aivyos_core.asr.base import ASRUnavailable
from aivyos_core.asr.funasr_backend import FunASRBackend
from aivyos_core.asr.manager import create_asr
from aivyos_core.asr.mock_backend import MockASR

from tests import AivyTestCase


class TestMockASR(AivyTestCase):
    def test_fixed_text(self):
        asr = MockASR(text="帮我查天气")
        r = asr.transcribe(b"\x00\x00" * 100)
        self.assertEqual(r.text, "帮我查天气")
        self.assertEqual(r.backend, "mock-asr")

    def test_default_placeholder(self):
        asr = MockASR()
        r = asr.transcribe(b"\x00\x00" * 100)
        self.assertIn("mock", r.text)
        r2 = asr.transcribe(b"")
        self.assertEqual(r2.text, "")

    def test_transcribe_stream(self):
        asr = MockASR(text="流式测试")
        r = asr.transcribe_stream([b"\x00\x00" * 10, b"\x00\x00" * 10])
        self.assertEqual(r.text, "流式测试")


class TestFunASRGuard(AivyTestCase):
    @staticmethod
    def _funasr_installed() -> bool:
        import importlib.util

        return importlib.util.find_spec("funasr") is not None and importlib.util.find_spec("torch") is not None

    def test_missing_funasr_raises(self):
        # 未安装 funasr → 实例化抛 ASRUnavailable（已安装则跳过，真机走真实后端）
        if self._funasr_installed():
            self.skipTest("funasr 已安装（真机走真实 ASR），跳过降级断言")
        with self.assertRaises(ASRUnavailable):
            FunASRBackend()

    def test_create_asr_auto_falls_back_to_mock(self):
        # auto：funasr 可用则真实，否则降级 MockASR
        asr = create_asr({"backend": "auto"})
        if self._funasr_installed():
            self.assertNotIsInstance(asr, MockASR)
        else:
            self.assertIsInstance(asr, MockASR)

    def test_create_asr_mock_forced(self):
        asr = create_asr({"backend": "mock"})
        self.assertIsInstance(asr, MockASR)


if __name__ == "__main__":
    unittest.main()
