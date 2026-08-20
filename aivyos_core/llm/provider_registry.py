"""提供商注册表 — 管理 LLM 后端适配器的注册、实例化、热切换。

核心设计：
    1. 适配器类注册：register() 将 Provider 类注册到注册表
    2. 实例化：create() 根据 ProviderInfo 配置实例化后端
    3. 热切换：支持运行时替换后端配置，自动处理旧实例的优雅关闭
    4. 状态查询：list_backends() 返回所有后端的状态与能力

典型用法：
    registry = ProviderRegistry()
    registry.register("ollama", OllamaBackend)
    registry.register("deepseek", DeepSeekBackend)

    info = ProviderInfo(name="my-ollama", provider="ollama", model="qwen2.5:7b", ...)
    backend = registry.create(info)

    result = await registry.get("my-ollama").complete(request)
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import Any, Dict, List, Optional, Type

from aivyos_core.llm.base import LLMBackend, LLMBackendError
from aivyos_core.llm.circuit_breaker import CircuitBreakerRegistry
from aivyos_core.models import (
    BackendCapability,
    BackendStatus,
    ProviderInfo,
)

log = logging.getLogger(__name__)


class ProviderRegistry:
    """LLM 提供商注册表 — 适配器发现、实例管理、热切换。

    支持三种注册方式：
        1. 直接注册类：register("ollama", OllamaBackend)
        2. 自动发现：discover_providers() 扫描 providers 模块
        3. 动态加载：load_provider_from_module(module_path, class_name)
    """

    def __init__(self) -> None:
        self._providers: Dict[str, Type[LLMBackend]] = {}
        self._instances: Dict[str, LLMBackend] = {}
        self._info_map: Dict[str, ProviderInfo] = {}
        self._breakers = CircuitBreakerRegistry()

    # ---- 注册 ----

    def register(self, provider_type: str, backend_cls: Type[LLMBackend]) -> None:
        """注册一个提供商适配器类。

        Args:
            provider_type: 提供商类型标识（如 "ollama"、"deepseek"）。
            backend_cls: LLMBackend 的子类。

        Raises:
            TypeError: backend_cls 不是 LLMBackend 子类时。
        """
        if not isinstance(backend_cls, type) or not issubclass(backend_cls, LLMBackend):
            raise TypeError(
                f"backend_cls 必须是 LLMBackend 的子类，实际: {type(backend_cls)}"
            )
        self._providers[provider_type] = backend_cls
        log.info("注册 LLM 提供商适配器: %s → %s", provider_type, backend_cls.__name__)

    def unregister(self, provider_type: str) -> None:
        """注销一个提供商适配器类型（不影响已实例化的后端）。"""
        if provider_type in self._providers:
            del self._providers[provider_type]
            log.info("注销 LLM 提供商适配器: %s", provider_type)

    def list_provider_types(self) -> List[str]:
        """列出所有已注册的提供商类型。"""
        return list(self._providers.keys())

    # ---- 实例化 ----

    def create(self, info: ProviderInfo) -> LLMBackend:
        """根据 ProviderInfo 实例化一个后端。

        Args:
            info: 提供商元数据配置。

        Returns:
            LLMBackend 实例。

        Raises:
            LLMBackendError: 未知提供商类型或实例化失败。
        """
        if info.provider not in self._providers:
            raise LLMBackendError(
                f"未知提供商类型: {info.provider}，"
                f"已注册: {list(self._providers.keys())}"
            )

        cls = self._providers[info.provider]
        try:
            backend = cls(info=info)
        except Exception as e:
            raise LLMBackendError(
                f"实例化 {info.provider} 后端失败: {e}",
                provider=info.provider,
                model=info.model,
            ) from e

        self._instances[info.name] = backend
        self._info_map[info.name] = info

        # 初始化熔断器
        self._breakers.get_or_create(
            name=info.name,
            failure_threshold=info.config.get("breaker_threshold", 3),
            cooldown_seconds=info.config.get("breaker_cooldown_s", 60.0),
        )

        log.info(
            "创建 LLM 后端: %s (provider=%s, model=%s, caps=%s)",
            info.name, info.provider, info.model,
            {k: v for k, v in info.capabilities.to_dict().items() if v},
        )
        return backend

    def get(self, name: str) -> LLMBackend:
        """获取已实例化的后端。

        Raises:
            LLMBackendError: 后端未初始化。
        """
        if name not in self._instances:
            raise LLMBackendError(f"后端未初始化: {name}")
        return self._instances[name]

    def get_info(self, name: str) -> Optional[ProviderInfo]:
        """获取后端的 ProviderInfo。"""
        return self._info_map.get(name)

    def contains(self, name: str) -> bool:
        """检查是否存在指定名称的后端。"""
        return name in self._instances

    def remove(self, name: str) -> bool:
        """移除一个已实例化的后端。

        Returns:
            是否成功移除。
        """
        if name in self._instances:
            del self._instances[name]
            self._info_map.pop(name, None)
            log.info("移除 LLM 后端: %s", name)
            return True
        return False

    # ---- 查询 ----

    def list_backends(self) -> List[Dict[str, Any]]:
        """返回所有已注册后端的状态与能力摘要。"""
        result = []
        for name, backend in self._instances.items():
            info = self._info_map.get(name)
            breaker = self._breakers.get(name)
            result.append({
                "name": name,
                "provider": backend.provider,
                "model": backend.name,
                "enabled": info.enabled if info else True,
                "capabilities": backend.capabilities.to_dict(),
                "breaker_state": breaker.state if breaker else "unknown",
                "breaker_stats": breaker.get_stats() if breaker else {},
            })
        return result

    async def health_check_all(self) -> Dict[str, BackendStatus]:
        """对所有已实例化的后端执行健康检查。"""
        results: Dict[str, BackendStatus] = {}
        for name, backend in self._instances.items():
            try:
                status = await backend.health_check()
                results[name] = status
            except Exception as e:
                results[name] = BackendStatus(
                    provider=backend.provider,
                    model=backend.name,
                    status="down",
                    detail=str(e)[:200],
                )
        return results

    # ---- 熔断器便捷访问 ----

    @property
    def breakers(self) -> CircuitBreakerRegistry:
        """获取熔断器注册表。"""
        return self._breakers

    def get_breaker(self, name: str):
        """获取指定后端的熔断器。"""
        return self._breakers.get(name)

    def can_execute(self, name: str) -> bool:
        """检查指定后端是否允许执行请求。"""
        cb = self._breakers.get(name)
        if cb is None:
            return True
        return cb.can_execute()

    def record_success(self, name: str) -> None:
        """为指定后端记录成功。"""
        cb = self._breakers.get(name)
        if cb:
            cb.record_success()

    def record_failure(self, name: str) -> None:
        """为指定后端记录失败。"""
        cb = self._breakers.get(name)
        if cb:
            cb.record_failure()

    # ---- 动态加载 ----

    def load_provider_from_module(self, module_path: str, class_name: str) -> None:
        """从模块路径动态加载提供商适配器。

        Args:
            module_path: Python 模块路径（如 "aivyos_core.llm.providers"）。
            class_name: 适配器类名。

        Raises:
            ImportError: 模块加载失败。
            AttributeError: 类不存在。
        """
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        if not issubclass(cls, LLMBackend):
            raise TypeError(f"{class_name} 不是 LLMBackend 子类")
        # 从类属性获取 provider 类型
        provider_type = getattr(cls, "provider", class_name.lower().replace("backend", ""))
        self.register(provider_type, cls)
        log.info("动态加载提供商: %s.%s → %s", module_path, class_name, provider_type)

    # ---- 调试 ----

    def __len__(self) -> int:
        return len(self._instances)

    def __repr__(self) -> str:
        return (
            f"<ProviderRegistry providers={len(self._providers)} "
            f"instances={len(self._instances)}>"
        )