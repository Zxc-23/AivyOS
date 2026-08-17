"""TTS 层测试：mock WAV 输出 + cosyvoice 缺失降级。"""

import unittest

from aivyos_core.audio.wav import pcm_to_wav_bytes
from aivyos_core.tts.base import TTSUnavailable
from aivyos_core.tts.cosyvoice_backend import CosyVoiceBackend
from aivyos_core.tts.manager import create_tts
from aivyos_core.tts.mock_backend import MockTTS

from tests import AivyTestCase


class TestMockTTS(AivyTestCase):
    def test_synthesize_pcm(self):
        tts = MockTTS(sample_rate=24000, duration_s=0.5)
        r = tts.synthesize("你好")
        self.assertEqual(r.backend, "mock-tts")
        self.assertEqual(r.sample_rate, 24000)
        self.assertEqual(len(r.pcm), int(24000 * 0.5) * 2)  # 0.5s × 24000 采样 × 2B

    def test_wav_bytes_valid_riff(self):
        tts = MockTTS()
        r = tts.synthesize("测试")
        wav = pcm_to_wav_bytes(r.pcm, r.sample_rate)
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav[:16])

    def test_clone_voice_falls_back(self):
        tts = MockTTS()
        r = tts.clone_voice(b"\x00\x00" * 100, "克隆测试")
        self.assertEqual(r.backend, "mock-tts")


class TestCosyVoiceGuard(AivyTestCase):
    def test_missing_cosyvoice_raises(self):
        with self.assertRaises(TTSUnavailable):
            CosyVoiceBackend()

    def test_create_tts_auto_falls_back_to_mock(self):
        tts = create_tts({"backend": "auto"})
        self.assertIsInstance(tts, MockTTS)

    def test_create_tts_mock_forced(self):
        tts = create_tts({"backend": "mock"})
        self.assertIsInstance(tts, MockTTS)


if __name__ == "__main__":
    unittest.main()
