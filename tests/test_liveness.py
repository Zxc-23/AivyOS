"""活体检测测试（§9.1：频谱/能量变化率反重放）。"""

import math
import struct
import unittest

from aivyos_core.auth.liveness import LivenessChecker

from tests import AivyTestCase


def natural_audio(duration_s: float = 4.0, sample_rate: int = 16000) -> bytes:
    """能量包络自然起伏（模拟真人说话：音节间强弱交替）。"""
    out = bytearray()
    for i in range(int(duration_s * sample_rate)):
        t = i / sample_rate
        v = 3000 * math.sin(2 * math.pi * 220 * t)
        v *= 0.3 + 0.7 * abs(math.sin(2 * math.pi * 2.2 * t))  # 包络起伏
        out += struct.pack("<h", int(v))
    return bytes(out)


def flat_audio(duration_s: float = 4.0, sample_rate: int = 16000) -> bytes:
    """恒定幅度（模拟录音重放：能量均匀）。"""
    out = bytearray()
    for i in range(int(duration_s * sample_rate)):
        v = 3000 * math.sin(2 * math.pi * 220 * i / sample_rate)
        out += struct.pack("<h", int(v))
    return bytes(out)


class TestLiveness(AivyTestCase):
    def setUp(self):
        self.lc = LivenessChecker(min_variation=0.15)

    def test_natural_audio_passes(self):
        ok, var = self.lc.check_audio(natural_audio())
        self.assertTrue(ok, f"自然语音应通过，变异系数={var:.3f}")

    def test_flat_audio_fails(self):
        ok, var = self.lc.check_audio(flat_audio())
        self.assertFalse(ok, f"恒定幅度应判定为疑似重放，变异系数={var:.3f}")

    def test_short_audio_fails(self):
        ok, _ = self.lc.check_audio(flat_audio(duration_s=0.2))
        self.assertFalse(ok)

    def test_image_placeholder(self):
        ok, _ = self.lc.check_image(b"image")
        self.assertTrue(ok)
        ok2, _ = self.lc.check_image(None)
        self.assertFalse(ok2)


if __name__ == "__main__":
    unittest.main()
