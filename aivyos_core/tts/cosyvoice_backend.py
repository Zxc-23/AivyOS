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

    def __init__(self, model: str = "CosyVoice3-0.5B", clone_seconds: int = 3, clone_ref_path: str | None = None) -> None:
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice3  # type: ignore
        except ImportError as e:
            raise TTSUnavailable(
                "cosyvoice 未安装：pip install cosyvoice（见 requirements-ml.txt）。"
                "已自动降级到 mock TTS。"
            ) from e
        self.model = CosyVoice3(model, load_jit=False, load_trt=False, fp16=False)
        self.clone_seconds = clone_seconds
        self._ref_pcm: Optional[bytes] = None
        if clone_ref_path:
            from aivyos_core.audio.wav import read_wav

            _, self._ref_pcm = read_wav(clone_ref_path)

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

    def clone_voice(self, ref_pcm: Optional[bytes] = None, text: str = "") -> TTSResult:
        """zero-shot 克隆（§6.1）：ref_pcm 为 3 秒参考音频；缺省用配置 clone_ref_path。"""
        if text == "":
            return self.synthesize(text="")
        ref = ref_pcm if ref_pcm is not None else self._ref_pcm
        import time

        start = time.perf_counter()
        chunks = []
        for chunk in self.model.inference_zero_shot(text, self._default_ref_text(), self._ref_bytes(ref)):
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
            meta={"clone": True, "ref_source": "configured" if self._ref_pcm else "provided/zero"},
        )

    # ---- 内部 ----

    @staticmethod
    def _default_ref_text() -> str:
        return "你好，我是 Aivy，你的私人助理。"

    @staticmethod
    def _default_ref_audio():
        import numpy as np

        return np.zeros(16000 * 3, dtype="int16")

    @staticmethod
    def _ref_bytes(pcm: Optional[bytes]):
        import numpy as np

        if pcm is None:
            return np.zeros(16000 * 3, dtype="int16")  # 未配置参考样本 → 零向量（占位音色）
        return np.frombuffer(pcm, dtype="int16")
