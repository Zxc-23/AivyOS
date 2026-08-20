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

    设计原则：宁可误报不可漏报。
    - 自动校准：前 20 帧计算噪声基线，阈值 = 噪声 * 1.3
    - 高灵敏度：单帧超阈值即判定为语音（由上层负责起止判定）
    - 校准后阈值范围：15-500，确保在各种环境下都能捕捉语音
    """

    def __init__(self, threshold: int = 30, hangover_ms: int = 30, frame_ms: int = 30,
                 auto_calibrate: bool = True) -> None:
        self.threshold = threshold
        self.hangover_ms = hangover_ms
        self.frame_ms = frame_ms
        self._noise_rms: list[float] = []
        self._auto_calibrate = auto_calibrate
        self._calibrated = False
        self._calibration_frames = 20

    def is_speech(self, frame: bytes) -> bool:
        rms = _rms(frame)
        if self._auto_calibrate and not self._calibrated:
            self._noise_rms.append(rms)
            if len(self._noise_rms) >= self._calibration_frames:
                self._finalize_calibration()
        return rms >= self.threshold

    def _finalize_calibration(self) -> None:
        """基于噪声均值计算阈值（高灵敏度策略）。"""
        avg_noise = sum(self._noise_rms) / len(self._noise_rms)

        self.threshold = max(15, min(500, int(avg_noise * 1.3)))
        self._calibrated = True
        import logging
        logging.getLogger(__name__).info(
            "EnergyVAD 校准: noise_avg=%.1f, threshold=%d (n=%d)",
            avg_noise, self.threshold, len(self._noise_rms)
        )


class SileroVAD(VADEngine):
    """Silero VAD v5（可选依赖 silero-vad / torch）。

    Silero VAD 要求固定帧大小：
      - 16000 Hz → 512 采样点 (32ms)
      - 8000 Hz  → 256 采样点 (32ms)
    """

    def __init__(self, sample_rate: int = 16000, threshold: float = 0.2) -> None:
        try:
            from silero_vad import load_silero_vad  # type: ignore

            self.model = load_silero_vad()
        except ImportError as e:
            raise RuntimeError("silero-vad 未安装：pip install silero-vad（缺失时已可降级 EnergyVAD）") from e
        self.sample_rate = sample_rate
        self.threshold = threshold
        self._target_samples = 512 if sample_rate == 16000 else 256
        self._target_bytes = self._target_samples * 2  # int16 = 2 bytes

    def is_speech(self, frame: bytes) -> bool:
        """检测单帧是否包含语音。

        Args:
            frame: int16 PCM 音频帧（任意长度，自动 padding/truncation 到模型要求）

        Returns:
            True 表示检测到语音
        """
        import torch  # type: ignore

        frame_data = frame
        if len(frame) != self._target_bytes:
            frame_data = frame[:self._target_bytes].ljust(self._target_bytes, b"\x00")

        # 用可写 bytearray 消除 "buffer not writable" 警告（torch.tensor 不接受 bytes）
        tensor = torch.frombuffer(bytearray(frame_data), dtype=torch.int16).float() / 32768.0
        prob = self.model(tensor, self.sample_rate).item()
        return prob >= self.threshold


def create_vad(cfg: dict) -> VADEngine:
    """auto：Silero 可用则用，否则能量 VAD。"""
    sample_rate = int(cfg.get("sample_rate", 16000))
    frame_ms = int(cfg.get("frame_ms", 30))
    if cfg.get("vad_backend") == "energy":
        return EnergyVAD(frame_ms=frame_ms)
    try:
        threshold = float(cfg.get("vad_threshold", 0.2))
        return SileroVAD(sample_rate=sample_rate, threshold=threshold)
    except (RuntimeError, ImportError):
        return EnergyVAD(frame_ms=frame_ms)
