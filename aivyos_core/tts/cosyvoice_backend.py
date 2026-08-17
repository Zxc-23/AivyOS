"""CosyVoice 3 适配后端（文档 §6.1：主引擎 0.5B，3 秒音色克隆，24kHz）。

cosyvoice 为可选依赖：未安装时导入安全，实例化抛 TTSUnavailable（调用方降级 mock）。
GPT-SoVITS 备选引擎通过同一 TTSBackend 接口可插拔切换（§6.1 备选）。
"""

from __future__ import annotations

from aivyos_core.tts.base import TTSBackend, TTSResult, TTSUnavailable


class CosyVoiceBackend(TTSBackend):
    """CosyVoice 3（Fun-CosyVoice3 0.5B，Apache-2.0）。"""

    name = "cosyvoice3"
    sample_rate = 24000

    def __init__(self, model: str = "CosyVoice3-0.5B", clone_seconds: int = 3) -> None:
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice3  # type: ignore
        except ImportError as e:
            raise TTSUnavailable(
                "cosyvoice 未安装：pip install cosyvoice（见 requirements-ml.txt）。"
                "已自动降级到 mock TTS。"
            ) from e
        self.model = CosyVoice3(model, load_jit=False, load_trt=False, fp16=False)
        self.clone_seconds = clone_seconds

    def synthesize(self, text: str) -> TTSResult:
        import time

        start = time.perf_counter()
        chunks = []
        for chunk in self.model.inference_zero_shot(
            text,
            self._default_ref_text(),
            self._default_ref_audio(),
        ):
            chunks.append(chunk["tts_speech"])
        import torch

        audio = torch.cat(chunks, dim=1) if chunks else torch.zeros(1, 0)
        pcm = (audio[0].numpy() * 32767).astype("int16").tobytes()
        return TTSResult(
            pcm=pcm,
            sample_rate=self.sample_rate,
            text=text,
            backend=self.name,
            latency_ms=(time.perf_counter() - start) * 1000,
            meta={"clone": False},
        )

    def clone_voice(self, ref_pcm: bytes, text: str) -> TTSResult:
        """zero-shot 克隆：ref_pcm 为 3 秒参考音频（§6.1）。"""
        import time

        start = time.perf_counter()
        chunks = []
        for chunk in self.model.inference_zero_shot(text, self._default_ref_text(), self._ref_bytes(ref_pcm)):
            chunks.append(chunk["tts_speech"])
        import torch

        audio = torch.cat(chunks, dim=1) if chunks else torch.zeros(1, 0)
        pcm = (audio[0].numpy() * 32767).astype("int16").tobytes()
        return TTSResult(
            pcm=pcm,
            sample_rate=self.sample_rate,
            text=text,
            backend=self.name,
            latency_ms=(time.perf_counter() - start) * 1000,
            meta={"clone": True},
        )

    # ---- 内部（占位，接入时替换为真实参考音频）----

    @staticmethod
    def _default_ref_text() -> str:
        return "你好，我是 Aivy，你的私人助理。"

    @staticmethod
    def _default_ref_audio():
        import numpy as np

        return np.zeros(16000 * 3, dtype="int16")

    @staticmethod
    def _ref_bytes(pcm: bytes):
        import numpy as np

        return np.frombuffer(pcm, dtype="int16")
