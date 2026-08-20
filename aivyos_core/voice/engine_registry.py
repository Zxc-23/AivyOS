"""Phase 2 语音引擎注册表：统一管理 ASR/TTS 后端实例。

参考 LLM ProviderRegistry 设计模式，为语音引擎提供：
    - 注册表模式：动态注册/切换/管理 ASR/TTS 后端
    - 熔断保护：每个引擎独立熔断器
    - 健康检查：统一健康状态查询
    - 成本追踪：云端引擎 token/费用统计
    - Mock 降级：无依赖时自动回退到 Mock 引擎

对应报告 §6.1.2 语音引擎升级任务。
"""

from __future__ import annotations

import inspect
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Type

from aivyos_core.asr.base import ASRBackend, ASRResult
from aivyos_core.llm.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry
from aivyos_core.llm.cost_tracker import CostTracker
from aivyos_core.tts.base import TTSBackend, TTSResult

log = logging.getLogger(__name__)


@dataclass
class EngineInfo:
    """引擎元数据。"""
    name: str
    engine_type: str  # "asr" | "tts"
    provider: str = ""
    model: str = ""
    enabled: bool = True
    priority: int = 50
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EngineStatus:
    """引擎健康状态。"""
    name: str
    engine_type: str
    status: str = "unknown"  # "ok" | "degraded" | "down"
    latency_ms: float = 0.0
    detail: str = ""
    last_check: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _safe_instantiate(backend_cls: Type, config: Optional[Dict[str, Any]] = None):
    """安全实例化后端，仅在构造函数接受 config 参数时传入。"""
    sig = inspect.signature(backend_cls.__init__)
    if "config" in sig.parameters:
        return backend_cls(config=config or {})
    return backend_cls()


class VoiceEngineRegistry:
    """ASR/TTS 引擎统一注册表（线程安全）。

    用法：
        reg = VoiceEngineRegistry()
        reg.register_asr("funasr", FunASRBackend)
        reg.register_tts("cosyvoice", CosyVoiceBackend)
        asr = reg.create_asr("funasr")
        result = reg.transcribe(asr, pcm_data)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._asr_types: Dict[str, Type[ASRBackend]] = {}
        self._tts_types: Dict[str, Type[TTSBackend]] = {}
        self._instances: Dict[str, Any] = {}
        self._infos: Dict[str, EngineInfo] = {}
        self._breakers = CircuitBreakerRegistry()
        self._cost_tracker = CostTracker()
        self._status_cache: Dict[str, EngineStatus] = {}

    # ====================================================================
    #  注册
    # ====================================================================

    def register_asr(
        self, name: str, backend_cls: Type[ASRBackend]
    ) -> None:
        """注册 ASR 引擎类型。

        Args:
            name: 引擎唯一名称（如 "funasr"、"whisper"）。
            backend_cls: ASRBackend 子类。
        """
        with self._lock:
            self._asr_types[name] = backend_cls

    def register_tts(
        self, name: str, backend_cls: Type[TTSBackend]
    ) -> None:
        """注册 TTS 引擎类型。

        Args:
            name: 引擎唯一名称（如 "cosyvoice"、"gpt-sovits"）。
            backend_cls: TTSBackend 子类。
        """
        with self._lock:
            self._tts_types[name] = backend_cls

    # ====================================================================
    #  实例化
    # ====================================================================

    def create_asr(
        self,
        name: str,
        provider: str = "",
        model: str = "",
        priority: int = 50,
        config: Optional[Dict[str, Any]] = None,
        engine_type: Optional[str] = None,
    ) -> ASRBackend:
        """实例化 ASR 引擎。

        Args:
            name: 引擎实例名称（唯一标识）。
            provider: 提供商类型。
            model: 模型名。
            priority: 优先级。
            config: 引擎配置。
            engine_type: 引擎类型名（默认使用 name 查找类型）。

        Returns:
            ASRBackend 实例。

        Raises:
            ValueError: 引擎类型未注册。
        """
        with self._lock:
            # 优先用 engine_type 查找类型，再用 name 查找
            type_name = engine_type or name
            if type_name not in self._asr_types:
                # 尝试查找包含 mock 的类型
                if "mock" in self._asr_types:
                    type_name = "mock"
                else:
                    raise ValueError(
                        f"ASR 引擎 '{type_name}' 未注册，可选: {list(self._asr_types.keys())}"
                    )
            backend = _safe_instantiate(self._asr_types[type_name], config)
            info = EngineInfo(
                name=name,
                engine_type="asr",
                provider=provider,
                model=model,
                priority=priority,
                config=config or {},
            )
            self._instances[name] = backend
            self._infos[name] = info
            self._breakers.get_or_create(
                name,
                failure_threshold=info.config.get("breaker_threshold", 3),
                cooldown_seconds=info.config.get("breaker_cooldown_s", 60.0),
            )
            return backend

    def create_tts(
        self,
        name: str,
        provider: str = "",
        model: str = "",
        priority: int = 50,
        config: Optional[Dict[str, Any]] = None,
        engine_type: Optional[str] = None,
    ) -> TTSBackend:
        """实例化 TTS 引擎。

        Args:
            name: 引擎实例名称（唯一标识）。
            provider: 提供商类型。
            model: 模型名。
            priority: 优先级。
            config: 引擎配置。
            engine_type: 引擎类型名（默认使用 name 查找类型）。

        Returns:
            TTSBackend 实例。

        Raises:
            ValueError: 引擎类型未注册。
        """
        with self._lock:
            type_name = engine_type or name
            if type_name not in self._tts_types:
                if "mock" in self._tts_types:
                    type_name = "mock"
                else:
                    raise ValueError(
                        f"TTS 引擎 '{type_name}' 未注册，可选: {list(self._tts_types.keys())}"
                    )
            backend = _safe_instantiate(self._tts_types[type_name], config)
            info = EngineInfo(
                name=name,
                engine_type="tts",
                provider=provider,
                model=model,
                priority=priority,
                config=config or {},
            )
            self._instances[name] = backend
            self._infos[name] = info
            self._breakers.get_or_create(
                name,
                failure_threshold=info.config.get("breaker_threshold", 3),
                cooldown_seconds=info.config.get("breaker_cooldown_s", 60.0),
            )
            return backend

    def get(self, name: str) -> Optional[Any]:
        """获取已实例化的引擎。

        Args:
            name: 引擎名称。

        Returns:
            引擎实例或 None。
        """
        return self._instances.get(name)

    def remove(self, name: str) -> bool:
        """移除引擎实例。

        Args:
            name: 引擎名称。

        Returns:
            是否成功移除。
        """
        with self._lock:
            existed = name in self._instances
            self._instances.pop(name, None)
            self._infos.pop(name, None)
            return existed

    # ====================================================================
    #  核心调用（带熔断保护）
    # ====================================================================

    def transcribe(
        self, name: str, pcm: bytes, sample_rate: int = 16000
    ) -> ASRResult:
        """执行 ASR 转录（带熔断保护）。

        Args:
            name: 引擎名称。
            pcm: 16-bit PCM 音频数据。
            sample_rate: 采样率。

        Returns:
            ASRResult 识别结果。

        Raises:
            RuntimeError: 引擎不可用或熔断中。
        """
        backend = self._instances.get(name)
        if not backend:
            raise RuntimeError(f"ASR 引擎 '{name}' 不存在")

        if not self._breakers.can_execute(name):
            raise RuntimeError(f"ASR 引擎 '{name}' 熔断中")

        start = time.monotonic()
        try:
            result = backend.transcribe(pcm, sample_rate)
            self._breakers.record_success(name)
            latency = (time.monotonic() - start) * 1000
            self._update_status(name, "ok", latency)
            return result
        except Exception as e:
            self._breakers.record_failure(name)
            self._update_status(name, "down", detail=str(e))
            raise

    def synthesize(self, name: str, text: str) -> TTSResult:
        """执行 TTS 合成（带熔断保护）。

        Args:
            name: 引擎名称。
            text: 要合成的文本。

        Returns:
            TTSResult 合成结果。

        Raises:
            RuntimeError: 引擎不可用或熔断中。
        """
        backend = self._instances.get(name)
        if not backend:
            raise RuntimeError(f"TTS 引擎 '{name}' 不存在")

        if not self._breakers.can_execute(name):
            raise RuntimeError(f"TTS 引擎 '{name}' 熔断中")

        start = time.monotonic()
        try:
            result = backend.synthesize(text)
            self._breakers.record_success(name)
            latency = (time.monotonic() - start) * 1000
            self._update_status(name, "ok", latency)
            # 成本追踪（按字符数估算 token）
            char_count = len(text)
            self._cost_tracker.record(
                backend_name=name,
                input_tokens=char_count,
                output_tokens=char_count,
                latency_ms=latency,
                provider=self._infos.get(name, EngineInfo(name, "tts")).provider,
                model=self._infos.get(name, EngineInfo(name, "tts")).model,
            )
            return result
        except Exception as e:
            self._breakers.record_failure(name)
            self._update_status(name, "down", detail=str(e))
            raise

    # ====================================================================
    #  状态查询
    # ====================================================================

    def list_engines(self, engine_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出所有已实例化引擎。

        Args:
            engine_type: 过滤类型（None=全部, "asr", "tts"）。

        Returns:
            引擎信息列表。
        """
        results = []
        for name, info in self._infos.items():
            if engine_type and info.engine_type != engine_type:
                continue
            backend = self._instances.get(name)
            status = self._status_cache.get(name, EngineStatus(name, info.engine_type))
            breaker_stats = self._breakers.get_stats(name)
            results.append({
                "name": name,
                "type": info.engine_type,
                "provider": info.provider,
                "model": info.model,
                "enabled": info.enabled,
                "status": status.to_dict(),
                "breaker": breaker_stats,
                "available": self._breakers.can_execute(name),
            })
        return results

    def health_check(self, name: str) -> EngineStatus:
        """执行引擎健康检查。

        Args:
            name: 引擎名称。

        Returns:
            EngineStatus 健康状态。
        """
        backend = self._instances.get(name)
        if not backend:
            return EngineStatus(name, "unknown", status="down", detail="引擎不存在")

        start = time.monotonic()
        try:
            if isinstance(backend, ASRBackend):
                _ = backend.transcribe(b"", 16000)
            elif isinstance(backend, TTSBackend):
                _ = backend.synthesize("")
            latency = (time.monotonic() - start) * 1000
            status = EngineStatus(
                name,
                self._infos.get(name, EngineInfo(name, "")).engine_type,
                status="ok",
                latency_ms=latency,
                last_check=time.monotonic(),
            )
        except Exception as e:
            status = EngineStatus(
                name,
                self._infos.get(name, EngineInfo(name, "")).engine_type,
                status="down",
                detail=str(e),
                last_check=time.monotonic(),
            )
        self._status_cache[name] = status
        return status

    def get_dashboard(self) -> Dict[str, Any]:
        """获取语音引擎仪表盘。

        Returns:
            仪表盘数据。
        """
        engines = self.list_engines()
        return {
            "total_engines": len(engines),
            "asr_count": sum(1 for e in engines if e["type"] == "asr"),
            "tts_count": sum(1 for e in engines if e["type"] == "tts"),
            "engines": engines,
            "breakers": self._breakers.get_all_stats(),
            "cost": self._cost_tracker.get_dashboard(),
        }

    # ====================================================================
    #  内部
    # ====================================================================

    def _update_status(
        self, name: str, status: str, latency_ms: float = 0.0, detail: str = ""
    ) -> None:
        """更新引擎状态缓存。"""
        info = self._infos.get(name)
        eng_type = info.engine_type if info else "unknown"
        self._status_cache[name] = EngineStatus(
            name=name,
            engine_type=eng_type,
            status=status,
            latency_ms=latency_ms,
            detail=detail,
            last_check=time.monotonic(),
        )


def register_asr_engines(registry: VoiceEngineRegistry) -> None:
    """注册所有内置 ASR 引擎类型（含本地+云端）。

    Args:
        registry: VoiceEngineRegistry 实例。
    """
    # 本地引擎
    try:
        from aivyos_core.asr.funasr_backend import FunASRBackend
        registry.register_asr("funasr", FunASRBackend)
    except ImportError:
        log.info("FunASR 未安装，跳过注册")

    try:
        from aivyos_core.asr.mock_backend import MockASR
        registry.register_asr("mock", MockASR)
    except ImportError:
        pass

    # 云端引擎
    try:
        from aivyos_core.asr.cloud_backends import (
            AliyunASRBackend, TencentASRBackend, DoubaoASRBackend,
        )
        registry.register_asr("aliyun", AliyunASRBackend)
        registry.register_asr("tencent", TencentASRBackend)
        registry.register_asr("doubao", DoubaoASRBackend)
    except ImportError as e:
        log.warning("云端 ASR 引擎加载失败: %s", e)


def register_tts_engines(registry: VoiceEngineRegistry) -> None:
    """注册所有内置 TTS 引擎类型（含本地+云端）。

    Args:
        registry: VoiceEngineRegistry 实例。
    """
    # 本地引擎
    try:
        from aivyos_core.tts.cosyvoice_backend import CosyVoiceBackend
        registry.register_tts("cosyvoice", CosyVoiceBackend)
    except ImportError:
        log.info("CosyVoice 未安装，跳过注册")

    try:
        from aivyos_core.tts.mock_backend import MockTTS
        registry.register_tts("mock", MockTTS)
    except ImportError:
        pass

    # 云端引擎
    try:
        from aivyos_core.tts.doubao_backend import DoubaoTTSBackend
        registry.register_tts("doubao", DoubaoTTSBackend)
    except ImportError as e:
        log.warning("豆包 TTS 引擎加载失败: %s", e)

    # 已有云端引擎（cloud_engines.py）
    try:
        from aivyos_core.voice.cloud_engines import ElevenLabsBackend, EdgeTTSBackend
        registry.register_tts("elevenlabs", ElevenLabsBackend)
        registry.register_tts("edge-tts", EdgeTTSBackend)
    except ImportError as e:
        log.warning("云端 TTS 引擎加载失败: %s", e)

    try:
        from aivyos_core.voice.cloud_engines import DeepgramBackend
        registry.register_asr("deepgram", DeepgramBackend)
    except ImportError as e:
        log.warning("Deepgram ASR 引擎加载失败: %s", e)


def create_voice_registry(config: Optional[Dict[str, Any]] = None) -> VoiceEngineRegistry:
    """创建并初始化语音引擎注册表。

    Args:
        config: 全局配置字典。

    Returns:
        初始化后的 VoiceEngineRegistry 实例。
    """
    reg = VoiceEngineRegistry()
    register_asr_engines(reg)
    register_tts_engines(reg)

    cfg = config or {}
    asr_cfg = cfg.get("asr", {})
    tts_cfg = cfg.get("tts", {})

    # 实例化 ASR（本地 + 云端）
    asr_backend = asr_cfg.get("backend", "mock")
    asr_name = f"asr-{asr_backend}" if asr_backend != "auto" else "asr-mock"
    # 支持所有已注册的 ASR 类型
    try:
        reg.create_asr(
            asr_name,
            provider=asr_backend,
            model=asr_cfg.get("model", ""),
            config=asr_cfg,
        )
    except ValueError:
        try:
            reg.create_asr("asr-mock", config=asr_cfg)
        except ValueError:
            pass

    # 实例化 TTS（本地 + 云端）
    tts_backend = tts_cfg.get("backend", "auto")
    if tts_backend == "auto":
        # auto 模式：智能检测可用的 TTS
        import os as _os
        auto_tts_name = "tts-mock"
        auto_tts_provider = "mock"

        # 1) 豆包
        if _os.environ.get("VOLCENGINE_API_KEY") or tts_cfg.get("api_key"):
            try:
                reg.create_tts("tts-doubao", provider="doubao", config=tts_cfg)
                auto_tts_name = "tts-doubao"
                auto_tts_provider = "doubao"
            except ValueError:
                pass

        # 2) ElevenLabs
        if auto_tts_provider == "mock" and _os.environ.get("ELEVENLABS_API_KEY"):
            try:
                reg.create_tts("tts-elevenlabs", provider="elevenlabs", config=tts_cfg)
                auto_tts_name = "tts-elevenlabs"
                auto_tts_provider = "elevenlabs"
            except ValueError:
                pass

        # 3) CosyVoice
        if auto_tts_provider == "mock":
            try:
                reg.create_tts("tts-cosyvoice", provider="cosyvoice", config=tts_cfg)
                auto_tts_name = "tts-cosyvoice"
                auto_tts_provider = "cosyvoice"
            except ValueError:
                pass

        # 4) Edge-TTS（免费，无需 API Key）
        if auto_tts_provider == "mock":
            try:
                reg.create_tts("tts-edge", provider="edge-tts", config=tts_cfg)
                auto_tts_name = "tts-edge"
                auto_tts_provider = "edge-tts"
            except ValueError:
                pass

        # 5) 兜底 mock
        if auto_tts_provider == "mock":
            try:
                reg.create_tts("tts-mock", provider="mock", config=tts_cfg)
            except ValueError:
                pass
    else:
        # 明确指定的后端
        tts_name = f"tts-{tts_backend}"
        try:
            reg.create_tts(
                tts_name,
                provider=tts_backend,
                model=tts_cfg.get("model", ""),
                config=tts_cfg,
            )
        except ValueError:
            try:
                reg.create_tts("tts-mock", config=tts_cfg)
            except ValueError:
                pass

    return reg