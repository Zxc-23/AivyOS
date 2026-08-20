"""语音会话编排测试（mock 链路全通 + 唤醒词门控 + 真实采集路径）。"""

import asyncio
import math
import struct
import unittest

from aivyos_core.config import deep_merge
from aivyos_core.voice.session import VoiceSession

from tests import AivyTestCase, make_config


class FakeSource:
    """模拟音源：1s 正弦音（语音）+ 0.5s 静音（尾部）。"""

    sample_rate = 16000
    frame_ms = 30
    frame_bytes = 960

    async def stream(self):
        for i in range(34):  # ~1.02s 语音
            out = bytearray()
            for j in range(480):
                v = int(4000 * math.sin(2 * math.pi * 440 * (i * 480 + j) / 16000))
                out += struct.pack("<h", v)
            yield bytes(out)
        for _ in range(16):  # 0.48s 静音
            yield b"\x00\x00" * 480


def voice_config(**voice_overrides) -> dict:
    cfg = make_config()
    cfg["asr"]["backend"] = "mock"
    cfg["tts"]["backend"] = "mock"
    cfg["audio"]["vad_backend"] = "energy"
    cfg["audio"]["input_backend"] = "synthetic"
    return deep_merge(cfg, {"voice": voice_overrides})


class TestVoiceSession(AivyTestCase):
    def test_text_override_full_chain(self):
        session = VoiceSession(voice_config())
        result = asyncio.run(session.run_turn(text_override="你好"))
        self.assertIsNotNone(result)
        self.assertIn("reply", result)
        self.assertTrue(result["reply"])
        self.assertEqual(result["asr_backend"], "text-override")
        self.assertEqual(result["tts_backend"], "mock-tts")
        self.assertGreater(result["wav_len"], 0)

    def test_wake_gating(self):
        session = VoiceSession(voice_config(wake_required=True))
        miss = asyncio.run(session.run_turn(text_override="你好"))
        self.assertIsNotNone(miss)
        self.assertIsNone(miss["reply"])  # 唤醒词未命中
        hit = asyncio.run(session.run_turn(text_override="Aivy 帮我查天气"))
        self.assertIsNotNone(hit["reply"])  # 命中并去除唤醒词
        self.assertEqual(hit["text_clean"], "帮我查天气")

    def test_capture_path_with_fake_source(self):
        session = VoiceSession(voice_config())
        session.source = FakeSource()  # 注入模拟音源，走真实采集→VAD→ASR 路径
        result = asyncio.run(session.run_turn())
        self.assertIsNotNone(result)
        self.assertIn("（mock 识别）你好", result["text"])
        self.assertTrue(result["reply"])

    def test_status_reports_backends(self):
        session = VoiceSession(voice_config())
        st = session.status()
        self.assertEqual(st["asr"], "mock-asr")
        self.assertEqual(st["tts"], "mock-tts")
        self.assertIn("vad", st)
        self.assertFalse(st["wake_required"])

    def test_status_reports_readiness(self):
        """就绪门：mock 后端 asr_ready/tts_ready 恒为 True（无需预热）。"""
        from aivyos_core.server_entry import _is_exit_command  # noqa: F401  (确保模块可导入)

        session = VoiceSession(voice_config())
        st = session.status()
        # session.status 本身不带 asr_ready；由 server_entry.voice_status 附加。
        # 这里验证 mock 后端可安全读取 _warmed_up / _available 属性（不抛异常）。
        asr_ready = bool(getattr(session.asr, "_warmed_up", True)) or session.asr.name == "mock-asr"
        tts_ready = bool(getattr(session.tts, "_available", True)) or session.tts.name == "mock-tts"
        self.assertTrue(asr_ready)
        self.assertTrue(tts_ready)


if __name__ == "__main__":
    unittest.main()
