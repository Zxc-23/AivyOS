"""WAV 读写工具（stdlib wave）。"""

from __future__ import annotations

import io
import wave
from pathlib import Path


def pcm_to_wav_bytes(
    pcm: bytes, sample_rate: int, channels: int = 1, sample_width: int = 2
) -> bytes:
    """int16 PCM → WAV 文件字节（内存）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def write_wav(path: str | Path, pcm: bytes, sample_rate: int, channels: int = 1) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pcm_to_wav_bytes(pcm, sample_rate, channels))
    return path


def read_wav(path: str | Path) -> tuple[int, bytes]:
    """读取 WAV，返回 (sample_rate, int16 PCM bytes)。"""
    with wave.open(str(path), "rb") as w:
        assert w.getsampwidth() == 2, "仅支持 16-bit PCM WAV"
        return w.getframerate(), w.readframes(w.getnframes())
