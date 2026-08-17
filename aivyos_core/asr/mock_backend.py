"""Mock ASR — 规则化回退（零依赖）。

真实场景（麦克风已就绪但未装 funasr）：
- 默认按"语音检测到"返回固定问候文本，明确标注 mock，不伪装真实识别。
- 可构造 MockASR(text=...) 注入固定文本（测试/演示）。
- 检测到唤醒词前缀时原样返回，用于唤醒链路联调。
"""

from __future__ import annotations

from aivyos_core.asr.base import ASRBackend, ASRResult


class MockASR(ASRBackend):
    name = "mock-asr"

    def __init__(self, text: str | None = None, language: str = "zh") -> None:
        self._fixed = text
        self.language = language

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> ASRResult:
        if self._fixed is not None:
            return ASRResult(text=self._fixed, confidence=1.0, language=self.language, backend=self.name)
        if not pcm:
            return ASRResult(text="", confidence=0.0, language=self.language, backend=self.name)
        # 有音频输入但无真实模型 → 返回占位问候（明确 mock）
        return ASRResult(
            text="（mock 识别）你好",
            confidence=0.5,
            language=self.language,
            partials=["（mock 识别）你好"],
            backend=self.name,
        )
