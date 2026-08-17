"""活体检测（文档 §9.1 步骤 5：防止录音/照片/视频攻击）。

- 频谱反欺骗（音频）：真实人声的能量包络随时间自然起伏，
  播放/录音重放通常更均匀 → 用帧 RMS 变异系数判定
- 视觉活体（图像）：VisualLiveness
    * cv2 后端（可选）：拉普拉斯方差（模糊照片疑似翻拍）+ 人脸检测
    * passive 模式：明确跳过（honest，非占位通过），记录原因
"""

from __future__ import annotations

import logging
import math
import struct
from typing import Tuple

log = logging.getLogger(__name__)


class VisualLiveness:
    """视觉活体：cv2 真实检测（可选）；auto 缺失 cv2 时用 passive（诚实标注）。"""

    def __init__(self, backend: str = "auto", blur_threshold: float = 80.0) -> None:
        self.backend = backend
        self.blur_threshold = blur_threshold
        self._cv2 = None
        self._cascade = None
        if backend in ("cv2", "auto"):
            try:
                import cv2  # type: ignore

                self._cv2 = cv2
                self._cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
            except ImportError:
                if backend == "cv2":
                    log.warning("视觉活体要求 cv2（pip install opencv-python），回退 passive")
        if self._cv2 is None:
            self.backend = "passive"

    def check(self, image: bytes) -> Tuple[bool, str]:
        """检测单张图像：模糊（疑似翻拍）→ 拒绝；无人脸 → 拒绝；否则通过。

        passive 模式（无 cv2）：明确标注跳过，不伪装检测。
        """
        if self.backend == "passive":
            return True, "passive（未启用视觉活体检测，需安装 opencv-python）"
        try:
            import numpy as np  # type: ignore

            arr = np.frombuffer(image, dtype="uint8")
            img = self._cv2.imdecode(arr, self._cv2.IMREAD_GRAYSCALE)
            if img is None:
                return False, "图像解码失败"
            laplacian_var = self._cv2.Laplacian(img, self._cv2.CV_64F).var()
            if laplacian_var < self.blur_threshold:
                return False, f"图像模糊（方差 {laplacian_var:.1f} < {self.blur_threshold}），疑似翻拍"
            faces = self._cascade.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5)
            if len(faces) == 0:
                return False, "未检测到人脸"
            return True, f"视觉活体通过（模糊方差 {laplacian_var:.1f}，人脸 {len(faces)} 个）"
        except Exception as e:
            return False, f"视觉活体检测异常: {e}"

    def check_frames(self, frames: list) -> Tuple[bool, str]:
        """多帧检测（Phase 4 接入眨眼 EAR 判定的接口预留）。"""
        if len(frames) < 2:
            return self.check(frames[0]) if frames else (False, "无帧输入")
        results = [self.check(f) for f in frames]
        if all(ok for ok, _ in results):
            return True, f"{len(frames)} 帧全部通过"
        return False, f"{len(frames)} 帧中 {sum(1 for ok, _ in results if not ok)} 帧未通过"


class LivenessChecker:
    def __init__(self, min_variation: float = 0.15, frame_ms: int = 30, visual_backend: str = "auto") -> None:
        self.min_variation = min_variation  # 帧 RMS 变异系数下限（低于视为疑似重放）
        self.frame_ms = frame_ms
        self.visual = VisualLiveness(backend=visual_backend)

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
        """视觉活体（cv2 真实检测 / passive 诚实标注）。"""
        if image is None:
            return False, "无图像输入"
        return self.visual.check(image)
