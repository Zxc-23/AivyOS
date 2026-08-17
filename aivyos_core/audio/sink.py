"""音频播放/输出（文档 §6.1）。

- NullSink：丢弃（默认，无设备环境安全）
- WavSink：写入 WAV 文件（演示/保存）
- PlaybackSink：sounddevice 实时播放（可选）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from aivyos_core.audio.wav import write_wav


class AudioSink(ABC):
    @abstractmethod
    def play(self, pcm: bytes) -> None:
        """播放/输出一段 16-bit PCM。"""
        raise NotImplementedError


class NullSink(AudioSink):
    def play(self, pcm: bytes) -> None:
        pass


class WavSink(AudioSink):
    def __init__(self, path: str | Path, sample_rate: int = 24000) -> None:
        self.path = Path(path)
        self.sample_rate = sample_rate
        self.count = 0

    def play(self, pcm: bytes) -> None:
        self.count += 1
        write_wav(self.path, pcm, self.sample_rate)


class PlaybackSink(AudioSink):
    def __init__(self, sample_rate: int = 24000) -> None:
        try:
            import sounddevice as sd  # type: ignore

            self.sd = sd
        except ImportError as e:
            raise RuntimeError("实时播放需要 sounddevice：pip install sounddevice") from e
        self.sample_rate = sample_rate

    def play(self, pcm: bytes) -> None:
        import numpy as np  # type: ignore

        audio = np.frombuffer(pcm, dtype="int16")
        self.sd.play(audio, self.sample_rate)
        self.sd.wait()


def create_sink(cfg: dict) -> AudioSink:
    """auto：可播放则播放，否则 Null。可指定 wav_path 落盘。"""
    if cfg.get("sink") == "null":
        return NullSink()
    if cfg.get("wav_path"):
        return WavSink(cfg["wav_path"], sample_rate=int(cfg.get("sample_rate", 24000)))
    try:
        return PlaybackSink(sample_rate=int(cfg.get("sample_rate", 24000)))
    except RuntimeError:
        return NullSink()
