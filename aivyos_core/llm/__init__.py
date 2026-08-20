"""LLM 层：后端抽象、多提供商注册表、熔断保护、多维度路由策略。

Phase 1 模块：
    base.py          LLMBackend ABC + LLMBackendError
    mock.py          MockLLM（零依赖回退）
    openai_compat.py OpenAICompatLLM（兼容端点客户端）
    router.py        ModelRouter（Phase 1 路由，兼容模式）

Phase 2 扩展：
    circuit_breaker.py  CircuitBreaker + CircuitBreakerRegistry
    provider_registry.py ProviderRegistry（适配器注册/实例化/热切换）
    providers.py        11+ 提供商适配器（Ollama/vLLM/DeepSeek/OpenAI/Anthropic/...）

Phase 2 数据类型（models.py）：
    BackendCapability   后端能力标签
    BackendStatus       健康检查结果
    ProviderInfo        提供商元数据
    RoutingStrategy     路由策略枚举
"""

from aivyos_core.llm.base import LLMBackend, LLMBackendError
from aivyos_core.llm.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry
from aivyos_core.llm.mock import MockLLM
from aivyos_core.llm.openai_compat import OpenAICompatLLM
from aivyos_core.llm.provider_registry import ProviderRegistry
from aivyos_core.llm.providers import (
    AnthropicBackend,
    AzureOpenAIBackend,
    BedrockBackend,
    create_provider_info,
    DeepSeekBackend,
    GoogleAIBackend,
    MockBackend,
    MistralBackend,
    OllamaBackend,
    OpenAIBackend,
    QwenBackend,
    register_all_providers,
    SiliconFlowBackend,
    VLLMBackend,
)
from aivyos_core.llm.router import ModelRouter

__all__ = [
    # Phase 1（向后兼容）
    "LLMBackend",
    "LLMBackendError",
    "MockLLM",
    "OpenAICompatLLM",
    "ModelRouter",
    # Phase 2 新增
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "ProviderRegistry",
    "MockBackend",
    "OllamaBackend",
    "VLLMBackend",
    "DeepSeekBackend",
    "SiliconFlowBackend",
    "QwenBackend",
    "MistralBackend",
    "OpenAIBackend",
    "AnthropicBackend",
    "GoogleAIBackend",
    "AzureOpenAIBackend",
    "BedrockBackend",
    "register_all_providers",
    "create_provider_info",
]