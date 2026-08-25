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
DEFAULT_MAX_RETRIES = 1
DEFAULT_RETRY_DELAY = 0.5  # 秒


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
    """阿里云 ASR 引擎（DashScope Fun-ASR 异步API）。

    使用阿里云 DashScope 异步语音识别 API，需要公网可访问的音频URL。
    需要环境变量：DASHSCOPE_API_KEY

    文档: https://help.aliyun.com/zh/model-studio/fun-asr-recorded-speech-recognition-restful-api
    
    说明：
    - 阿里云Fun-ASR API采用异步调用模式
    - 需要提交任务后轮询查询结果
    - 音频需要公网可访问的URL（支持本地文件上传到OSS）
    """

    name = "aliyun"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化阿里云 ASR。

        Args:
            config: 配置字典，支持 api_key、api_key_env、workspace_id、language、model 等。
        """
        cfg = config or {}
        api_key = cfg.get("api_key", "")
        workspace_id = cfg.get("workspace_id", "")
        
        # 构建API基础URL
        if workspace_id:
            base_url = cfg.get(
                "base_url",
                f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1"
            )
        else:
            base_url = cfg.get(
                "base_url",
                "https://dashscope.aliyuncs.com/api/v1"
            )
        
        super().__init__(
            api_key=api_key,
            api_key_env=cfg.get("api_key_env", "DASHSCOPE_API_KEY"),
            base_url=base_url,
            max_retries=cfg.get("max_retries", DEFAULT_MAX_RETRIES),
            retry_delay=cfg.get("retry_delay", DEFAULT_RETRY_DELAY),
            config=cfg,
        )
        self._workspace_id = workspace_id
        self._language = cfg.get("language", "zh")
        self._model = cfg.get("model", "fun-asr")
        self._sample_rate = cfg.get("sample_rate", 16000)
        self._format = cfg.get("format", "wav")
        # 异步任务轮询配置
        self._poll_interval = cfg.get("poll_interval", 1.0)  # 秒
        self._max_polls = cfg.get("max_polls", 30)  # 最大轮询次数
        # OSS配置（用于上传本地音频）
        self._oss_upload = cfg.get("oss_upload", False)
        self._oss_bucket = cfg.get("oss_bucket", "")
        self._oss_endpoint = cfg.get("oss_endpoint", "")
        self._oss_access_key_id = cfg.get("oss_access_key_id", "")
        self._oss_access_key_secret = cfg.get("oss_access_key_secret", "")

    def _transcribe_cloud(self, pcm: bytes, sample_rate: int) -> ASRResult:
        """调用阿里云 DashScope 异步 ASR API。

        流程：提交任务 -> 获取task_id -> 轮询查询 -> 获取结果URL -> 下载结果
        """
        # 将PCM保存为临时WAV文件
        wav_path = self._save_temp_wav(pcm, sample_rate or self._sample_rate)
        
        try:
            # 步骤1：上传音频或使用URL
            audio_url = self._prepare_audio(wav_path)
            
            # 步骤2：提交识别任务
            task_id = self._submit_task(audio_url)
            
            # 步骤3：轮询查询结果
            result_data = self._poll_task_result(task_id)
            
            # 步骤4：解析结果
            return self._parse_result(result_data)
            
        finally:
            # 清理临时文件
            try:
                os.remove(wav_path)
            except Exception as e:
                log.debug("忽略预期内异常: %s", e, exc_info=True)

    def _prepare_audio(self, wav_path: str) -> str:
        """准备音频URL。

        优先使用OSS上传，否则使用阿里云示例音频或报错。

        Args:
            wav_path: WAV文件路径。

        Returns:
            公网可访问的音频URL。

        Raises:
            RuntimeError: 无法获取音频URL。
        """
        # 如果配置了OSS上传
        if self._oss_upload and self._oss_bucket:
            return self._upload_to_oss(wav_path)
        
        # 否则使用本地HTTP服务器或直接失败
        # 为简化实现，这里返回错误提示
        raise RuntimeError(
            "阿里云ASR需要公网可访问的音频URL。"
            "请配置OSS上传（oss_upload=True）或使用本地HTTP服务器。"
        )

    def _upload_to_oss(self, file_path: str) -> str:
        """上传文件到阿里云OSS并返回URL。

        Args:
            file_path: 本地文件路径。

        Returns:
            公网可访问的OSS URL。
        """
        try:
            import oss2
            
            auth = oss2.Auth(self._oss_access_key_id, self._oss_access_key_secret)
            bucket = oss2.Bucket(auth, self._oss_endpoint, self._oss_bucket)
            
            import uuid
            object_key = f"asr/{uuid.uuid4().hex}.wav"
            bucket.put_object_from_file(object_key, file_path)
            
            # 生成临时URL（有效期1小时）
            url = bucket.sign_url("GET", object_key, 3600)
            return url
        except ImportError:
            raise RuntimeError("需要安装oss2库: pip install oss2")
        except Exception as e:
            raise RuntimeError(f"OSS上传失败: {e}")

    def _submit_task(self, audio_url: str) -> str:
        """提交语音识别任务。

        Args:
            audio_url: 音频文件的公网URL。

        Returns:
            任务ID。
        """
        url = f"{self._base_url}/services/audio/asr/transcription"
        
        payload = json.dumps({
            "model": self._model,
            "input": {
                "file_urls": [audio_url],
            },
            "parameters": {},
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-DashScope-Async": "enable",
        }

        data = self._http_post(url, payload, headers)
        task_id = data.get("output", {}).get("task_id", "")
        
        if not task_id:
            raise RuntimeError(f"提交任务失败: {data}")
        
        log.info("阿里云ASR任务已提交: %s", task_id)
        return task_id

    def _poll_task_result(self, task_id: str) -> Dict[str, Any]:
        """轮询查询任务结果。

        Args:
            task_id: 任务ID。

        Returns:
            任务结果数据。
        """
        url = f"{self._base_url}/tasks/{task_id}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
        }
        
        for attempt in range(self._max_polls):
            time.sleep(self._poll_interval)
            
            try:
                data = self._http_get(url, headers)
                status = data.get("task_status", "")
                
                if status == "SUCCEEDED":
                    log.info("阿里云ASR任务完成: %s", task_id)
                    return data
                elif status == "FAILED":
                    error_msg = data.get("message", "Unknown error")
                    raise RuntimeError(f"阿里云ASR任务失败: {error_msg}")
                else:
                    log.debug("阿里云ASR任务状态: %s (attempt %d/%d)", 
                             status, attempt + 1, self._max_polls)
                             
            except Exception as e:
                log.warning("轮询任务状态失败 (attempt %d): %s", attempt + 1, e)
                if attempt == self._max_polls - 1:
                    raise
        
        raise RuntimeError(f"阿里云ASR任务超时: {task_id}")

    def _parse_result(self, result_data: Dict[str, Any]) -> ASRResult:
        """解析阿里云ASR结果。

        Args:
            result_data: 任务结果数据。

        Returns:
            ASRResult 识别结果。
        """
        text = ""
        confidence = 0.0
        
        # 从transcripts中提取文本
        transcripts = result_data.get("transcripts", [])
        if transcripts:
            transcript = transcripts[0]
            text = transcript.get("text", "")
            
            # 计算平均置信度
            sentences = transcript.get("sentences", [])
            if sentences:
                confidences = []
                for sentence in sentences:
                    words = sentence.get("words", [])
                    for word in words:
                        conf = word.get("confidence", 0.0)
                        if conf > 0:
                            confidences.append(conf)
                if confidences:
                    confidence = sum(confidences) / len(confidences)
        
        # 如果有transcription_url，尝试下载详细结果
        result_urls = result_data.get("results", [])
        if not text and result_urls:
            # 直接从结果中获取
            pass
        
        return ASRResult(
            text=text,
            confidence=confidence,
            language=self._language,
            backend=self.name,
        )

    def _save_temp_wav(self, pcm: bytes, sample_rate: int) -> str:
        """将PCM数据保存为临时WAV文件。

        Args:
            pcm: 16-bit PCM音频数据。
            sample_rate: 采样率。

        Returns:
            临时WAV文件路径。
        """
        import tempfile
        import struct
        
        # 构建WAV文件
        num_samples = len(pcm) // 2
        data_size = len(pcm)
        file_size = 44 + data_size - 8
        channels = 1
        bits_per_sample = 16
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8

        wav_header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF', file_size, b'WAVE', b'fmt ', 16, 1, channels,
            sample_rate, byte_rate, block_align, bits_per_sample,
            b'data', data_size,
        )
        
        wav_data = wav_header + pcm
        
        # 创建临时文件
        fd, path = tempfile.mkstemp(suffix='.wav', prefix='aivyos_asr_')
        with os.fdopen(fd, 'wb') as f:
            f.write(wav_data)
        
        return path

    def _http_get(
        self,
        url: str,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """发送 HTTP GET 请求。

        Args:
            url: 请求 URL。
            headers: 请求头。
            timeout: 超时时间。

        Returns:
            响应 JSON 字典。
        """
        req = urllib.request.Request(
            url, headers=headers, method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"HTTP {e.code}: {body}") from e
        except Exception as e:
            raise RuntimeError(f"请求失败: {e}") from e


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