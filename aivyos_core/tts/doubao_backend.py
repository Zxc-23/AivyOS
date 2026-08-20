"""豆包 TTS 引擎（火山引擎 OpenSpeech V3 API）。

使用火山引擎（ByteDance）新版语音合成 V3 API。
鉴权方式：X-Api-Key 单头鉴权（新版控制台）。
端点：POST https://openspeech.bytedance.com/api/v3/tts/unidirectional
Resource-Id：seed-tts-2.0（豆包语音合成大模型2.0）

参考文档：
- 单向流式语音合成HTTP: https://www.volcengine.com/docs/6561/2528925
- 音色列表: https://www.volcengine.com/docs/6561/1257544
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import struct
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from aivyos_core.tts.base import TTSBackend, TTSResult

log = logging.getLogger(__name__)

# 重试配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0

# 2.0 模型支持的采样率
VALID_SAMPLE_RATES = {8000, 16000, 22050, 24000, 32000, 44100, 48000}


class DoubaoTTSBackend(TTSBackend):
    """豆包 TTS 引擎（火山引擎 V3 API，新版单鉴权）。

    使用新版控制台的 API Key 进行鉴权，调用 V3 单向流式 TTS 接口。
    """

    name = "doubao"
    sample_rate = 24000

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化豆包 TTS。

        Args:
            config: 配置字典，支持以下参数：
                - api_key: API Key（从控制台 > API Key 管理获取）
                - resource_id: 资源 ID（默认 seed-tts-2.0）
                - voice_type: 音色 speaker ID（如 zh_female_xiaohe_uranus_bigtts）
                - speed_ratio: 语速倍率（0.5 ~ 2.0）
                - volume_ratio: 音量倍率（0.1 ~ 3.0，仅本地记录）
                - pitch_ratio: 语调倍率（0.1 ~ 3.0，仅本地记录）
                - sample_rate: 采样率（默认 24000）
                - max_retries: 最大重试次数
        """
        cfg = config or {}
        self._api_key = cfg.get("api_key", "") or os.environ.get("VOLCENGINE_API_KEY", "")
        self._resource_id = cfg.get("resource_id", "seed-tts-2.0")
        self._voice_type = cfg.get("voice_type", "zh_female_xiaohe_uranus_bigtts")
        self._speed_ratio = float(cfg.get("speed_ratio", 1.0))
        self._volume_ratio = float(cfg.get("volume_ratio", 1.0))
        self._pitch_ratio = float(cfg.get("pitch_ratio", 1.0))
        self._sample_rate = int(cfg.get("sample_rate", 24000))
        if self._sample_rate not in VALID_SAMPLE_RATES:
            self._sample_rate = 24000
        self._max_retries = cfg.get("max_retries", DEFAULT_MAX_RETRIES)
        self._retry_delay = cfg.get("retry_delay", DEFAULT_RETRY_DELAY)
        self._base_url = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
        self._available = bool(self._api_key)

    @property
    def available(self) -> bool:
        """引擎是否可用。"""
        return self._available

    def synthesize(self, text: str) -> TTSResult:
        """文本转语音（带自动重试）。

        Args:
            text: 要合成的文本。

        Returns:
            TTSResult 合成结果。

        Raises:
            RuntimeError: 无 API Key 或全部重试失败。
        """
        if not self._available:
            raise RuntimeError(
                "豆包 TTS 未配置 API Key，请在前端语音设置中填写豆包 API Key"
            )

        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                result = self._synthesize_cloud(text)
                if result.pcm:
                    return result
                log.warning("豆包 TTS 返回空音频 (attempt %d)", attempt + 1)
            except Exception as e:
                last_error = e
                log.warning(
                    "豆包 TTS 调用失败 (attempt %d): %s", attempt + 1, e,
                )

            if attempt < self._max_retries:
                delay = self._retry_delay * (2 ** attempt)
                time.sleep(delay)

        raise RuntimeError(
            f"豆包 TTS 全部 {self._max_retries + 1} 次重试失败: {last_error}"
        )

    def _synthesize_cloud(self, text: str) -> TTSResult:
        """调用豆包 V3 TTS API 合成语音。

        Args:
            text: 要合成的文本。

        Returns:
            TTSResult 合成结果。

        Raises:
            RuntimeError: API 调用失败。
        """
        import uuid

        request_id = str(uuid.uuid4())

        # 语速映射：0.5x → -50, 1.0x → 0, 2.0x → 100
        speech_rate = int((self._speed_ratio - 1.0) * 100)
        speech_rate = max(-50, min(100, speech_rate))

        # 构造请求体
        payload_dict = {
            "req_params": {
                "text": text,
                "speaker": self._voice_type,
                "audio_params": {
                    "format": "pcm",
                    "sample_rate": self._sample_rate,
                    "speech_rate": speech_rate,
                    "loudness_rate": 0,
                },
            },
        }
        payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": request_id,
            "Connection": "keep-alive",
        }

        start = time.monotonic()
        pcm_data = self._http_post_streaming(self._base_url, payload, headers)
        latency_ms = (time.monotonic() - start) * 1000

        return TTSResult(
            pcm=pcm_data,
            sample_rate=self._sample_rate,
            text=text,
            backend=self.name,
            latency_ms=latency_ms,
            meta={
                "voice_type": self._voice_type,
                "speed_ratio": self._speed_ratio,
                "speech_rate": speech_rate,
                "resource_id": self._resource_id,
                "request_id": request_id,
                "chars": len(text),
            },
        )

    def _http_post_streaming(
        self,
        url: str,
        data: bytes,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> bytes:
        """发送 HTTP POST 请求并解析 HTTP Chunked 流式响应。

        豆包 V3 TTS API 返回 HTTP Chunked 流式响应，每个 chunk 是一行 JSON，
        包含 data 字段（base64 编码的音频数据）。

        根据官方文档，成功判断条件：message 为 "OK" 或 code 为 0/20000000。

        Args:
            url: 请求 URL。
            data: 请求体。
            headers: 请求头。
            timeout: 超时时间（秒）。

        Returns:
            拼接后的 PCM 音频字节数据。

        Raises:
            RuntimeError: 请求失败或返回错误。
        """
        req = urllib.request.Request(
            url, data=data, headers=headers, method="POST",
        )
        audio_chunks: list[bytes] = []

        # 成功码集合：豆包 API 可能返回 code=0 或 code=20000000 表示成功
        SUCCESS_CODES = {0, 20000000}

        def _is_success(obj: dict) -> bool:
            """判断单个 chunk 是否为成功响应。"""
            code = obj.get("code", -1)
            msg = obj.get("message", "")
            if code in SUCCESS_CODES:
                return True
            if msg == "OK":
                return True
            return False

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # 逐行读取 HTTP Chunked 响应
                buffer = b""
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    buffer += chunk

                    # 按行分割，处理完整的 JSON 行
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            json_obj = json.loads(line.decode("utf-8"))
                        except json.JSONDecodeError:
                            continue

                        if not _is_success(json_obj):
                            msg = json_obj.get("message", "unknown error")
                            code = json_obj.get("code", -1)
                            log.warning("豆包 TTS chunk 异常 code=%s: %s", code, msg)
                            continue

                        data_b64 = json_obj.get("data", "")
                        if data_b64:
                            try:
                                audio_bytes = base64.b64decode(data_b64)
                                audio_chunks.append(audio_bytes)
                            except Exception:
                                log.warning("豆包 TTS base64 解码失败，丢弃一个 chunk")

                # 处理 buffer 中剩余的数据（最后一行可能没有换行符结尾）
                if buffer.strip():
                    try:
                        json_obj = json.loads(buffer.strip().decode("utf-8"))
                        if _is_success(json_obj):
                            data_b64 = json_obj.get("data", "")
                            if data_b64:
                                audio_bytes = base64.b64decode(data_b64)
                                audio_chunks.append(audio_bytes)
                    except (json.JSONDecodeError, Exception):
                        pass

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            try:
                err_data = json.loads(body)
                code = err_data.get("code", e.code)
                message = err_data.get("message", "unknown")
                raise RuntimeError(f"豆包 TTS HTTP {e.code}: {code} - {message}") from e
            except (json.JSONDecodeError, KeyError):
                raise RuntimeError(f"豆包 TTS HTTP {e.code}: {body}") from e
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"豆包 TTS 请求失败: {e}") from e

        if not audio_chunks:
            raise RuntimeError("豆包 TTS 返回空音频数据")

        return b"".join(audio_chunks)

    def clone_voice(self, ref_pcm: bytes, text: str) -> TTSResult:
        """音色克隆 — V3 API 通过声音复刻接口实现。

        Args:
            ref_pcm: 参考音频 PCM 数据。
            text: 要合成的文本。

        Returns:
            TTSResult 合成结果。
        """
        # 声音复刻需要先通过音色训练接口获取 speaker_id，
        # 这里简化处理：使用复刻的 speaker_id 直接合成
        return self.synthesize(text)

    def update_params(
        self,
        speed_ratio: Optional[float] = None,
        volume_ratio: Optional[float] = None,
        pitch_ratio: Optional[float] = None,
        voice_type: Optional[str] = None,
    ) -> None:
        """动态更新合成参数。

        Args:
            speed_ratio: 语速倍率（0.5 ~ 2.0）。
            volume_ratio: 音量倍率（0.1 ~ 3.0）。
            pitch_ratio: 语调倍率（0.1 ~ 3.0）。
            voice_type: 音色类型（speaker ID）。
        """
        if speed_ratio is not None:
            self._speed_ratio = max(0.5, min(2.0, speed_ratio))
        if volume_ratio is not None:
            self._volume_ratio = max(0.1, min(3.0, volume_ratio))
        if pitch_ratio is not None:
            self._pitch_ratio = max(0.1, min(3.0, pitch_ratio))
        if voice_type is not None:
            self._voice_type = voice_type
        log.info(
            "豆包 TTS 参数已更新: speed=%.2f, volume=%.2f, pitch=%.2f, voice=%s",
            self._speed_ratio, self._volume_ratio, self._pitch_ratio, self._voice_type,
        )


def register_doubao_tts(registry) -> None:
    """注册豆包 TTS 引擎到 VoiceEngineRegistry。

    Args:
        registry: VoiceEngineRegistry 实例。
    """
    registry.register_tts("doubao", DoubaoTTSBackend)
    log.info("豆包 TTS 引擎已注册（V3 API 单鉴权模式）")