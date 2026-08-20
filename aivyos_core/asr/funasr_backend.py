"""SenseVoice / FunASR 适配后端（文档 §3.1.1）。

funasr 为可选依赖：未安装时导入安全，实例化抛 ASRUnavailable（调用方降级 mock）。
接入方式：`AutoModel(model="iic/SenseVoiceSmall")`（SenseVoice）或
`AutoModel(model="paraformer-zh")`（FunASR/Paraformer），二者同属 FunASR 生态。

v2 改进：添加语音预过滤，避免对静音/纯噪音产生幻觉输出。
"""

from __future__ import annotations

import math
import re
import struct
from typing import Optional

from aivyos_core.asr.base import ASRBackend, ASRResult, ASRUnavailable


def _rms_energy(pcm: bytes) -> float:
    """计算 PCM 音频的 RMS 能量值。

    Args:
        pcm: 16-bit PCM 字节数据

    Returns:
        RMS 能量值，范围 0-32767
    """
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    total = 0.0
    for i in range(n):
        (s,) = struct.unpack_from("<h", pcm, i * 2)
        total += float(s) * float(s)
    return math.sqrt(total / n)


def _has_speech(pcm: bytes, threshold: float = 15.0, min_ratio: float = 0.05) -> bool:
    """检测 PCM 音频是否包含有效语音。

    通过帧级 RMS 能量检测 + 波峰因子（crest factor）分析，
    区分真实语音与环境噪音/纯音调。

    判定逻辑:
    1. 低于 RMS 阈值的帧数占比不足 min_ratio → 噪音
    2. 平均 RMS 过低 → 噪音
    3. 波峰因子过低 (< 2.5) → 纯音/机械噪音
    4. 波峰因子足够 (>= 2.5) 且 RMS 达标 → 语音

    Args:
        pcm: 16-bit PCM 字节数据
        threshold: 单帧 RMS 能量阈值
        min_ratio: 最小语音帧比例（低于此值视为无语音）

    Returns:
        True 表示包含有效语音
    """
    frame_size = 512  # 32ms @ 16kHz
    n_frames = len(pcm) // (frame_size * 2)
    if n_frames == 0:
        return False

    speech_frames = 0
    peak_sum = 0.0
    rms_sum = 0.0
    rms_values = []
    for i in range(n_frames):
        offset = i * frame_size * 2
        frame = pcm[offset : offset + frame_size * 2]
        rms = _rms_energy(frame)
        rms_sum += rms
        rms_values.append(rms)
        if rms > threshold:
            speech_frames += 1
            peak = 0.0
            for j in range(len(frame) // 2):
                (s,) = struct.unpack_from("<h", frame, j * 2)
                peak = max(peak, abs(float(s)))
            peak_sum += peak

    ratio = speech_frames / n_frames
    if ratio < min_ratio:
        return False

    avg_rms = rms_sum / n_frames
    if avg_rms < threshold * 0.8:
        return False

    max_rms = max(rms_values) if rms_values else 0
    dynamic_range = max_rms / avg_rms if avg_rms > 0 else 1.0

    if speech_frames > 0 and avg_rms > 1.0:
        avg_peak = peak_sum / speech_frames
        crest_factor = avg_peak / avg_rms if avg_rms > 0 else 999

        if crest_factor < 1.8:
            return False

        if crest_factor < 2.5 and avg_rms < threshold * 1.5:
            return False

        if crest_factor < 2.0 and dynamic_range < 1.5:
            return False

    return True


class FunASRBackend(ASRBackend):
    """SenseVoice / FunASR 本地推理（OpenAI 兼容 API 亦可，见备注）。"""

    name = "funasr"

    def __init__(
        self,
        model: str = "sensevoice-small",
        language: str = "zh",
        vad_model: Optional[str] = None,
        device: str = "cpu",
        silence_threshold: float = 15.0,
        silence_min_ratio: float = 0.05,
    ) -> None:
        """初始化 FunASR 后端。

        Args:
            model: 模型名称 (sensevoice-small, paraformer-zh)
            language: 识别语言 (zh, en)
            vad_model: VAD 模型名称（可选）
            device: 推理设备 (cpu, cuda)
            silence_threshold: 静音检测 RMS 阈值（0=禁用预过滤）
            silence_min_ratio: 静音检测最小语音帧比例
        """
        self.model_name = model
        self.language = language
        self.device = device
        self.silence_threshold = silence_threshold
        self.silence_min_ratio = silence_min_ratio
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
        try:
            self.model = AutoModel(
                model=model_map.get(model, model),
                vad_model=vad_model,
                device=device,
                disable_update=True,
            )
        except Exception as e:
            raise ASRUnavailable(
                f"FunASR 模型加载失败: {e}"
            ) from e

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> ASRResult:
        """将 PCM 音频转写为文本。

        包含语音预过滤逻辑：当音频中有效语音帧比例低于阈值时，
        直接返回空结果，避免模型对静音/噪音产生幻觉输出。

        Args:
            pcm: 16-bit PCM 字节数据
            sample_rate: 采样率

        Returns:
            ASRResult 转写结果
        """
        import io
        import wave

        if self.silence_threshold > 0:
            if not _has_speech(pcm, self.silence_threshold, self.silence_min_ratio):
                return ASRResult(text="", confidence=0.0, language=self.language, backend=self.name)

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
            text = re.sub(r"<\|[^>]+\|>", "", text).strip()
            if text in ("。", ".", "嗯", "啊", "哦", "嗯。"):
                text = ""
        return ASRResult(text=text, confidence=confidence, language=self.language, backend=self.name)
