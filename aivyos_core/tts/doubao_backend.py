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
DEFAULT_MAX_RETRIES = 1
DEFAULT_RETRY_DELAY = 0.5

# 2.0 模型支持的采样率
VALID_SAMPLE_RATES = {8000, 16000, 22050, 24000, 32000, 44100, 48000}


class DoubaoTTSBackend(TTSBackend):
    """豆包 TTS 引擎类（火山引擎 OpenSpeech V3 API）。

    功能：火山引擎新版 V3 单向流式 TTS，支持 API Key / Access Key / 环境变量三种鉴权；
          无 Key 时自动降级到 Mock 合成静音音频。
    参数：无（实例化通过 __init__ 传入 config）。
    返回：无。
    异常：无。
    """

    name = "doubao"
    sample_rate = 24000

    @staticmethod
    def availability_check(api_key=None, access_key=None, env_key: str = "VOLCENGINE_API_KEY") -> Dict[str, Any]:
        """静态可用性检查（无需实例化即可调用）。

        功能：按优先级检查 api_key → access_key → 环境变量，判断豆包 TTS 是否可调用云端接口。
        参数：
            api_key: 直接传入的 API Key（新版 X-Api-Key 单鉴权）。
            access_key: 别名参数，含义与 api_key 相同（兼容多命名调用方）。
            env_key: 回退读取的环境变量名，默认 VOLCENGINE_API_KEY。
        返回：
            Dict[str, Any]: 结构 {
                ok: bool,                  # 是否存在有效 Key
                reason: "has_key"|"missing_key",
                supports_access_key_param: True,
                sample_rate: 24000,
                default_voice: "zh_female_xiaohe_uranus_bigtts",
            }
        异常：无。
        """
        effective = (
            (api_key or "").strip()
            or (access_key or "").strip()
            or (os.environ.get(env_key or "VOLCENGINE_API_KEY") or "").strip()
        )
        return {
            "ok": bool(effective),
            "reason": "has_key" if effective else "missing_key",
            "supports_access_key_param": True,
            "sample_rate": 24000,
            "default_voice": "zh_female_xiaohe_uranus_bigtts",
        }

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化豆包 TTS 后端实例。

        功能：解析 config / 环境变量中的 Key，设置音色/语速/采样率等参数；无 Key 时标记为不可用。
        参数：
            config: 配置字典，支持：
                - api_key / access_key: API Key（二选一即可）
                - resource_id: 资源 ID，默认 seed-tts-2.0
                - voice_type: 音色 speaker ID，默认 zh_female_xiaohe_uranus_bigtts
                - speed_ratio: 语速倍率 0.5~2.0，默认 1.0
                - volume_ratio: 音量倍率 0.1~3.0，默认 1.0（仅本地记录）
                - pitch_ratio: 语调倍率 0.1~3.0，默认 1.0（仅本地记录）
                - sample_rate: 采样率，默认 24000
                - max_retries: 最大重试次数，默认 1
        返回：无。
        异常：无。
        """
        cfg = config or {}
        # 支持多种API Key参数名：api_key或access_key
        self._api_key = (
            cfg.get("api_key", "")
            or cfg.get("access_key", "")
            or os.environ.get("VOLCENGINE_API_KEY", "")
        )
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
        """当前实例的可用状态（是否有有效 API Key）。

        功能：只读属性，反映 __init__ 时解析出的 Key 是否有效。
        参数：无。
        返回：
            bool: True=存在有效 Key，可走云端合成；False=降级到 Mock 静音合成。
        异常：无。
        """
        return self._available

    def synthesize(self, text: str) -> TTSResult:
        """文本转语音（带指数退避重试）。

        功能：无 Key → Mock 静音；有 Key → 云端 V3 API，失败自动重试 max_retries+1 次。
        参数：
            text: 要合成的纯文本（中英文混合均可）。
        返回：
            TTSResult: 含 pcm 字节、采样率、后端名、延迟、meta 信息的结果对象。
        异常：
            RuntimeError: 全部重试次数耗尽后仍失败时抛出，附带最后一次异常信息。
        """
        if not self._available:
            # Mock 降级：生成1秒静音PCM数据
            log.info("豆包 TTS 无 API Key，降级到 Mock 模式")
            return self._mock_synthesize(text)

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

    def _mock_synthesize(self, text: str) -> TTSResult:
        """Mock 合成：生成1秒静音PCM数据用于测试。

        Args:
            text: 要合成的文本（仅用于日志记录）。

        Returns:
            TTSResult 包含1秒静音PCM数据。
        """
        duration_s = 1.0
        num_samples = int(self._sample_rate * duration_s)
        # 生成静音数据（全0）
        pcm_data = b"\x00" * (num_samples * 2)  # 16-bit PCM
        
        return TTSResult(
            pcm=pcm_data,
            sample_rate=self._sample_rate,
            text=text,
            backend="doubao-mock",
            latency_ms=0.0,
            meta={
                "mode": "mock",
                "reason": "no_api_key",
                "chars": len(text),
            },
        )

    def clone_voice(self, ref_pcm: bytes, text: str) -> TTSResult:
        """音色克隆（简化版，当前回退到普通 synthesize）。

        功能：预留接口，完整实现需先通过音色训练接口获取 speaker_id 再合成。
        参数：
            ref_pcm: 参考音频 16-bit PCM 字节（用于音色复刻训练）。
            text: 要合成的目标文本。
        返回：
            TTSResult: 当前版本与 synthesize 返回结构一致。
        异常：无。
        """
        return self.synthesize(text)

    def update_params(
        self,
        speed_ratio: Optional[float] = None,
        volume_ratio: Optional[float] = None,
        pitch_ratio: Optional[float] = None,
        voice_type: Optional[str] = None,
    ) -> None:
        """运行时动态更新合成参数（无需重建实例）。

        功能：按字段覆盖语速/音量/语调/音色，并做合法范围裁剪。
        参数：
            speed_ratio: 语速倍率 0.5~2.0，None 表示不修改。
            volume_ratio: 音量倍率 0.1~3.0，None 表示不修改。
            pitch_ratio: 语调倍率 0.1~3.0，None 表示不修改。
            voice_type: 音色 speaker ID 字符串，None 表示不修改。
        返回：无。
        异常：无。
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
    """将豆包 TTS 后端注册到引擎注册表。

    功能：以 name="doubao" 为键，将 DoubaoTTSBackend 类注册到全局 TTS 引擎注册表。
    参数：
        registry: 具备 register_tts(name, cls) 方法的 VoiceEngineRegistry 实例。
    返回：无。
    异常：无（注册表内部抛错除外）。
    """
    registry.register_tts("doubao", DoubaoTTSBackend)
    log.info("豆包 TTS 引擎已注册（V3 API 单鉴权模式）")