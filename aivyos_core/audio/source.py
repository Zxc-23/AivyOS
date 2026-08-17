"""音频采集源（文档 §3.1：16kHz 单声道 PCM）。

- MicSource：真实麦克风（sounddevice 可选；未安装抛 AudioUnavailable）
- WavSource：WAV 文件回放（测试/离线）
- SyntheticSource：合成信号（正弦波/静音，测试与演示）

`create_source` 按配置自动选择，全部后端输出统一 16-bit PCM 帧。
"""

from __future__ import annotations

import asyncio
import math
import struct
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from aivyos_core.audio.wav import read_wav


class AudioUnavailable(RuntimeError):
    """音频设备/后端不可用。"""


class AudioSource(ABC):
    sample_rate: int = 16000
    channels: int = 1
    frame_ms: int = 30

    @property
    def frame_bytes(self) -> int:
        return self.sample_rate * self.channels * 2 * self.frame_ms // 1000

    @abstractmethod
    def stream(self) -> AsyncIterator[bytes]:
        """产出 16-bit PCM 帧（每帧 frame_ms）。"""
        raise NotImplementedError


class MicSource(AudioSource):
    """真实麦克风（sounddevice 可选依赖）。"""

    def __init__(self, sample_rate: int = 16000, frame_ms: int = 30, device: Optional[str] = None) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as e:
            raise AudioUnavailable(
                "麦克风采集需要 sounddevice：pip install sounddevice（或设置 AIVYOS_AUDIO_INPUT=wav|synthetic）"
            ) from e
        self.sd = sd
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.device = device
        self._frames_per_chunk = max(1, sample_rate * frame_ms // 1000)

    async def stream(self) -> AsyncIterator[bytes]:
        stream = self.sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self._frames_per_chunk,
            device=self.device,
        )
        try:
            with stream:
                while True:
                    data, _ = stream.read(self._frames_per_chunk)
                    yield bytes(data)
        except asyncio.CancelledError:
            raise


class WavSource(AudioSource):
    """从 WAV 文件读取（离线/测试）。"""

    def __init__(self, path: str, frame_ms: int = 30) -> None:
        rate, pcm = read_wav(path)
        self.sample_rate = rate
        self.frame_ms = frame_ms
        self._pcm = pcm

    async def stream(self) -> AsyncIterator[bytes]:
        step = self.frame_bytes
        for i in range(0, len(self._pcm), step):
            yield self._pcm[i : i + step]
            await asyncio.sleep(0)  # 让出事件循环


class SyntheticSource(AudioSource):
    """合成信号源：测试与演示（正弦音 / 静音 / 噪声）。"""

    def __init__(
        self,
        duration_s: float = 3.0,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        tone_hz: Optional[float] = None,
        amplitude: int = 4000,
        silence_after_s: float = 0.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.duration_s = duration_s
        self.tone_hz = tone_hz
        self.amplitude = amplitude
        self.silence_after_s = silence_after_s

    async def stream(self) -> AsyncIterator[bytes]:
        n_frames = int(self.duration_s * self.sample_rate)
        step = self.frame_bytes
        for i in range(0, n_frames, self.sample_rate * self.frame_ms // 1000):
            yield self._make_frame(min(step, (n_frames - i) * 2))
            await asyncio.sleep(0)

    def _make_frame(self, nbytes: int) -> bytes:
        n = nbytes // 2
        if self.tone_hz is None:
            return b"\x00\x00" * n
        out = bytearray()
        for i in range(n):
            v = int(self.amplitude * math.sin(2 * math.pi * self.tone_hz * i / self.sample_rate))
            out += struct.pack("<h", max(-32768, min(32767, v)))
        return bytes(out)


def create_source(cfg: dict) -> AudioSource:
    """按配置选择音源：auto → mic（可用）→ synthetic；wav 指定文件路径。"""
    backend = cfg.get("input_backend", "auto")
    rate = int(cfg.get("sample_rate", 16000))
    frame_ms = int(cfg.get("frame_ms", 30))
    device = cfg.get("device")

    if backend == "mic":
        return MicSource(rate, frame_ms, device)
    if backend == "wav":
        path = cfg.get("wav_path")
        if not path:
            raise AudioUnavailable("input_backend=wav 但未配置 audio.wav_path")
        return WavSource(path, frame_ms)
    if backend == "synthetic":
        return SyntheticSource(sample_rate=rate, frame_ms=frame_ms)

    # auto
    try:
        return MicSource(rate, frame_ms, device)
    except AudioUnavailable:
        return SyntheticSource(sample_rate=rate, frame_ms=frame_ms)
