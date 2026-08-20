"""LLM 提供商适配器集合 — 11+ 主流提供商的统一接口实现。

设计原则：
    1. **兼容端点共享基类**：Ollama / vLLM / DeepSeek / SiliconFlow / Qwen 等
       OpenAI 兼容端点均继承 OpenAICompatBackend，仅覆盖端点 URL、认证方式、能力标签。
    2. **原生 API 独立实现**：Anthropic / Google / Bedrock 等非兼容端点各自实现。
    3. **能力声明驱动**：每个适配器通过 capabilities 属性声明自身能力，
       路由层据此做能力匹配决策。
    4. **零强制第三方依赖**：网络请求使用标准库 urllib，httpx 作为可选增强。

提供商列表：
    本地部署：Ollama / vLLM
    云端兼容：DeepSeek / SiliconFlow / Qwen(DashScope) / Mistral
    云端原生：OpenAI / Anthropic / Google(Gemini) / Azure OpenAI / AWS Bedrock
    回退：MockLLM（零依赖）
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, AsyncIterator, Dict, List, Optional

from aivyos_core.llm.base import LLMBackend, LLMBackendError
from aivyos_core.models import (
    BackendCapability,
    BackendStatus,
    LLMRequest,
    LLMResponse,
    ProviderInfo,
)


# ============================================================================
# 通用 OpenAI 兼容基类
# ============================================================================


class OpenAICompatBackend(LLMBackend):
    """OpenAI 兼容端点基类 — 覆盖 complete() 和 health_check()。

    兼容的端点（Ollama / vLLM / DeepSeek / SiliconFlow / Qwen 等）
    仅需覆盖 base_url、默认模型、能力标签即可。

    使用标准库 urllib 实现，零第三方依赖。
    """

    provider = "openai-compat"

    def __init__(self, info: ProviderInfo) -> None:
        self._info = info
        self.base_url = (info.base_url or "http://127.0.0.1:11434/v1").rstrip("/")
        self.model = info.model
        self.api_key = self._resolve_api_key(info)
        self.timeout_s = info.config.get("timeout_s", 60.0)
        self.name = info.name  # 唯一标识符（如 "ollama-local"），与注册表 key 一致

    def _resolve_api_key(self, info: ProviderInfo) -> Optional[str]:
        """从环境变量或 config 中解析 API Key。"""
        if info.api_key_env:
            key = os.environ.get(info.api_key_env)
            if key:
                return key
        return info.config.get("api_key") or os.environ.get("AIVYOS_CLOUD_API_KEY")

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=False,
            json_schema=True,
            thinking=False,
            tool_use=True,
            structured_output=True,
            context_window=32768,
            max_output_tokens=4096,
            cost_per_1m_input=0.0,
            cost_per_1m_output=0.0,
            free_tier=True,
            setup_time_s=0.0,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """同步文本补全（兼容端点实现）。"""
        return await self._call(request)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        """流式文本补全（兼容端点实现，SSE 解析）。"""
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
        }
        headers = self._build_headers()
        start = time.perf_counter()
        collected_text = ""

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                for line in resp:
                    line_str = line.decode("utf-8").strip()
                    if not line_str or not line_str.startswith("data: "):
                        continue
                    data = line_str[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            collected_text += content
                            yield LLMResponse(
                                text=collected_text,
                                model=chunk.get("model", self.model),
                                latency_ms=(time.perf_counter() - start) * 1000,
                                usage=chunk.get("usage") or {},
                                raw=chunk,
                            )
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise LLMBackendError(
                f"HTTP {e.code} from {self.base_url}: {detail}",
                provider=self.provider,
                model=self.model,
            ) from e
        except Exception as e:
            raise LLMBackendError(
                f"无法连接 {self.base_url}: {e}",
                provider=self.provider,
                model=self.model,
            ) from e

    async def health_check(self) -> BackendStatus:
        """探测兼容端点的 /models 接口。"""
        url = f"{self.base_url}/models"
        start = time.perf_counter()
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=min(3.0, self.timeout_s)) as resp:
                latency_ms = (time.perf_counter() - start) * 1000
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("id", "") for m in data.get("data", [])]
                return BackendStatus(
                    provider=self.provider,
                    model=self.model,
                    status="ok",
                    latency_ms=latency_ms,
                    detail=f"可用模型: {models[:5]}" if models else "端点正常",
                )
        except urllib.error.HTTPError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return BackendStatus(
                provider=self.provider,
                model=self.model,
                status="degraded",
                latency_ms=latency_ms,
                detail=f"HTTP {e.code}",
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return BackendStatus(
                provider=self.provider,
                model=self.model,
                status="down",
                latency_ms=latency_ms,
                detail=str(e)[:200],
            )

    # ---- 内部 ----

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _call(self, request: LLMRequest) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        headers = self._build_headers()
        start = time.perf_counter()

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise LLMBackendError(
                f"HTTP {e.code} from {self.base_url}: {detail}",
                provider=self.provider,
                model=self.model,
            ) from e
        except Exception as e:
            raise LLMBackendError(
                f"无法连接 {self.base_url}: {e}",
                provider=self.provider,
                model=self.model,
            ) from e

        latency_ms = (time.perf_counter() - start) * 1000
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMBackendError(
                f"响应格式异常: {str(payload)[:300]}",
                provider=self.provider,
                model=self.model,
            ) from e

        return LLMResponse(
            text=text,
            model=payload.get("model", self.model),
            latency_ms=latency_ms,
            usage=payload.get("usage") or {},
            raw=payload,
        )


# ============================================================================
# 本地部署适配器
# ============================================================================


class OllamaBackend(OpenAICompatBackend):
    """Ollama 本地部署适配器。

    默认端点: http://127.0.0.1:11434/v1
    默认模型: qwen2.5:3b（8GB 显存推荐）
    """

    provider = "ollama"

    def __init__(self, info: ProviderInfo) -> None:
        if not info.base_url:
            info.base_url = "http://127.0.0.1:11434/v1"
        if not info.model:
            info.model = "qwen2.5:3b"
        super().__init__(info)

    @property
    def capabilities(self) -> BackendCapability:
        cap = super().capabilities
        cap.context_window = 32768
        cap.free_tier = True
        cap.setup_time_s = 5.0
        return cap


class VLLMBackend(OpenAICompatBackend):
    """vLLM 本地部署适配器。

    默认端点: http://127.0.0.1:8000/v1
    vLLM 支持高吞吐推理、动态批处理、PagedAttention。
    """

    provider = "vllm"

    def __init__(self, info: ProviderInfo) -> None:
        if not info.base_url:
            info.base_url = "http://127.0.0.1:8000/v1"
        if not info.model:
            info.model = "qwen2.5:3b"
        super().__init__(info)

    @property
    def capabilities(self) -> BackendCapability:
        cap = super().capabilities
        cap.context_window = 128000
        cap.free_tier = True
        cap.setup_time_s = 10.0
        return cap


# ============================================================================
# 云端兼容适配器（OpenAI 协议）
# ============================================================================


class DeepSeekBackend(OpenAICompatBackend):
    """DeepSeek 云端适配器。

    端点: https://api.deepseek.com/v1
    特色: 免费额度、代码能力强、支持思考链
    """

    provider = "deepseek"

    def __init__(self, info: ProviderInfo) -> None:
        if not info.base_url:
            info.base_url = "https://api.deepseek.com/v1"
        if not info.model:
            info.model = "deepseek-v4-flash"
        info.api_key_env = info.api_key_env or "DEEPSEEK_API_KEY"
        super().__init__(info)

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=False,
            json_schema=True,
            thinking=True,
            tool_use=True,
            structured_output=True,
            context_window=128000,
            max_output_tokens=4096,
            cost_per_1m_input=0.001,
            cost_per_1m_output=0.004,
            free_tier=True,
            setup_time_s=0.1,
        )


class SiliconFlowBackend(OpenAICompatBackend):
    """SiliconFlow 云端适配器（硅基流动）。

    端点: https://api.siliconflow.cn/v1
    特色: 聚合多家开源模型、低成本、支持视觉
    """

    provider = "siliconflow"

    def __init__(self, info: ProviderInfo) -> None:
        if not info.base_url:
            info.base_url = "https://api.siliconflow.cn/v1"
        if not info.model:
            info.model = "deepseek-v4-flash"
        info.api_key_env = info.api_key_env or "SILICONFLOW_API_KEY"
        super().__init__(info)

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=True,
            json_schema=True,
            thinking=False,
            tool_use=True,
            structured_output=True,
            context_window=128000,
            max_output_tokens=8192,
            cost_per_1m_input=0.002,
            cost_per_1m_output=0.004,
            free_tier=False,
            setup_time_s=0.1,
        )


class QwenBackend(OpenAICompatBackend):
    """阿里云 DashScope 适配器（通义系列）。

    端点: https://dashscope.aliyuncs.com/compatible-mode/v1
    特色: 中文优化、多模态、国内网络低延迟
    """

    provider = "qwen"

    def __init__(self, info: ProviderInfo) -> None:
        if not info.base_url:
            info.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        if not info.model:
            info.model = "qwen-plus"
        info.api_key_env = info.api_key_env or "DASHSCOPE_API_KEY"
        super().__init__(info)

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=True,
            json_schema=True,
            thinking=True,
            tool_use=True,
            structured_output=True,
            context_window=128000,
            max_output_tokens=8192,
            cost_per_1m_input=0.004,
            cost_per_1m_output=0.012,
            free_tier=False,
            setup_time_s=0.1,
        )


class MistralBackend(OpenAICompatBackend):
    """Mistral AI 云端适配器。

    端点: https://api.mistral.ai/v1
    特色: 开源模型、代码能力强、支持工具调用
    """

    provider = "mistral"

    def __init__(self, info: ProviderInfo) -> None:
        if not info.base_url:
            info.base_url = "https://api.mistral.ai/v1"
        if not info.model:
            info.model = "mistral-small-latest"
        info.api_key_env = info.api_key_env or "MISTRAL_API_KEY"
        super().__init__(info)

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=False,
            json_schema=True,
            thinking=False,
            tool_use=True,
            structured_output=True,
            context_window=32768,
            max_output_tokens=4096,
            cost_per_1m_input=0.001,
            cost_per_1m_output=0.003,
            free_tier=False,
            setup_time_s=0.1,
        )


# ============================================================================
# 云端原生适配器（非兼容端点）
# ============================================================================


class OpenAIBackend(LLMBackend):
    """OpenAI 原生适配器。

    端点: https://api.openai.com/v1
    支持原生 Responses API 和 Chat Completions。
    """

    provider = "openai"

    def __init__(self, info: ProviderInfo) -> None:
        self._info = info
        self.base_url = (info.base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = info.model or "gpt-4o-mini"
        self.api_key = self._resolve_api_key(info)
        self.timeout_s = info.config.get("timeout_s", 60.0)
        self.name = info.name

    def _resolve_api_key(self, info: ProviderInfo) -> Optional[str]:
        if info.api_key_env:
            key = os.environ.get(info.api_key_env)
            if key:
                return key
        return info.config.get("api_key") or os.environ.get("OPENAI_API_KEY")

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=True,
            json_schema=True,
            thinking=True,
            tool_use=True,
            structured_output=True,
            context_window=128000,
            max_output_tokens=16384,
            cost_per_1m_input=0.15,
            cost_per_1m_output=0.60,
            free_tier=False,
            setup_time_s=0.1,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        start = time.perf_counter()
        try:
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"),
                headers=headers, method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise LLMBackendError(
                f"HTTP {e.code}: {detail}", provider="openai", model=self.model,
            ) from e
        except Exception as e:
            raise LLMBackendError(
                f"无法连接 {self.base_url}: {e}", provider="openai", model=self.model,
            ) from e

        latency_ms = (time.perf_counter() - start) * 1000
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMBackendError(
                f"响应格式异常: {str(payload)[:300]}",
                provider="openai", model=self.model,
            ) from e

        return LLMResponse(
            text=text,
            model=payload.get("model", self.model),
            latency_ms=latency_ms,
            usage=payload.get("usage") or {},
            raw=payload,
        )

    async def health_check(self) -> BackendStatus:
        if not self.api_key:
            return BackendStatus(
                provider="openai", model=self.model,
                status="down", detail="缺少 API Key",
            )
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models", method="GET",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                latency_ms = 0.0
                return BackendStatus(
                    provider="openai", model=self.model,
                    status="ok", latency_ms=latency_ms,
                )
        except Exception as e:
            return BackendStatus(
                provider="openai", model=self.model,
                status="down", detail=str(e)[:200],
            )


class AnthropicBackend(LLMBackend):
    """Anthropic 原生适配器（Messages API）。

    端点: https://api.anthropic.com/v1
    使用 Claude Messages API（POST /messages）。
    """

    provider = "anthropic"

    def __init__(self, info: ProviderInfo) -> None:
        self._info = info
        self.base_url = (info.base_url or "https://api.anthropic.com/v1").rstrip("/")
        self.model = info.model or "claude-3-5-sonnet-latest"
        self.api_key = self._resolve_api_key(info)
        self.timeout_s = info.config.get("timeout_s", 60.0)
        self.name = info.name

    def _resolve_api_key(self, info: ProviderInfo) -> Optional[str]:
        if info.api_key_env:
            key = os.environ.get(info.api_key_env)
            if key:
                return key
        return info.config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=True,
            json_schema=True,
            thinking=True,
            tool_use=True,
            structured_output=True,
            context_window=200000,
            max_output_tokens=8192,
            cost_per_1m_input=0.003,
            cost_per_1m_output=0.015,
            free_tier=False,
            setup_time_s=0.1,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """将 ChatCompletion 格式转换为 Anthropic Messages API 格式。"""
        # 转换 messages 格式
        messages = []
        system_prompt = ""
        for msg in request.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content
            elif role in ("user", "assistant"):
                messages.append({"role": role, "content": content})

        body: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": min(request.max_tokens, 8192),
        }
        if system_prompt:
            body["system"] = system_prompt

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

        start = time.perf_counter()
        try:
            req = urllib.request.Request(
                f"{self.base_url}/messages",
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise LLMBackendError(
                f"HTTP {e.code}: {detail}", provider="anthropic", model=self.model,
            ) from e
        except Exception as e:
            raise LLMBackendError(
                f"无法连接 {self.base_url}: {e}", provider="anthropic", model=self.model,
            ) from e

        latency_ms = (time.perf_counter() - start) * 1000
        # 从 Anthropic 响应中提取文本
        text = ""
        for block in payload.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")

        usage = {
            "prompt_tokens": payload.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": payload.get("usage", {}).get("output_tokens", 0),
        }

        return LLMResponse(
            text=text,
            model=payload.get("model", self.model),
            latency_ms=latency_ms,
            usage=usage,
            raw=payload,
        )

    async def health_check(self) -> BackendStatus:
        if not self.api_key:
            return BackendStatus(
                provider="anthropic", model=self.model,
                status="down", detail="缺少 API Key",
            )
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models/{self.model}",
                method="GET",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return BackendStatus(
                    provider="anthropic", model=self.model, status="ok",
                )
        except Exception as e:
            return BackendStatus(
                provider="anthropic", model=self.model,
                status="down", detail=str(e)[:200],
            )


class GoogleAIBackend(LLMBackend):
    """Google Gemini 原生适配器。

    端点: https://generativelanguage.googleapis.com/v1beta
    使用 Gemini Pro API。
    """

    provider = "google"

    def __init__(self, info: ProviderInfo) -> None:
        self._info = info
        self.base_url = (info.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.model = info.model or "gemini-2.0-flash-exp"
        self.api_key = self._resolve_api_key(info)
        self.timeout_s = info.config.get("timeout_s", 60.0)
        self.name = info.name

    def _resolve_api_key(self, info: ProviderInfo) -> Optional[str]:
        if info.api_key_env:
            key = os.environ.get(info.api_key_env)
            if key:
                return key
        return info.config.get("api_key") or os.environ.get("GOOGLE_API_KEY")

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=True,
            json_schema=True,
            thinking=False,
            tool_use=True,
            structured_output=True,
            context_window=1048576,
            max_output_tokens=8192,
            cost_per_1m_input=0.00035,
            cost_per_1m_output=0.00105,
            free_tier=True,
            setup_time_s=0.1,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """转换为 Gemini generateContent API 格式。"""
        contents = []
        system_prompt = ""
        for msg in request.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content
            elif role == "user":
                contents.append({"role": "USER", "parts": [{"text": content}]})
            elif role == "assistant":
                contents.append({"role": "MODEL", "parts": [{"text": content}]})

        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        url = f"{self.base_url}/models/{self.model}:generateContent"
        if self.api_key:
            url += f"?key={self.api_key}"

        start = time.perf_counter()
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise LLMBackendError(
                f"HTTP {e.code}: {detail}", provider="google", model=self.model,
            ) from e
        except Exception as e:
            raise LLMBackendError(
                f"无法连接 {self.base_url}: {e}", provider="google", model=self.model,
            ) from e

        latency_ms = (time.perf_counter() - start) * 1000
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMBackendError(
                f"响应格式异常: {str(payload)[:300]}",
                provider="google", model=self.model,
            ) from e

        return LLMResponse(
            text=text,
            model=self.model,
            latency_ms=latency_ms,
            usage=payload.get("usageMetadata") or {},
            raw=payload,
        )

    async def health_check(self) -> BackendStatus:
        if not self.api_key:
            return BackendStatus(
                provider="google", model=self.model,
                status="down", detail="缺少 API Key",
            )
        try:
            url = f"{self.base_url}/models/{self.model}"
            if self.api_key:
                url += f"?key={self.api_key}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return BackendStatus(
                    provider="google", model=self.model, status="ok",
                )
        except Exception as e:
            return BackendStatus(
                provider="google", model=self.model,
                status="down", detail=str(e)[:200],
            )


class AzureOpenAIBackend(OpenAICompatBackend):
    """Azure OpenAI 适配器。

    端点格式: https://{resource}.openai.azure.com/openai/deployments/{deployment}
    使用 Azure API Key 认证。
    """

    provider = "azure-openai"

    def __init__(self, info: ProviderInfo) -> None:
        if not info.base_url:
            resource = info.config.get("resource", "aivyos")
            deployment = info.config.get("deployment", "gpt-4o")
            info.base_url = f"https://{resource}.openai.azure.com/openai/deployments/{deployment}"
        if not info.model:
            info.model = info.config.get("deployment", "gpt-4o")
        info.api_key_env = info.api_key_env or "AZURE_OPENAI_API_KEY"
        super().__init__(info)

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=True,
            json_schema=True,
            thinking=True,
            tool_use=True,
            structured_output=True,
            context_window=128000,
            max_output_tokens=16384,
            cost_per_1m_input=0.15,
            cost_per_1m_output=0.60,
            free_tier=False,
            setup_time_s=0.1,
        )


class BedrockBackend(LLMBackend):
    """AWS Bedrock 适配器（简化版）。

    完整实现需 boto3 SDK，此处提供基于 HTTP 的简化版本。
    生产环境建议通过 LiteLLM 或 boto3 接入。
    """

    provider = "bedrock"

    def __init__(self, info: ProviderInfo) -> None:
        self._info = info
        self.base_url = (info.base_url or "").rstrip("/")
        self.model = info.model or "anthropic.claude-3-5-sonnet-20241022-v2:0"
        self.api_key = self._resolve_api_key(info)
        self.timeout_s = info.config.get("timeout_s", 60.0)
        self.name = info.name

    def _resolve_api_key(self, info: ProviderInfo) -> Optional[str]:
        if info.api_key_env:
            key = os.environ.get(info.api_key_env)
            if key:
                return key
        return info.config.get("api_key")

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=True,
            json_schema=True,
            thinking=True,
            tool_use=True,
            structured_output=True,
            context_window=200000,
            max_output_tokens=8192,
            cost_per_1m_input=0.003,
            cost_per_1m_output=0.015,
            free_tier=False,
            setup_time_s=0.5,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Bedrock 调用 — 需配置 AWS 凭证和端点。"""
        if not self.base_url:
            raise LLMBackendError(
                "Bedrock 未配置 base_url，"
                "请配置 AWS 区域端点（如 https://bedrock-runtime.us-east-1.amazonaws.com）",
                provider="bedrock",
            )
        # Bedrock 实际调用需 boto3 + SigV4 签名，此处为占位实现
        raise LLMBackendError(
            "Bedrock 适配器需要 boto3 SDK 和 AWS 凭证，"
            "建议通过 LiteLLM 统一网关接入或配置 boto3。",
            provider="bedrock",
        )

    async def health_check(self) -> BackendStatus:
        return BackendStatus(
            provider="bedrock", model=self.model,
            status="unknown",
            detail="Bedrock 适配器需 boto3 初始化",
        )


# ============================================================================
# Mock 回退适配器
# ============================================================================


class MockBackend(LLMBackend):
    """Mock 回退后端 — 零依赖、规则化回复。

    对应 Phase 1 的 MockLLM，保证在任何环境下对话链路可运行。
    """

    provider = "mock"

    def __init__(self, info: ProviderInfo) -> None:
        self.model = info.model or "mock-echo"
        self.name = info.name

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=False,
            vision=False,
            json_schema=False,
            thinking=False,
            tool_use=False,
            structured_output=False,
            context_window=4096,
            max_output_tokens=2048,
            cost_per_1m_input=0.0,
            cost_per_1m_output=0.0,
            free_tier=True,
            setup_time_s=0.0,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        user_text = next(
            (m["content"] for m in reversed(request.messages) if m["role"] == "user"),
            "",
        )
        text = self._reply(user_text)
        latency_ms = (time.perf_counter() - start) * 1000
        return LLMResponse(
            text=text,
            model=self.model,
            latency_ms=latency_ms,
            usage={
                "prompt_tokens": self._est_tokens(request.messages),
                "completion_tokens": self._est_tokens(text),
            },
        )

    async def health_check(self) -> BackendStatus:
        return BackendStatus(
            provider="mock", model=self.model,
            status="ok", latency_ms=0.1, detail="Mock 后端始终可用",
        )

    # ---- 内部 ----

    @staticmethod
    def _est_tokens(text) -> int:
        if isinstance(text, list):
            return sum(len(m.get("content", "")) for m in text) // 2
        return len(text) // 2

    def _reply(self, user_text: str) -> str:
        t = user_text.strip().lower()
        if not t:
            return "（mock）请说点什么，例如：你好 / 今天天气 / 写一个计算器。"
        if any(k in t for k in ("你好", "hi", "hello", "在吗")):
            return "（mock）您好，我是 Aivy，您的私人助理。当前处于 mock 模式。"
        if any(k in t for k in ("天气", "气温", "下雨")):
            return "（mock）天气查询需启用 search 工具或接入天气 API（Phase 2）。"
        if any(k in t for k in ("代码", "写个", "实现", "函数", "脚本", "计算器")):
            return "（mock）代码生成需启用 Cline SDK（Phase 2）。当前 mock 模式无法生成真实代码。"
        if any(k in t for k in ("记住", "我叫", "我喜欢", "别忘了")):
            return "（mock）已调用记忆接口，信息将被保存。"
        if any(k in t for k in ("你是谁", "介绍")):
            return "（mock）我是 AivyOS —— 本地优先的私人 AI 伴侣系统。"
        return f"（mock）收到：{user_text.strip()[:80]}。配置 AIVYOS_LLM_MODE=local 后切换到真实模型。"


# ============================================================================
# 适配器注册工厂
# ============================================================================


class DoubaoBackend(OpenAICompatBackend):
    """豆包（火山引擎）云端适配器。

    端点: https://ark.cn-beijing.volces.com/api/v3
    特色: 国内网络低延迟、支持多模态、中文优化
    """

    provider = "doubao"

    def __init__(self, info: ProviderInfo) -> None:
        if not info.base_url:
            info.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        if not info.model:
            info.model = "doubao-pro-32k"
        info.api_key_env = info.api_key_env or "VOLCENGINE_API_KEY"
        super().__init__(info)

    @property
    def capabilities(self) -> BackendCapability:
        return BackendCapability(
            streaming=True,
            vision=True,
            json_schema=True,
            thinking=False,
            tool_use=True,
            structured_output=True,
            context_window=32768,
            max_output_tokens=4096,
            cost_per_1m_input=0.0008,
            cost_per_1m_output=0.002,
            free_tier=False,
            setup_time_s=0.1,
        )


def register_all_providers(registry) -> None:
    """将所有提供商适配器注册到 ProviderRegistry。

    Args:
        registry: ProviderRegistry 实例。
    """
    registry.register("ollama", OllamaBackend)
    registry.register("vllm", VLLMBackend)
    registry.register("deepseek", DeepSeekBackend)
    registry.register("siliconflow", SiliconFlowBackend)
    registry.register("qwen", QwenBackend)
    registry.register("mistral", MistralBackend)
    registry.register("openai", OpenAIBackend)
    registry.register("anthropic", AnthropicBackend)
    registry.register("google", GoogleAIBackend)
    registry.register("azure-openai", AzureOpenAIBackend)
    registry.register("bedrock", BedrockBackend)
    registry.register("doubao", DoubaoBackend)
    registry.register("mock", MockBackend)


def create_provider_info(
    provider: str,
    model: str = "",
    base_url: str = "",
    api_key_env: str = "",
    priority: int = 50,
    **kwargs: Any,
) -> ProviderInfo:
    """便捷工厂函数 — 创建 ProviderInfo。

    Args:
        provider: 提供商类型标识。
        model: 默认模型名。
        base_url: API 端点。
        api_key_env: API Key 环境变量名。
        priority: 路由优先级。
        **kwargs: 额外配置（timeout_s / breaker_threshold 等）。

    Returns:
        ProviderInfo 实例。
    """
    return ProviderInfo(
        name=kwargs.pop("name", f"{provider}-{model or 'default'}"),
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        priority=priority,
        config=kwargs,
    )