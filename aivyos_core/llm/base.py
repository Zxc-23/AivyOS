"""LLM 后端抽象与异常。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from aivyos_core.models import LLMRequest, LLMResponse


class LLMBackendError(Exception):
    """LLM 后端调用失败（超时、网络、鉴权、服务不可用等）。"""


class LLMBackend(ABC):
    """LLM 后端接口：所有推理引擎（vLLM/Ollama/云端/mock）统一实现。"""

    name: str = "base"

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """执行一次补全，返回响应。"""
        raise NotImplementedError
