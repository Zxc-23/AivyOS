"""连续对话模式测试（唤醒后窗口期内免唤醒词）。"""

import asyncio
import unittest

from aivyos_core.voice.session import VoiceSession

from tests import AivyTestCase, make_config


class FakeDetector:
    """可编程唤醒词检测器：模拟命中/未命中。"""

    def __init__(self, hit: bool = True):
        self.hit = hit

    def detect(self, text: str) -> bool:
        return self.hit

    def strip(self, text: str) -> str:
        # 去掉唤醒词前缀（模拟）
        for w in ("Aivy", "艾维", "贾维斯"):
            if text.startswith(w):
                return text[len(w):].strip()
        return text


def make_session(wake_required=True):
    cfg = make_config()
    cfg["voice"]["wake_required"] = wake_required
    session = VoiceSession(cfg)
    session.wake = FakeDetector(hit=False)  # 默认不命中
    session.wake_required = wake_required
    return session


class TestSkipWake(AivyTestCase):
    def test_text_override_requires_wake_without_skip(self):
        s = make_session(wake_required=True)
        r = asyncio.run(s.run_turn(text_override="你好"))
        self.assertIsNotNone(r)
        self.assertIsNone(r["reply"])  # 唤醒未命中 → 无回复
        self.assertIs(r["wake"], False)

    def test_text_override_skips_wake_when_allowed(self):
        s = make_session(wake_required=True)
        r = asyncio.run(s.run_turn(text_override="你好", skip_wake=True))
        self.assertIsNotNone(r)
        self.assertTrue(r["reply"])  # 跳过唤醒 → 正常回复
        self.assertNotIn("wake", r)  # 未走唤醒检查

    def test_wake_not_required_no_skip_needed(self):
        s = make_session(wake_required=False)
        r = asyncio.run(s.run_turn(text_override="你好"))
        self.assertTrue(r["reply"])

    def test_skip_wake_still_works_with_wake_hit(self):
        s = make_session(wake_required=True)
        s.wake = FakeDetector(hit=True)
        r = asyncio.run(s.run_turn(text_override="Aivy 帮我查天气"))
        self.assertTrue(r["reply"])


class TestExitCommand(AivyTestCase):
    """退出命令词检测（连续对话结束语）。"""

    def _is_exit(self, text: str) -> bool:
        from aivyos_core.server_entry import _is_exit_command

        return _is_exit_command(text)

    def test_exit_words_detected(self):
        for text in ("再见", "退出对话", "结束", "拜拜", "不说了，谢谢", "bye", "stop now", "再见了"):
            self.assertTrue(self._is_exit(text), text)

    def test_normal_commands_not_exit(self):
        for text in ("帮我查天气", "退出的原因是什么", "接下来做什么", "结束的方式有很多种"):
            self.assertFalse(self._is_exit(text), text)

    def test_exit_in_sentence(self):
        # 命令词出现在句中也可触发（如"再见"结尾）
        self.assertTrue(self._is_exit("今天就到这里，再见"))
        self.assertTrue(self._is_exit("好的，退出吧"))


class TestSpeakHelper(AivyTestCase):
    """VoiceSession.speak / aspeak 不崩溃（mock TTS）。"""

    def test_aspeak_with_mock_tts(self):
        cfg = make_config()
        cfg["tts"]["backend"] = "mock"
        from aivyos_core.voice.session import VoiceSession

        s = VoiceSession(cfg)
        ok = asyncio.run(s.aspeak("还需要我吗？"))
        self.assertTrue(ok)  # mock TTS + sink 播放成功

    def test_speak_sync_returns(self):
        cfg = make_config()
        cfg["tts"]["backend"] = "mock"
        from aivyos_core.voice.session import VoiceSession

        s = VoiceSession(cfg)
        ok = s.speak("好的，随时叫我。")
        self.assertTrue(ok)


class TestPTT(AivyTestCase):
    """PTT（按住说话）：分离采集 + process_pcm 共用路径。"""

    def _session(self):
        cfg = make_config()
        cfg["tts"]["backend"] = "mock"
        cfg["asr"]["backend"] = "mock"  # 强制 mock ASR（真机 auto 会选 FunASR）
        cfg["voice"]["wake_required"] = False  # 简化：不需唤醒词
        from aivyos_core.voice.session import VoiceSession

        s = VoiceSession(cfg)
        return s

    def test_ptt_start_stop_empty(self):
        """未采集到音频 → no_speech_detected（不崩溃）。"""
        s = self._session()
        ok = asyncio.run(s.start_ptt())
        self.assertTrue(ok)
        self.assertFalse(asyncio.run(s.start_ptt()))  # 重复启动被拒
        result = asyncio.run(s.stop_ptt())
        self.assertEqual(result["error"], "no_speech_detected")

    def test_ptt_process_pcm_direct(self):
        """process_pcm 直接处理合成 PCM → 完整链路（ASR mock + LLM mock + TTS mock）。"""
        import math
        import struct

        s = self._session()
        pcm = bytearray()
        for i in range(16000):
            v = int(3000 * math.sin(2 * math.pi * 440 * i / 16000))
            pcm += struct.pack("<h", v)
        result = asyncio.run(s.process_pcm(bytes(pcm)))
        self.assertTrue(result["reply"])
        self.assertIn("breakdown_ms", result)
        self.assertIn("wav_b64", result)

    def test_ptt_stop_uses_process_pcm(self):
        """stop_ptt 与 process_pcm 返回结构一致。"""
        import math
        import struct

        s = self._session()
        # 手动填充 buffer 模拟已采集
        pcm = bytearray()
        for i in range(8000):
            v = int(3000 * math.sin(2 * math.pi * 440 * i / 16000))
            pcm += struct.pack("<h", v)
        s._ptt_buffer = bytearray(pcm)
        s._ptt_active = True
        result = asyncio.run(s.stop_ptt())
        self.assertTrue(result["reply"])
        self.assertIn("text_clean", result)


if __name__ == "__main__":
    unittest.main()
