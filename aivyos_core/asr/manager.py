"""ASR 后端选择：funasr 优先，缺失自动降级 mock（优雅降级）。"""

from __future__ import annotations

import logging
from typing import Any, Dict

from aivyos_core.asr.base import ASRBackend, ASRUnavailable
from aivyos_core.asr.funasr_backend import FunASRBackend
from aivyos_core.asr.mock_backend import MockASR

log = logging.getLogger(__name__)


def create_asr(cfg: Dict[str, Any]) -> ASRBackend:
    """按配置创建 ASR 后端实例。

    Args:
        cfg: ASR 配置字典，支持以下键:
            - backend: 后端类型 (auto|funasr|mock)
            - model: 模型名称
            - language: 识别语言
            - silence_threshold: 静音检测 RMS 阈值
            - silence_min_ratio: 静音检测最小语音帧比例

    Returns:
        ASRBackend 实例
    """
    backend = cfg.get("backend", "auto")
    model = cfg.get("model", "sensevoice-small")
    language = cfg.get("language", "zh")
    silence_threshold = float(cfg.get("silence_threshold", 15.0))
    silence_min_ratio = float(cfg.get("silence_min_ratio", 0.05))

    if backend == "mock":
        return MockASR(language=language)

    if backend in ("funasr", "auto"):
        try:
            return FunASRBackend(
                model=model,
                language=language,
                silence_threshold=silence_threshold,
                silence_min_ratio=silence_min_ratio,
            )
        except ASRUnavailable as e:
            if backend == "funasr":
                log.warning("配置要求 funasr 但不可用：%s", e)
            else:
                log.info("funasr 不可用，降级 mock ASR：%s", e)
    return MockASR(language=language)
