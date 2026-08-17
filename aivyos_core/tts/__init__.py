"""TTS 语音合成层（文档 §6.1：CosyVoice 3 主引擎，GPT-SoVITS 备选）。"""

from aivyos_core.tts.base import TTSBackend, TTSResult, TTSUnavailable
from aivyos_core.tts.cosyvoice_backend import CosyVoiceBackend
from aivyos_core.tts.mock_backend import MockTTS
from aivyos_core.tts.manager import create_tts

__all__ = ["TTSBackend", "TTSResult", "TTSUnavailable", "CosyVoiceBackend", "MockTTS", "create_tts"]
