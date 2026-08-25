"""音频播放/输出（文档 §6.1）。

- NullSink：丢弃（默认，无设备环境安全）
- WavSink：写入 WAV 文件（演示/保存）
- PlaybackSink：sounddevice 实时播放（非阻塞，fire-and-forget）
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from aivyos_core.audio.wav import write_wav

log = logging.getLogger(__name__)


class AudioSink(ABC):
    @abstractmethod
    def play(self, pcm: bytes) -> None:
        """播放/输出一段 16-bit PCM。"""
        raise NotImplementedError

    def stop(self) -> None:
        """停止当前播放（默认空实现）。"""
        pass


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
    """非阻塞音频播放：fire-and-forget，不阻塞调用线程。

    前端已通过 Web Audio API 播放 wav_b64，后端 PlaybackSink 仅在无前端时使用。
    使用 sounddevice.play() 异步播放（不调用 wait()），立即返回。
    """

    def __init__(self, sample_rate: int = 24000) -> None:
        try:
            import sounddevice as sd  # type: ignore
            import numpy as np  # type: ignore

            self.sd = sd
            self.np = np
        except ImportError as e:
            raise RuntimeError("实时播放需要 sounddevice + numpy（缺失时降级 NullSink）") from e
        self.sample_rate = sample_rate
        self._current_audio = None
        self._lock = threading.Lock()

    def stop(self) -> None:
        """停止当前正在播放的音频。"""
        with self._lock:
            self._current_audio = None
        try:
            self.sd.stop()
        except Exception as e:
            log.debug("忽略预期内异常: %s", e, exc_info=True)
        log.debug("PlaybackSink.stop() 已调用")

    def play(self, pcm: bytes) -> None:
        """异步播放 PCM 音频（fire-and-forget，不阻塞）。

        sounddevice.play() 立即返回，音频在后台播放。
        保留音频引用防止 GC 回收导致播放中断。
        """
        try:
            audio = self.np.frombuffer(pcm, dtype="int16")
            with self._lock:
                self._current_audio = audio
            self.sd.play(audio, self.sample_rate)
            # play() 立即返回，音频在后台播放
            # 不调用 wait()，不阻塞
        except Exception as e:
            log.warning("PlaybackSink 播放异常: %s", e)


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