"""LLM 层：后端抽象、OpenAI 兼容客户端、mock 回退、路由策略（§4.1）。"""

from aivyos_core.llm.base import LLMBackend, LLMBackendError
from aivyos_core.llm.mock import MockLLM
from aivyos_core.llm.openai_compat import OpenAICompatLLM
from aivyos_core.llm.router import ModelRouter

__all__ = ["LLMBackend", "LLMBackendError", "MockLLM", "OpenAICompatLLM", "ModelRouter"]
