"""ASR 语音识别层（文档 §3.1.1：SenseVoice / FunASR(Paraformer) 流式）。"""

from aivyos_core.asr.base import ASRBackend, ASRResult, ASRUnavailable
from aivyos_core.asr.funasr_backend import FunASRBackend
from aivyos_core.asr.mock_backend import MockASR
from aivyos_core.asr.manager import create_asr

__all__ = ["ASRBackend", "ASRResult", "ASRUnavailable", "FunASRBackend", "MockASR", "create_asr"]
