"""语音活动检测 VAD（文档 §3.1.1：Silero VAD v5，帧长 30ms）。

- SileroVAD：silero-vad 包（可选；缺失时自动降级）
- EnergyVAD：能量（RMS）阈值回退实现（零依赖，可运行可测试）
"""

from __future__ import annotations

import math
import struct
from abc import ABC, abstractmethod
from typing import Optional


class VADEngine(ABC):
    frame_ms: int = 30
    sample_rate: int = 16000

    @abstractmethod
    def is_speech(self, frame: bytes) -> bool:
        """判断一帧 16-bit PCM 是否含语音。"""
        raise NotImplementedError


def _rms(frame: bytes) -> float:
    n = len(frame) // 2
    if n == 0:
        return 0.0
    acc = 0
    for i in range(n):
        (s,) = struct.unpack_from("<h", frame, i * 2)
        acc += s * s
    return math.sqrt(acc / n)


class EnergyVAD(VADEngine):
    """RMS 能量阈值 VAD（回退实现，§3.1.1 的简化替代）。

    - threshold：高于判为语音（16-bit 默认 ~300，约 -34dBFS）
    - hangover_ms：语音结束后保持"语音中"的时长，防止断词
    """

    def __init__(self, threshold: int = 300, hangover_ms: int = 300, frame_ms: int = 30) -> None:
        self.threshold = threshold
        self.hangover_ms = hangover_ms
        self.frame_ms = frame_ms
        self._speech_frames = 0  # 连续语音帧计数（用于断句）

    def is_speech(self, frame: bytes) -> bool:
        return _rms(frame) >= self.threshold


class SileroVAD(VADEngine):
    """Silero VAD v5（可选依赖 silero-vad / torch）。"""

    def __init__(self, sample_rate: int = 16000, threshold: float = 0.5) -> None:
        try:
            from silero_vad import load_silero_vad  # type: ignore

            self.model = load_silero_vad()
        except ImportError as e:
            raise RuntimeError("silero-vad 未安装：pip install silero-vad（缺失时已可降级 EnergyVAD）") from e
        self.sample_rate = sample_rate
        self.threshold = threshold

    def is_speech(self, frame: bytes) -> bool:
        import torch  # type: ignore

        tensor = torch.frombuffer(frame, dtype=torch.int16).float() / 32768.0
        prob = self.model(tensor, self.sample_rate).item()
        return prob >= self.threshold


def create_vad(cfg: dict) -> VADEngine:
    """auto：Silero 可用则用，否则能量 VAD。"""
    sample_rate = int(cfg.get("sample_rate", 16000))
    frame_ms = int(cfg.get("frame_ms", 30))
    if cfg.get("vad_backend") == "energy":
        return EnergyVAD(frame_ms=frame_ms)
    try:
        return SileroVAD(sample_rate=sample_rate)
    except (RuntimeError, ImportError):
        return EnergyVAD(frame_ms=frame_ms)
