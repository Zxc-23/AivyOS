"""Mock TTS — 零依赖回退：生成占位 PCM（正弦提示音）并记录文本。

保证语音链路无模型也可完整运行（采集→VAD→ASR→LLM→TTS→输出）。
"""

from __future__ import annotations

import math
import struct
import time

from aivyos_core.tts.base import TTSBackend, TTSResult


class MockTTS(TTSBackend):
    name = "mock-tts"
    sample_rate = 24000

    def __init__(self, sample_rate: int = 24000, tone_hz: float = 440.0, duration_s: float = 0.5) -> None:
        self.sample_rate = sample_rate
        self.tone_hz = tone_hz
        self.duration_s = duration_s

    def synthesize(self, text: str) -> TTSResult:
        start = time.perf_counter()
        n = int(self.sample_rate * self.duration_s)
        pcm = bytearray()
        for i in range(n):
            v = int(1200 * math.sin(2 * math.pi * self.tone_hz * i / self.sample_rate))
            pcm += struct.pack("<h", v)
        return TTSResult(
            pcm=bytes(pcm),
            sample_rate=self.sample_rate,
            text=text,
            backend=self.name,
            latency_ms=(time.perf_counter() - start) * 1000,
            meta={"note": "mock 提示音，非真实语音"},
        )
