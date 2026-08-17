"""TTS 后端选择：cosyvoice 优先，缺失自动降级 mock（优雅降级）。"""

from __future__ import annotations

import logging
from typing import Any, Dict

from aivyos_core.tts.base import TTSBackend, TTSUnavailable
from aivyos_core.tts.cosyvoice_backend import CosyVoiceBackend
from aivyos_core.tts.mock_backend import MockTTS

log = logging.getLogger(__name__)


def create_tts(cfg: Dict[str, Any]) -> TTSBackend:
    backend = cfg.get("backend", "auto")
    model = cfg.get("model", "CosyVoice3-0.5B")
    sample_rate = int(cfg.get("sample_rate", 24000))
    clone_seconds = int(cfg.get("clone_seconds", 3))

    if backend == "mock":
        return MockTTS(sample_rate=sample_rate)

    if backend in ("cosyvoice", "auto"):
        try:
            return CosyVoiceBackend(
                model=model,
                clone_seconds=clone_seconds,
                clone_ref_path=cfg.get("clone_ref_path"),
            )
        except TTSUnavailable as e:
            if backend == "cosyvoice":
                log.warning("配置要求 cosyvoice 但不可用：%s", e)
            else:
                log.info("cosyvoice 不可用，降级 mock TTS：%s", e)
    return MockTTS(sample_rate=sample_rate)
