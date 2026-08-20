"""Phase 2 云端语音引擎适配器（接口定义 + Mock 降级）。

提供 ElevenLabs TTS、Edge-TTS、Deepgram ASR 的抽象基类，
所有云端引擎在无 API Key 时自动降级到 Mock 实现。

设计原则：
    - 适配器模式：每个云端引擎实现统一接口
    - 优雅降级：无依赖/无 Key 时自动回退 mock
    - 熔断器保护：集成 VoiceEngineRegistry 熔断机制
    - 成本追踪：Token/字符用量统计

对应报告 §6.1.2 云端 TTS/ASR 集成任务。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

from aivyos_core.asr.base import ASRBackend, ASRResult
from aivyos_core.tts.base import TTSBackend, TTSResult

log = logging.getLogger(__name__)


class CloudTTSBackend(TTSBackend):
    """云端 TTS 适配器基类。

    子类需实现 _synthesize_cloud() 方法。
    提供：API Key 读取、URL 请求、错误降级、熔断友好。
    """

    name = "cloud-tts-base"

    def __init__(self, api_key_env: str = "", base_url: str = "") -> None:
        """初始化云端 TTS。

        Args:
            api_key_env: API Key 环境变量名。
            base_url: API 基础 URL。
        """
        self._api_key_env = api_key_env
        self._base_url = base_url
        self._api_key = os.environ.get(api_key_env, "")
        self._available = bool(self._api_key)

    @property
    def available(self) -> bool:
        """引擎是否可用（有 API Key）。"""
        return self._available

    def synthesize(self, text: str) -> TTSResult:
        """合成语音（云端调用 + mock 降级）。

        Args:
            text: 要合成的文本。

        Returns:
            TTSResult 合成结果。
        """
        if not self._available:
            return self._mock_synthesize(text)

        try:
            return self._synthesize_cloud(text)
        except Exception as e:
            log.error("云端 TTS 调用失败: %s，降级 mock", e)
            return self._mock_synthesize(text)

    def _synthesize_cloud(self, text: str) -> TTSResult:
        """云端合成实现（子类覆盖）。

        Args:
            text: 文本。

        Returns:
            TTSResult。

        Raises:
            NotImplementedError: 子类未实现。
        """
        raise NotImplementedError

    def _mock_synthesize(self, text: str) -> TTSResult:
        """Mock 降级合成（返回静音 PCM）。"""
        # 生成 1 秒静音作为 mock 输出
        pcm = b"\x00" * self.sample_rate * 2  # 16-bit, 1s
        return TTSResult(
            pcm=pcm,
            sample_rate=self.sample_rate,
            text=text,
            backend=f"{self.name}-mock",
            latency_ms=0.0,
            meta={"fallback": True},
        )


class ElevenLabsBackend(CloudTTSBackend):
    """ElevenLabs TTS 适配器。

    使用 ElevenLabs Text-to-Speech API。
    需要环境变量：ELEVENLABS_API_KEY

    文档: https://elevenlabs.io/docs/api-reference/text-to-speech
    """

    name = "elevenlabs"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        super().__init__(
            api_key_env=cfg.get("api_key_env", "ELEVENLABS_API_KEY"),
            base_url=cfg.get("base_url", "https://api.elevenlabs.io/v1"),
        )
        self._voice_id = cfg.get("voice_id", "21m00Tcm4TlvDq8ikXViFdi")
        self._model_id = cfg.get("model_id", "eleven_multilingual_v2")
        self._sample_rate = int(cfg.get("sample_rate", 24000))

    def _synthesize_cloud(self, text: str) -> TTSResult:
        """调用 ElevenLabs API 合成。"""
        url = f"{self._base_url}/text-to-speech/{self._voice_id}"
        payload = json.dumps({
            "text": text,
            "model_id": self._model_id,
            "output_format": "pcm_22050",
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Accept": "audio/pcm",
                "Content-Type": "application/json",
                "xi-api-key": self._api_key,
            },
            method="POST",
        )

        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=30) as resp:
            pcm_data = resp.read()
        latency = (time.monotonic() - start) * 1000

        return TTSResult(
            pcm=pcm_data,
            sample_rate=22050,
            text=text,
            backend=self.name,
            latency_ms=latency,
            meta={"chars": len(text)},
        )


class EdgeTTSBackend(CloudTTSBackend):
    """Edge-TTS 适配器（微软免费 TTS）。

    使用 Edge TTS Web 接口（需 edge-tts 包）。
    完全免费但需联网。
    """

    name = "edge-tts"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        # Edge TTS 无需 API Key，始终可用
        self._voice = cfg.get("voice", "zh-CN-XiaoxiaoNeural")
        self._rate = cfg.get("rate", "+0%")
        self._available = True

    def _synthesize_cloud(self, text: str) -> TTSResult:
        """调用 edge-tts 合成。

        edge-tts 输出为 MP3（非 WAV）—— 直接截断头当 PCM 会播放刺耳噪音。
        使用 soundfile（libsndfile）解码为 int16 PCM（@24kHz）。
        """
        try:
            import edge_tts  # type: ignore
        except ImportError:
            raise RuntimeError("edge-tts 未安装: pip install edge-tts")

        import asyncio
        import io

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        communicate = edge_tts.Communicate(text, self._voice)

        # 流式收集 MP3 音频块（edge-tts 7.x 默认输出 MP3）
        mp3_data = bytearray()

        async def _collect():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_data.extend(chunk["data"])

        loop.run_until_complete(_collect())

        if not mp3_data:
            raise RuntimeError("edge-tts 未返回音频数据")

        # 解码 MP3 → int16 PCM（soundfile 可选依赖；缺失时降级 mock 提示）
        try:
            import soundfile as sf  # type: ignore

            pcm_data, sample_rate = sf.read(io.BytesIO(bytes(mp3_data)), dtype="int16")
        except ImportError:
            raise RuntimeError("edge-tts 解码需要 soundfile: pip install soundfile")
        except Exception as e:
            raise RuntimeError(f"edge-tts 音频解码失败: {e}") from e

        return TTSResult(
            pcm=bytes(pcm_data.tobytes()),
            sample_rate=int(sample_rate),
            text=text,
            backend=self.name,
            latency_ms=0.0,
            meta={"voice": self._voice, "format": "mp3-decoded"},
        )


class CloudASRBackend(ASRBackend):
    """云端 ASR 适配器基类。

    子类需实现 _transcribe_cloud() 方法。
    """

    name = "cloud-asr-base"

    def __init__(self, api_key_env: str = "", base_url: str = "") -> None:
        self._api_key_env = api_key_env
        self._base_url = base_url
        self._api_key = os.environ.get(api_key_env, "")
        self._available = bool(self._api_key)

    @property
    def available(self) -> bool:
        return self._available

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> ASRResult:
        """识别语音（云端调用 + mock 降级）。"""
        if not self._available:
            return ASRResult(
                text="",
                backend=f"{self.name}-mock",
                confidence=0.0,
            )

        try:
            return self._transcribe_cloud(pcm, sample_rate)
        except Exception as e:
            log.error("云端 ASR 调用失败: %s，降级 mock", e)
            return ASRResult(
                text="",
                backend=f"{self.name}-mock",
                confidence=0.0,
            )

    def _transcribe_cloud(self, pcm: bytes, sample_rate: int) -> ASRResult:
        """云端识别实现（子类覆盖）。"""
        raise NotImplementedError


class DeepgramBackend(CloudASRBackend):
    """Deepgram ASR 适配器。

    使用 Deepgram Speech-to-Text API。
    需要环境变量：DEEPGRAM_API_KEY

    文档: https://developers.deepgram.com/reference/listen-file
    """

    name = "deepgram"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        super().__init__(
            api_key_env=cfg.get("api_key_env", "DEEPGRAM_API_KEY"),
            base_url=cfg.get("base_url", "https://api.deepgram.com/v1"),
        )
        self._language = cfg.get("language", "zh")
        self._model = cfg.get("model", "general")

    def _transcribe_cloud(self, pcm: bytes, sample_rate: int) -> ASRResult:
        """调用 Deepgram API 识别。"""
        url = f"{self._base_url}/listen?model={self._model}&language={self._language}"
        req = urllib.request.Request(
            url,
            data=pcm,
            headers={
                "Authorization": f"Token {self._api_key}",
                "Content-Type": f"audio/pcm;rate={sample_rate}",
            },
            method="POST",
        )

        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latency = (time.monotonic() - start) * 1000

        # 解析 Deepgram 响应
        channels = data.get("channels", [])
        if channels:
            alternatives = channels[0].get("alternatives", [])
            if alternatives:
                text = alternatives[0].get("transcript", "")
                confidence = alternatives[0].get("confidence", 0.0)
                return ASRResult(
                    text=text,
                    confidence=confidence,
                    language=self._language,
                    backend=self.name,
                )

        return ASRResult(
            text="",
            confidence=0.0,
            language=self._language,
            backend=self.name,
        )


def register_cloud_engines(registry) -> None:
    """注册所有云端引擎类型到 VoiceEngineRegistry。

    Args:
        registry: VoiceEngineRegistry 实例。
    """
    # TTS
    registry.register_tts("elevenlabs", ElevenLabsBackend)
    registry.register_tts("edge-tts", EdgeTTSBackend)

    # ASR
    registry.register_asr("deepgram", DeepgramBackend)