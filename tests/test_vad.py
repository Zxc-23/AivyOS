"""VAD 测试（能量回退 + Silero 降级）。"""

import math
import struct
import unittest

from aivyos_core.audio.vad import EnergyVAD, create_vad

from tests import AivyTestCase


def make_frame(amplitude: int, n_samples: int = 480) -> bytes:
    """构造一帧 16-bit PCM（默认 30ms@16k）。"""
    out = bytearray()
    for i in range(n_samples):
        v = int(amplitude * math.sin(2 * math.pi * 440 * i / 16000))
        out += struct.pack("<h", v)
    return bytes(out)


class TestEnergyVAD(AivyTestCase):
    def setUp(self):
        self.vad = EnergyVAD(threshold=300, frame_ms=30)

    def test_speech_vs_silence(self):
        self.assertTrue(self.vad.is_speech(make_frame(4000)))
        self.assertTrue(self.vad.is_speech(make_frame(1000)))
        self.assertFalse(self.vad.is_speech(make_frame(0)))
        self.assertFalse(self.vad.is_speech(b"\x00\x00" * 480))

    def test_low_amplitude_is_silence(self):
        self.assertFalse(self.vad.is_speech(make_frame(100)))  # RMS ~70 < 300


class TestCreateVad(AivyTestCase):
    def test_energy_forced(self):
        vad = create_vad({"vad_backend": "energy", "sample_rate": 16000, "frame_ms": 30})
        self.assertIsInstance(vad, EnergyVAD)

    def test_auto_falls_back_to_energy(self):
        # 沙箱环境无 silero-vad → auto 应降级到 EnergyVAD
        vad = create_vad({"vad_backend": "auto", "sample_rate": 16000, "frame_ms": 30})
        self.assertIsInstance(vad, EnergyVAD)


if __name__ == "__main__":
    unittest.main()
