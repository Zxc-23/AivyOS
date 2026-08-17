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
    def test_missing_funasr_raises(self):
        # 未安装 funasr → 实例化抛 ASRUnavailable
        with self.assertRaises(ASRUnavailable):
            FunASRBackend()

    def test_create_asr_auto_falls_back_to_mock(self):
        asr = create_asr({"backend": "auto"})
        self.assertIsInstance(asr, MockASR)

    def test_create_asr_mock_forced(self):
        asr = create_asr({"backend": "mock"})
        self.assertIsInstance(asr, MockASR)


if __name__ == "__main__":
    unittest.main()
