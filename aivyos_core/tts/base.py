"""TTS 后端抽象（文档 §6.1）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


class TTSUnavailable(RuntimeError):
    """TTS 后端不可用。"""


@dataclass
class TTSResult:
    pcm: bytes            # 16-bit PCM
    sample_rate: int
    text: str
    backend: str = ""
    latency_ms: float = 0.0
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "pcm_len": len(self.pcm),
            "sample_rate": self.sample_rate,
            "text": self.text,
            "backend": self.backend,
            "latency_ms": self.latency_ms,
            "meta": self.meta,
        }


class TTSBackend(ABC):
    name: str = "base"
    sample_rate: int = 24000

    @abstractmethod
    def synthesize(self, text: str) -> TTSResult:
        """文本 → 16-bit PCM。"""
        raise NotImplementedError

    def clone_voice(self, ref_pcm: bytes, text: str) -> TTSResult:
        """音色克隆（§6.1：3 秒样本 zero-shot 克隆）。默认降级为普通合成。"""
        return self.synthesize(text)
