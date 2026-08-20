"""LLM 后端抽象接口（Phase 2 扩展版）。

Phase 1: 仅定义 complete() 同步补全方法。
Phase 2: 扩展 stream()、embed()、health_check()、capabilities 属性，
         支持多提供商注册表、流式响应、嵌入向量、健康检查等能力。

所有 LLM 后端（Ollama / vLLM / DeepSeek / OpenAI / Anthropic / Qwen / mock 等）
均实现此统一接口，通过 ProviderRegistry 进行管理。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional

from aivyos_core.models import (
    BackendCapability,
    BackendStatus,
    LLMRequest,
    LLMResponse,
)


class LLMBackendError(Exception):
    """LLM 后端调用失败（超时、网络、鉴权、服务不可用、格式异常等）。"""

    def __init__(self, message: str, provider: str = "", model: str = "") -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model


class LLMBackend(ABC):
    """LLM 后端统一抽象基类。

    所有推理引擎必须实现 complete() 方法，可选实现 stream() / embed() /
    health_check()。通过 capabilities 属性声明自身能力集合，供路由层决策。

    生命周期：
        1. ProviderRegistry.create() 实例化
        2. ModelRouter.route() 选定后端
        3. complete() / stream() 执行推理
        4. health_check() 定期探测
    """

    # ---- 类属性 ----
    name: str = "base"          # 后端实例标识
    provider: str = "unknown"   # 提供商类型（ollama / deepseek / ...）

    # ---- 能力声明 ----

    @property
    def capabilities(self) -> BackendCapability:
        """返回后端能力标签（子类应覆盖）。"""
        return BackendCapability()

    # ---- 核心方法（必须实现） ----

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """执行一次文本补全，返回完整响应。

        Args:
            request: LLM 请求对象，包含 messages / model / max_tokens 等。

        Returns:
            LLMResponse: 包含 text / model / latency_ms / usage 的响应。

        Raises:
            LLMBackendError: 调用失败时抛出。
        """
        raise NotImplementedError

    # ---- 扩展方法（可选实现，默认抛 NotImplementedError） ----

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        """流式补全，异步迭代返回增量响应。

        默认实现：调用 complete() 后将结果包装为单元素迭代器。
        子类应覆盖以实现真正的 SSE / chunked 流式传输。

        Args:
            request: LLM 请求对象（request.stream 应为 True）。

        Yields:
            LLMResponse: 每个 chunk 的增量响应，最终 chunk 包含完整文本。

        Raises:
            LLMBackendError: 调用失败时抛出。
        """
        response = await self.complete(request)
        yield response

    async def embed(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """生成文本嵌入向量。

        Args:
            texts: 待嵌入的文本列表。
            model: 嵌入模型名（None 使用默认）。

        Returns:
            List[List[float]]: 每个文本的嵌入向量。

        Raises:
            NotImplementedError: 后端不支持嵌入时抛出。
            LLMBackendError: 调用失败时抛出。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 未实现 embed()，"
            f"请使用支持嵌入的后端或切换到本地嵌入方案。"
        )

    async def health_check(self) -> BackendStatus:
        """执行健康检查，返回后端状态。

        默认实现：基于 capabilities 构造基础状态，不进行实际探测。
        子类应覆盖以实现真实的端点探测（如 GET /models）。

        Returns:
            BackendStatus: 包含 status / latency_ms / detail 的状态对象。
        """
        return BackendStatus(
            provider=self.provider,
            model=self.name,
            status="unknown",
            latency_ms=0.0,
            detail="未实现 health_check，状态未知",
        )

    # ---- 便捷方法 ----

    def supports(self, capability: str) -> bool:
        """检查后端是否支持指定能力。"""
        return bool(getattr(self.capabilities, capability, False))

    def status_dict(self) -> Dict[str, Any]:
        """返回后端状态摘要（供前端展示）。"""
        return {
            "name": self.name,
            "provider": self.provider,
            "capabilities": self.capabilities.to_dict(),
            "supports_streaming": self.supports("streaming"),
            "supports_vision": self.supports("vision"),
            "supports_thinking": self.supports("thinking"),
        }