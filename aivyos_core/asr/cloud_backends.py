"""云端 ASR 引擎实现：阿里云、腾讯云、豆包（火山引擎）。

设计原则：
    - 适配器模式：每个云端引擎继承 CloudASRBackend 基类
    - 统一接口：transcribe(pcm, sample_rate) → ASRResult
    - 重试机制：自动重试（默认 3 次，指数退避）
    - Mock 降级：无 API Key 时自动降级为 Mock
    - 零强制依赖：使用标准库 urllib，无需额外 SDK

对应需求：云端语音识别(ASR)模块集成。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from aivyos_core.asr.base import ASRBackend, ASRResult

log = logging.getLogger(__name__)

# 重试配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # 秒


class CloudASRBase(ASRBackend):
    """云端 ASR 适配器基类。

    提供：API Key 读取、HTTP 请求、自动重试、Mock 降级。
    子类需实现 _build_request() 和 _parse_response()。
    """

    name = "cloud-asr-base"

    def __init__(
        self,
        api_key: str = "",
        api_key_env: str = "",
        base_url: str = "",
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化云端 ASR。

        Args:
            api_key: API Key（直接传入优先）。
            api_key_env: API Key 环境变量名。
            base_url: API 基础 URL。
            max_retries: 最大重试次数。
            retry_delay: 重试初始延迟（秒，指数退避）。
            config: 额外配置。
        """
        self._api_key = api_key or os.environ.get(api_key_env, "")
        self._api_key_env = api_key_env
        self._base_url = base_url
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._config = config or {}
        self._available = bool(self._api_key)

    @property
    def available(self) -> bool:
        """引擎是否可用（有 API Key）。"""
        return self._available

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> ASRResult:
        """识别语音（云端调用 + 自动重试 + Mock 降级）。

        Args:
            pcm: 16-bit PCM 音频数据。
            sample_rate: 采样率。

        Returns:
            ASRResult 识别结果。
        """
        if not self._available:
            log.warning("%s 无 API Key，降级 Mock", self.name)
            return self._mock_result()

        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                result = self._transcribe_cloud(pcm, sample_rate)
                if result.text:
                    return result
                log.warning("%s 返回空文本 (attempt %d)", self.name, attempt + 1)
            except Exception as e:
                last_error = e
                log.warning(
                    "%s ASR 调用失败 (attempt %d): %s",
                    self.name, attempt + 1, e,
                )

            if attempt < self._max_retries:
                delay = self._retry_delay * (2 ** attempt)
                time.sleep(delay)

        # 全部重试失败
        log.error("%s ASR 全部 %d 次重试失败: %s", self.name, self._max_retries + 1, last_error)
        return self._mock_result()

    def _transcribe_cloud(self, pcm: bytes, sample_rate: int) -> ASRResult:
        """云端识别实现（子类覆盖）。

        Args:
            pcm: PCM 数据。
            sample_rate: 采样率。

        Returns:
            ASRResult。

        Raises:
            NotImplementedError: 子类未实现。
        """
        raise NotImplementedError

    def _mock_result(self) -> ASRResult:
        """返回 Mock 结果（空文本 + 低置信度）。"""
        return ASRResult(
            text="",
            confidence=0.0,
            backend=f"{self.name}-mock",
        )

    def _http_post(
        self,
        url: str,
        data: bytes,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """发送 HTTP POST 请求。

        Args:
            url: 请求 URL。
            data: 请求体。
            headers: 请求头。
            timeout: 超时时间。

        Returns:
            响应 JSON 字典。

        Raises:
            urllib.error.HTTPError: HTTP 错误。
            RuntimeError: 连接失败。
        """
        req = urllib.request.Request(
            url, data=data, headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"HTTP {e.code}: {body}") from e
        except Exception as e:
            raise RuntimeError(f"请求失败: {e}") from e


class AliyunASRBackend(CloudASRBase):
    """阿里云 ASR 引擎（DashScope Paraformer）。

    使用阿里云 DashScope 语音识别 API。
    需要环境变量：DASHSCOPE_API_KEY

    文档: https://help.aliyun.com/zh/model-studio/developer-reference/speech-recognition
    """

    name = "aliyun"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化阿里云 ASR。

        Args:
            config: 配置字典，支持 api_key、api_key_env、language、model 等。
        """
        cfg = config or {}
        api_key = cfg.get("api_key", "")
        super().__init__(
            api_key=api_key,
            api_key_env=cfg.get("api_key_env", "DASHSCOPE_API_KEY"),
            base_url=cfg.get("base_url", "https://dashscope.aliyuncs.com/api/v1/asr"),
            max_retries=cfg.get("max_retries", DEFAULT_MAX_RETRIES),
            retry_delay=cfg.get("retry_delay", DEFAULT_RETRY_DELAY),
            config=cfg,
        )
        self._language = cfg.get("language", "zh")
        self._model = cfg.get("model", "paraformer-v2")
        self._sample_rate = cfg.get("sample_rate", 16000)
        self._format = cfg.get("format", "pcm")  # pcm / wav / mp3

    def _transcribe_cloud(self, pcm: bytes, sample_rate: int) -> ASRResult:
        """调用阿里云 DashScope ASR API。"""
        url = f"{self._base_url}?model={self._model}&language={self._language}"

        # 将 PCM 编码为 base64
        audio_b64 = base64.b64encode(pcm).decode("utf-8")
        payload = json.dumps({
            "audio": audio_b64,
            "format": self._format,
            "sample_rate": sample_rate or self._sample_rate,
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        start = time.monotonic()
        data = self._http_post(url, payload, headers)
        latency_ms = (time.monotonic() - start) * 1000

        # 解析阿里云响应
        output = data.get("output", {})
        results = output.get("results", [])
        text = ""
        confidence = 0.0
        if results:
            sentence = results[0].get("sentence", {})
            text = sentence.get("text", "")
            confidence = sentence.get("confidence", 0.0)

        return ASRResult(
            text=text,
            confidence=confidence,
            language=self._language,
            backend=self.name,
        )


class TencentASRBackend(CloudASRBase):
    """腾讯云 ASR 引擎。

    使用腾讯云 ASR 一句话识别 API（简化版，无 SDK 依赖）。
    需要环境变量：TENCENT_SECRET_ID、TENCENT_SECRET_KEY

    文档: https://cloud.tencent.com/document/product/1093/37994
    """

    name = "tencent"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化腾讯云 ASR。

        Args:
            config: 配置字典，支持 secret_id、secret_key、api_key_env 等。
        """
        cfg = config or {}
        self._secret_id = cfg.get("secret_id", "") or os.environ.get("TENCENT_SECRET_ID", "")
        self._secret_key = cfg.get("secret_key", "") or os.environ.get("TENCENT_SECRET_KEY", "")

        api_key = cfg.get("api_key", "") or self._secret_key
        super().__init__(
            api_key=api_key,
            api_key_env="TENCENT_SECRET_KEY",
            base_url=cfg.get("base_url", "https://asr.tencentcloudapi.com"),
            max_retries=cfg.get("max_retries", DEFAULT_MAX_RETRIES),
            retry_delay=cfg.get("retry_delay", DEFAULT_RETRY_DELAY),
            config=cfg,
        )
        # 腾讯云需要 SecretId + SecretKey 签名认证
        self._secret_id = self._secret_id or os.environ.get("TENCENT_SECRET_ID", "")
        self._secret_key = self._secret_key or os.environ.get("TENCENT_SECRET_KEY", "")
        self._available = bool(self._secret_id and self._secret_key)
        self._language = cfg.get("language", "16k_zh")
        self._project_id = cfg.get("project_id", "")

    def _sign(self, timestamp: int, payload: str) -> str:
        """生成 TC3-HMAC-SHA256 签名。

        Args:
            timestamp: 当前时间戳。
            payload: 请求体字符串。

        Returns:
            Authorization 头值。
        """
        # 简化版签名实现（实际腾讯云 SDK 更复杂）
        # 此处使用 Basic 签名简化调用
        import hmac as _hmac
        import hashlib as _hashlib

        date = time.strftime("%Y-%m-%d", time.gmtime(timestamp))
        service = "asr"
        algorithm = "TC3-HMAC-SHA256"

        # Step 1: 规范请求串
        http_request_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        canonical_headers = (
            f"content-type:application/json\n"
            f"host:asr.tencentcloudapi.com\n"
            f"x-tc-action:sentencerecognition\n"
        )
        signed_headers = "content-type;host;x-tc-action"
        hashed_payload = _hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = (
            f"{http_request_method}\n{canonical_uri}\n{canonical_querystring}\n"
            f"{canonical_headers}\n{signed_headers}\n{hashed_payload}"
        )

        # Step 2: 待签字符串
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_canonical_request = _hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = (
            f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"
        )

        # Step 3: 计算签名
        secret_date = _hmac.new(
            f"TC3{self._secret_key}".encode("utf-8"), date.encode("utf-8"), _hashlib.sha256
        ).digest()
        secret_service = _hmac.new(secret_date, service.encode("utf-8"), _hashlib.sha256).digest()
        secret_signing = _hmac.new(secret_service, b"tc3_request", _hashlib.sha256).digest()
        signature = _hmac.new(secret_signing, string_to_sign.encode("utf-8"), _hashlib.sha256).hexdigest()

        # Step 4: 拼接 Authorization
        authorization = (
            f"{algorithm} Credential={self._secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return authorization

    def _transcribe_cloud(self, pcm: bytes, sample_rate: int) -> ASRResult:
        """调用腾讯云 ASR 一句话识别 API。"""
        timestamp = int(time.time())
        audio_b64 = base64.b64encode(pcm).decode("utf-8")

        payload_dict = {
            "Action": "SentenceRecognition",
            "Version": "2019-06-14",
            "Region": "ap-guangzhou",
            "Timestamp": timestamp,
            "Nonce": int(time.time() * 1000) % 2**31,
            "ProjectId": self._project_id,
            "EngSerViceType": self._language,
            "SourceType": 1,
            "VoiceFormat": "wav",
            "UsrAudioKey": "",
            "Data": audio_b64,
            "DataLen": len(pcm),
        }
        payload = json.dumps(payload_dict)

        authorization = self._sign(timestamp, payload)

        headers = {
            "Content-Type": "application/json",
            "Host": "asr.tencentcloudapi.com",
            "X-TC-Action": "SentenceRecognition",
            "X-TC-Version": "2019-06-14",
            "X-TC-Timestamp": str(timestamp),
            "Authorization": authorization,
        }

        start = time.monotonic()
        data = self._http_post(
            f"{self._base_url}/",
            payload.encode("utf-8"),
            headers,
        )
        latency_ms = (time.monotonic() - start) * 1000

        # 解析腾讯云响应
        response = data.get("Response", {})
        error = response.get("Error", {})
        if error:
            raise RuntimeError(f"腾讯云 ASR 错误: {error.get('Code')} - {error.get('Message')}")

        result = response.get("Result", "")
        return ASRResult(
            text=result,
            confidence=1.0 if result else 0.0,
            language="zh",
            backend=self.name,
        )


class DoubaoASRBackend(CloudASRBase):
    """豆包 ASR 引擎（火山引擎）。

    使用火山引擎（ByteDance）ASR API。
    需要环境变量：VOLCENGINE_ACCESS_KEY、VOLCENGINE_SECRET_KEY

    文档: https://www.volcengine.com/docs/6561/79823
    """

    name = "doubao"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化豆包 ASR。

        Args:
            config: 配置字典，支持 access_key、secret_key、appid、cluster 等。
        """
        cfg = config or {}
        self._access_key = cfg.get("access_key", "") or os.environ.get("VOLCENGINE_ACCESS_KEY", "")
        self._secret_key = cfg.get("secret_key", "") or os.environ.get("VOLCENGINE_SECRET_KEY", "")

        api_key = cfg.get("api_key", "") or self._access_key
        super().__init__(
            api_key=api_key,
            api_key_env="VOLCENGINE_ACCESS_KEY",
            base_url=cfg.get("base_url", "https://openspeech.bytedance.com/api/v1/asr"),
            max_retries=cfg.get("max_retries", DEFAULT_MAX_RETRIES),
            retry_delay=cfg.get("retry_delay", DEFAULT_RETRY_DELAY),
            config=cfg,
        )
        self._appid = cfg.get("appid", "") or os.environ.get("VOLCENGINE_APPID", "")
        self._cluster = cfg.get("cluster", "volcengine_streaming_common")
        self._token = cfg.get("token", "") or os.environ.get("VOLCENGINE_TOKEN", "")
        self._language = cfg.get("language", "zh")

        # 豆包需要 appid + token 认证
        self._available = bool(self._access_key and self._secret_key)

    def _gen_signature(self, timestamp: int) -> str:
        """生成火山引擎 API 签名。

        Args:
            timestamp: 时间戳。

        Returns:
            签名字符串。
        """
        sig = hashlib.sha256(
            f"{self._access_key}{timestamp}{self._secret_key}".encode("utf-8")
        ).hexdigest()
        return sig

    def _transcribe_cloud(self, pcm: bytes, sample_rate: int) -> ASRResult:
        """调用豆包 ASR API。"""
        timestamp = int(time.time())
        audio_b64 = base64.b64encode(pcm).decode("utf-8")

        payload = json.dumps({
            "app": {
                "appid": self._appid,
                "token": self._token or self._access_key,
                "cluster": self._cluster,
            },
            "user": {
                "uid": "aivyos_user",
            },
            "request": {
                "reqid": f"req_{int(time.time()*1000)}",
                "nbest": 1,
                "show_utterances": False,
            },
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": sample_rate,
                "bits": 16,
                "channel": 1,
                "data": audio_b64,
            },
        }).encode("utf-8")

        signature = self._gen_signature(timestamp)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer;{self._access_key}",
            "X-Api-Timestamp": str(timestamp),
            "X-Api-Signature": signature,
        }

        start = time.monotonic()
        data = self._http_post(self._base_url, payload, headers)
        latency_ms = (time.monotonic() - start) * 1000

        # 解析豆包响应
        code = data.get("code", 0)
        if code != 0:
            raise RuntimeError(f"豆包 ASR 错误: code={code}, message={data.get('message', '')}")

        result = data.get("data", {})
        text = result.get("text", "")
        confidence = result.get("confidence", 0.0)

        return ASRResult(
            text=text,
            confidence=confidence,
            language=self._language,
            backend=self.name,
        )


def register_cloud_asr_engines(registry) -> None:
    """注册所有云端 ASR 引擎到 VoiceEngineRegistry。

    Args:
        registry: VoiceEngineRegistry 实例。
    """
    registry.register_asr("aliyun", AliyunASRBackend)
    registry.register_asr("tencent", TencentASRBackend)
    registry.register_asr("doubao", DoubaoASRBackend)
    log.info("云端 ASR 引擎已注册: aliyun, tencent, doubao")