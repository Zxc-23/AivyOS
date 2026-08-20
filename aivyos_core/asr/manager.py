"""ASR 后端选择：funasr 优先，云端ASR可选，缺失自动降级 mock（优雅降级）。"""

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
            - backend: 后端类型 (auto|funasr|mock|aliyun|tencent|doubao)
            - model: 模型名称
            - language: 识别语言
            - api_key: 云端ASR API Key
            - api_key_env: 云端ASR API Key 环境变量名
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

    # Mock后端
    if backend == "mock":
        return MockASR(language=language)

    # 云端ASR后端
    if backend == "aliyun":
        try:
            from aivyos_core.asr.cloud_backends import AliyunASRBackend
            return AliyunASRBackend(config=cfg)
        except Exception as e:
            log.warning("阿里云 ASR 初始化失败，降级 mock: %s", e)
            return MockASR(language=language)

    if backend == "tencent":
        try:
            from aivyos_core.asr.cloud_backends import TencentASRBackend
            return TencentASRBackend(config=cfg)
        except Exception as e:
            log.warning("腾讯云 ASR 初始化失败，降级 mock: %s", e)
            return MockASR(language=language)

    if backend == "doubao":
        try:
            from aivyos_core.asr.cloud_backends import DoubaoASRBackend
            return DoubaoASRBackend(config=cfg)
        except Exception as e:
            log.warning("豆包 ASR 初始化失败，降级 mock: %s", e)
            return MockASR(language=language)

    # 本地FunASR后端（默认/auto模式）
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
