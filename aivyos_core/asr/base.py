"""ASR 后端抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


class ASRUnavailable(RuntimeError):
    """ASR 后端不可用（未安装依赖 / 模型缺失）。"""


@dataclass
class ASRResult:
    text: str
    confidence: float = 1.0
    language: str = "zh"
    partials: List[str] = field(default_factory=list)  # 流式中间结果（§16.3.2 asr_partial）
    backend: str = ""

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "language": self.language,
            "partials": self.partials,
            "backend": self.backend,
        }


class ASRBackend(ABC):
    name: str = "base"

    @abstractmethod
    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> ASRResult:
        """将一段 16-bit PCM 音频转为文本。"""
        raise NotImplementedError

    def transcribe_stream(self, frames) -> ASRResult:
        """流式识别（可覆盖）：默认聚合后一次性识别。"""
        pcm = b"".join(frames)
        return self.transcribe(pcm)
