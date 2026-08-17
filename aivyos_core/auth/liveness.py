"""活体检测（文档 §9.1 步骤 5：防止录音/照片/视频攻击）。

- 频谱反欺骗（音频）：真实人声的能量包络随时间自然起伏，
  播放/录音重放通常更均匀 → 用帧 RMS 变异系数判定
- 视觉活体（图像）：占位实现（Phase 4 接入摄像头深度/眨眼检测），默认通过并标注
"""

from __future__ import annotations

import math
import struct
from typing import Tuple


class LivenessChecker:
    def __init__(self, min_variation: float = 0.15, frame_ms: int = 30) -> None:
        self.min_variation = min_variation  # 帧 RMS 变异系数下限（低于视为疑似重放）
        self.frame_ms = frame_ms

    def check_audio(self, pcm: bytes, sample_rate: int = 16000) -> Tuple[bool, float]:
        """返回 (是否疑似真人, 变异系数)。"""
        frame = max(1, sample_rate * self.frame_ms // 1000)
        rms_values = []
        for i in range(0, len(pcm) // 2 - frame + 1, frame):
            samples = struct.unpack(f"<{frame}h", pcm[i * 2 : (i + frame) * 2])
            rms = math.sqrt(sum(s * s for s in samples) / frame)
            rms_values.append(rms)
        if len(rms_values) < 5:
            return False, 0.0
        mean = sum(rms_values) / len(rms_values)
        if mean <= 0:
            return False, 0.0
        var = math.sqrt(sum((v - mean) ** 2 for v in rms_values) / len(rms_values)) / mean
        return var >= self.min_variation, var

    def check_image(self, image: bytes | None) -> Tuple[bool, str]:
        """视觉活体占位：图像存在即通过（Phase 4 接入深度/眨眼检测）。"""
        if image is None:
            return False, "无图像输入"
        return True, "视觉活体占位（Phase 4 接入）"
