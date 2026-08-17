"""ASR 后端选择：funasr 优先，缺失自动降级 mock（优雅降级）。"""

from __future__ import annotations

import logging
from typing import Any, Dict

from aivyos_core.asr.base import ASRBackend, ASRUnavailable
from aivyos_core.asr.funasr_backend import FunASRBackend
from aivyos_core.asr.mock_backend import MockASR

log = logging.getLogger(__name__)


def create_asr(cfg: Dict[str, Any]) -> ASRBackend:
    backend = cfg.get("backend", "auto")
    model = cfg.get("model", "sensevoice-small")
    language = cfg.get("language", "zh")

    if backend == "mock":
        return MockASR(language=language)

    if backend in ("funasr", "auto"):
        try:
            return FunASRBackend(model=model, language=language)
        except ASRUnavailable as e:
            if backend == "funasr":
                log.warning("配置要求 funasr 但不可用：%s", e)
            else:
                log.info("funasr 不可用，降级 mock ASR：%s", e)
    return MockASR(language=language)
