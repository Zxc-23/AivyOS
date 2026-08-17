"""SenseVoice / FunASR 适配后端（文档 §3.1.1）。

funasr 为可选依赖：未安装时导入安全，实例化抛 ASRUnavailable（调用方降级 mock）。
接入方式：`AutoModel(model="iic/SenseVoiceSmall")`（SenseVoice）或
`AutoModel(model="paraformer-zh")`（FunASR/Paraformer），二者同属 FunASR 生态。
"""

from __future__ import annotations

from typing import Optional

from aivyos_core.asr.base import ASRBackend, ASRResult, ASRUnavailable


class FunASRBackend(ASRBackend):
    """SenseVoice / FunASR 本地推理（OpenAI 兼容 API 亦可，见备注）。"""

    name = "funasr"

    def __init__(
        self,
        model: str = "sensevoice-small",
        language: str = "zh",
        vad_model: Optional[str] = None,
        device: str = "cuda:0",
    ) -> None:
        self.model_name = model
        self.language = language
        self.device = device
        try:
            from funasr import AutoModel  # type: ignore
        except ImportError as e:
            raise ASRUnavailable(
                "funasr 未安装：pip install funasr（见 requirements-ml.txt）。"
                "已自动降级到 mock ASR。"
            ) from e
        model_map = {
            "sensevoice-small": "iic/SenseVoiceSmall",
            "paraformer-zh": "paraformer-zh",
            "paraformer-zh-streaming": "paraformer-zh-streaming",
        }
        self.model = AutoModel(
            model=model_map.get(model, model),
            vad_model=vad_model,
            device=device,
            disable_update=True,
        )

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> ASRResult:
        import io
        import wave

        # FunASR 需要文件/IO 输入：内存 WAV
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm)
        buf.seek(0)

        result = self.model.generate(
            input=buf,
            language=self.language,
            use_itn=True,
            batch_size_s=60,
        )
        text = ""
        confidence = 1.0
        if result:
            item = result[0]
            text = item.get("text", "")
            confidence = float(item.get("confidence", 1.0) or 1.0)
        return ASRResult(text=text, confidence=confidence, language=self.language, backend=self.name)
