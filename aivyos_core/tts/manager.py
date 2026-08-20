"""TTS 后端选择：云端优先 → cosyvoice 本地 → mock 优雅降级。

支持的 provider：
- doubao-tts / doubao  — 豆包 TTS（火山引擎 V3 API）
- edge-tts / edge      — Edge-TTS（微软免费，无需 API Key）
- elevenlabs           — ElevenLabs（国际）
- cosyvoice            — CosyVoice 3 本地模型
- auto                 — 自动检测（云端 → 本地 → mock）
- mock                 — 强制 mock
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from aivyos_core.tts.base import TTSBackend, TTSUnavailable
from aivyos_core.tts.cosyvoice_backend import CosyVoiceBackend
from aivyos_core.tts.mock_backend import MockTTS

log = logging.getLogger(__name__)

# 云端 TTS → 需要的环境变量
_CLOUD_TTS_ENV_MAP: Dict[str, str] = {
    "doubao-tts": "VOLCENGINE_API_KEY",
    "doubao": "VOLCENGINE_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
}

# 始终可用的云端 TTS（无需 API Key）
_ALWAYS_AVAILABLE_TTS = {"edge-tts", "edge"}


def _try_doubao(cfg: Dict[str, Any]) -> Optional[TTSBackend]:
    """尝试创建豆包 TTS 后端。"""
    api_key = cfg.get("api_key") or os.environ.get("VOLCENGINE_API_KEY", "")
    if not api_key:
        return None
    try:
        from aivyos_core.tts.doubao_backend import DoubaoTTSBackend
        voice = cfg.get("voice", "zh_female_xiaohe_uranus_bigtts")
        if not voice or "bigtts" not in voice:
            voice = "zh_female_xiaohe_uranus_bigtts"
        resource_id = cfg.get("resource_id") or "seed-tts-2.0"
        return DoubaoTTSBackend(config={
            "api_key": api_key,
            "resource_id": resource_id,
            "voice_type": voice,
            "speed_ratio": float(cfg.get("speed", 1.0)),
            "sample_rate": int(cfg.get("sample_rate", 24000)),
        })
    except ImportError as e:
        log.warning("豆包 TTS 模块导入失败: %s", e)
        return None
    except Exception as e:
        log.warning("豆包 TTS 初始化失败: %s", e)
        return None


def _try_edge(cfg: Dict[str, Any]) -> Optional[TTSBackend]:
    """尝试创建 Edge-TTS 后端（始终可用，无需 API Key）。"""
    try:
        # 先验证 edge_tts 包是否可用
        import edge_tts  # noqa: F401
    except ImportError:
        log.warning("Edge-TTS 未安装: pip install edge-tts")
        return None

    try:
        from aivyos_core.voice.cloud_engines import EdgeTTSBackend
        voice = cfg.get("voice", "zh-CN-XiaoxiaoNeural")
        if "Neural" not in voice:
            voice = "zh-CN-XiaoxiaoNeural"
        speed = float(cfg.get("speed", 1.0))
        rate_str = f"+{int((speed - 1) * 100)}%" if speed != 1.0 else "+0%"
        return EdgeTTSBackend(config={"voice": voice, "rate": rate_str})
    except ImportError as e:
        log.warning("Edge-TTS 模块导入失败: %s", e)
        return None
    except Exception as e:
        log.warning("Edge-TTS 初始化失败: %s", e)
        return None


def _try_elevenlabs(cfg: Dict[str, Any]) -> Optional[TTSBackend]:
    """尝试创建 ElevenLabs 后端。"""
    api_key = cfg.get("api_key") or os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        return None
    try:
        from aivyos_core.voice.cloud_engines import ElevenLabsBackend
        return ElevenLabsBackend(config={
            "api_key_env": "",
            "voice_id": cfg.get("voice_id", "21m00Tcm4TlvDq8ikXViFdi"),
            "model_id": cfg.get("model_id", "eleven_multilingual_v2"),
            "sample_rate": int(cfg.get("sample_rate", 24000)),
        })
    except ImportError as e:
        log.warning("ElevenLabs 模块导入失败: %s", e)
        return None
    except Exception as e:
        log.warning("ElevenLabs 初始化失败: %s", e)
        return None


def _try_cosyvoice(cfg: Dict[str, Any]) -> Optional[TTSBackend]:
    """尝试创建 CosyVoice 本地 TTS 后端。"""
    try:
        return CosyVoiceBackend(
            model=cfg.get("model", "CosyVoice3-0.5B"),
            clone_seconds=int(cfg.get("clone_seconds", 3)),
            clone_ref_path=cfg.get("clone_ref_path"),
        )
    except TTSUnavailable:
        return None
    except Exception as e:
        log.warning("CosyVoice 初始化失败: %s", e)
        return None


def create_tts(cfg: Dict[str, Any]) -> TTSBackend:
    """根据配置创建 TTS 后端（云端优先 → 本地 → mock）。

    Args:
        cfg: TTS 配置字典，支持以下 key：
            - backend: 后端名称（auto/doubao-tts/edge-tts/elevenlabs/cosyvoice/mock）
            - api_key: 云端 API Key（覆盖环境变量）
            - voice: 音色 ID
            - speed: 语速倍率
            - resource_id: 豆包资源 ID
            - model: CosyVoice 模型名

    Returns:
        TTSBackend 实例。
    """
    backend = (cfg.get("backend", "auto") or "auto").lower()
    sample_rate = int(cfg.get("sample_rate", 24000))

    if backend == "mock":
        return MockTTS(sample_rate=sample_rate)

    # ── 明确指定云端提供商 ──
    if backend in ("doubao-tts", "doubao", "bytedance", "volcengine"):
        result = _try_doubao(cfg)
        if result:
            log.info("TTS 后端：豆包（云端）")
            return result
        log.warning("指定豆包 TTS 但初始化失败，降级 mock")
        return MockTTS(sample_rate=sample_rate)

    if backend in ("edge-tts", "edge"):
        result = _try_edge(cfg)
        if result:
            log.info("TTS 后端：Edge-TTS（云端免费）")
            return result
        log.warning("指定 Edge-TTS 但初始化失败，降级 mock")
        return MockTTS(sample_rate=sample_rate)

    if backend == "elevenlabs":
        result = _try_elevenlabs(cfg)
        if result:
            log.info("TTS 后端：ElevenLabs（云端）")
            return result
        log.warning("指定 ElevenLabs 但初始化失败，降级 mock")
        return MockTTS(sample_rate=sample_rate)

    if backend == "cosyvoice":
        result = _try_cosyvoice(cfg)
        if result:
            log.info("TTS 后端：CosyVoice 本地")
            return result
        log.warning("指定 CosyVoice 但不可用，降级 mock")
        return MockTTS(sample_rate=sample_rate)

    # ── auto：智能检测 ──
    # 1) 豆包（配置 API Key 或环境变量）
    if cfg.get("api_key") or os.environ.get("VOLCENGINE_API_KEY"):
        result = _try_doubao(cfg)
        if result:
            log.info("auto 模式检测到豆包 API Key，使用云端豆包 TTS")
            return result

    # 2) ElevenLabs
    if os.environ.get("ELEVENLABS_API_KEY"):
        result = _try_elevenlabs(cfg)
        if result:
            log.info("auto 模式检测到 ElevenLabs API Key，使用云端 ElevenLabs")
            return result

    # 3) CosyVoice 本地
    result = _try_cosyvoice(cfg)
    if result:
        log.info("auto 模式使用 CosyVoice 本地 TTS")
        return result

    # 4) Edge-TTS（始终可用，免费云端）
    result = _try_edge(cfg)
    if result:
        log.info("auto 模式使用 Edge-TTS 免费云端")
        return result

    # 5) 兜底 mock
    log.info("auto 模式无可用 TTS，降级 mock")
    return MockTTS(sample_rate=sample_rate)