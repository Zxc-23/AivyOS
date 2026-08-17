"""OpenAI 兼容客户端（标准库实现，零第三方依赖）。

兼容端点：Ollama `/v1`、vLLM `/v1`、OpenAI/兼容云服务 `/v1`。
Week 1 为同步非流式；流式（SSE）留待 Week 2 与语音链路一起接入。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from aivyos_core.llm.base import LLMBackend, LLMBackendError
from aivyos_core.models import LLMRequest, LLMResponse


class OpenAICompatLLM(LLMBackend):
    """OpenAI 兼容 Chat Completions 客户端（urllib 实现）。"""

    name = "openai-compat"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s

    async def complete(self, request: LLMRequest) -> LLMResponse:
        # Week 1：同步调用（异步包装）；流式支持待 Week 2
        return await self._call(request)

    async def _call(self, request: LLMRequest) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.stream:
            body["stream"] = True
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        start = time.perf_counter()
        try:
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise LLMBackendError(f"HTTP {e.code} from {self.base_url}: {detail}") from e
        except Exception as e:  # URLError / timeout / connection refused
            raise LLMBackendError(f"无法连接 {self.base_url}: {e}") from e

        latency_ms = (time.perf_counter() - start) * 1000
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMBackendError(f"响应格式异常: {str(payload)[:300]}") from e

        return LLMResponse(
            text=text,
            model=payload.get("model", self.model),
            latency_ms=latency_ms,
            usage=payload.get("usage") or {},
            raw=payload,
        )
