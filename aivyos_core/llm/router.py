"""增强版 LLM 路由策略（Phase 2 多维度路由）。

Phase 1：按关键词复杂度路由 → local / cloud / mock 三选一。
Phase 2：多维度路由 — 能力匹配 → 可用性 → 成本/延迟优化 → 降级链。

支持的路由策略：
    auto              综合策略：能力匹配 → 可用性 → 成本优化
    cost-based        选最便宜的达标后端
    latency-based     选延迟最低的达标后端
    capability-based  严格按能力匹配

核心组件：
    ProviderRegistry  管理所有已注册的后端实例
    CircuitBreaker    每后端独立熔断保护
    FallbackChain     按优先级降级链

对应文档 §4.1.3 路由策略 + Phase 2 扩展。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from aivyos_core.llm.base import LLMBackend, LLMBackendError
from aivyos_core.llm.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry
from aivyos_core.llm.cost_tracker import CostTracker
from aivyos_core.llm.provider_registry import ProviderRegistry
from aivyos_core.llm.providers import MockBackend, create_provider_info, register_all_providers
from aivyos_core.models import (
    BackendCapability,
    BackendStatus,
    LLMRequest,
    LLMResponse,
    ProviderInfo,
    RouteDecision,
    RouteMode,
    RoutingStrategy,
)

log = logging.getLogger(__name__)

# ---- 复杂度关键词（沿用 Phase 1 逻辑，保持向后兼容） ----
CODING_KEYWORDS = (
    "代码", "写个", "实现", "函数", "脚本", "重构", "bug", "修复", "程序",
    "计算器", "网页", "项目", "接口", "api", "数据库", "算法",
)
COMPLEX_KEYWORDS = (
    "为什么", "分析", "对比", "方案", "规划", "评估", "权衡", "设计",
    "架构", "原因", "影响", "总结", "深度",
)
VISION_KEYWORDS = ("图片", "截图", "这张图", "识别图中", "看下这张")

# 任务类型 → 所需能力映射
TASK_CAPABILITY_MAP: Dict[str, Dict[str, Any]] = {
    "chat": {"streaming": True},
    "coding": {"streaming": True, "tool_use": True, "json_schema": True},
    "vision": {"vision": True, "streaming": True},
    "complex_reasoning": {"thinking": True, "streaming": True},
    "simple_chat": {"streaming": True},
}


class ModelRouter:
    """增强版多维度路由引擎。

    初始化流程：
        1. 创建 ProviderRegistry 并注册所有适配器类型
        2. 根据 llm_cfg.providers 配置实例化后端
        3. 首次创建时自动探测后端可用性
    """

    def __init__(self, llm_cfg: Dict[str, Any]) -> None:
        self.cfg = llm_cfg
        self.registry = ProviderRegistry()
        self._mock_backend: Optional[LLMBackend] = None
        self._probe_cache: Dict[str, Tuple[bool, float]] = {}
        self._forced_backend: Optional[str] = None

        # 成本追踪器
        self.cost_tracker = CostTracker()

        # 注册所有适配器类型
        register_all_providers(self.registry)

        # 路由策略
        self._strategy = llm_cfg.get("routing_strategy", RoutingStrategy.AUTO)

        # 初始化后端（兼容 Phase 1 配置）
        self._init_backends(llm_cfg)

        # 为所有已注册后端初始化成本追踪
        self._init_cost_tracking(llm_cfg)

        log.info("ModelRouter 初始化完成: %s", self.backends_summary())

    # ====================================================================
    # 初始化
    # ====================================================================

    def _init_backends(self, llm_cfg: Dict[str, Any]) -> None:
        """根据配置实例化所有后端。

        优先读取 llm_cfg.providers 列表；否则回退到 Phase 1 的 local/cloud 配置。
        """
        # ---- Phase 2 多提供商配置 ----
        providers = llm_cfg.get("providers")
        if providers and isinstance(providers, list):
            for prov_cfg in providers:
                self._init_provider_from_cfg(prov_cfg)
            return

        # ---- Phase 1 兼容配置 ----
        self._init_phase1_compat(llm_cfg)

    def _init_provider_from_cfg(self, prov_cfg: Dict[str, Any]) -> None:
        """从单个 provider 配置实例化后端。"""
        provider = prov_cfg.get("provider", "")
        model = prov_cfg.get("model", "")
        base_url = prov_cfg.get("base_url", "")
        api_key_env = prov_cfg.get("api_key_env", "")
        name = prov_cfg.get("name") or f"{provider}-{model}"

        info = ProviderInfo(
            name=name,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            priority=prov_cfg.get("priority", 50),
            enabled=prov_cfg.get("enabled", True),
            config={
                "timeout_s": prov_cfg.get("timeout_s", 60.0),
                "breaker_threshold": prov_cfg.get("breaker_threshold", 3),
                "breaker_cooldown_s": prov_cfg.get("breaker_cooldown_s", 60.0),
                "resource": prov_cfg.get("resource", ""),
                "deployment": prov_cfg.get("deployment", ""),
            },
        )

        try:
            self.registry.create(info)
        except Exception as e:
            log.warning("初始化后端失败 %s: %s", name, e)

    def _init_cost_tracking(self, llm_cfg: Dict[str, Any]) -> None:
        """为所有已注册后端初始化成本追踪费率。

        从 ProviderInfo.capabilities 中读取 cost_per_1m_input/output。
        """
        for backend in self._all_backends():
            info = self.registry.get_info(backend.name)
            if not info:
                continue
            caps = backend.capabilities
            self.cost_tracker.register_backend(
                backend_name=backend.name,
                provider=info.provider,
                model=info.model,
                cost_per_1m_input=caps.cost_per_1m_input,
                cost_per_1m_output=caps.cost_per_1m_output,
            )

    def _init_phase1_compat(self, llm_cfg: Dict[str, Any]) -> None:
        """Phase 1 兼容模式：将 local/cloud 配置迁移到 ProviderInfo。"""
        # ---- 本地后端 ----
        local_cfg = llm_cfg.get("local", {})
        if local_cfg:
            info = ProviderInfo(
                name="local-default",
                provider="ollama",
                model=local_cfg.get("model", "qwen2.5:3b"),
                base_url=local_cfg.get("base_url", "http://127.0.0.1:11434/v1"),
                api_key_env="",
                priority=30,
                config={
                    "timeout_s": local_cfg.get("timeout_s", 60.0),
                    "breaker_threshold": 3,
                    "breaker_cooldown_s": 60.0,
                },
            )
            try:
                self.registry.create(info)
            except Exception as e:
                log.warning("初始化本地后端失败: %s", e)

        # ---- 云端后端 ----
        cloud_cfg = llm_cfg.get("cloud", {})
        if cloud_cfg:
            # 根据 base_url 推断提供商
            base_url = cloud_cfg.get("base_url", "")
            provider = self._infer_provider_from_url(base_url)
            info = ProviderInfo(
                name="cloud-default",
                provider=provider,
                model=cloud_cfg.get("model", "claude-latest"),
                base_url=base_url,
                api_key_env=cloud_cfg.get("api_key_env", "AIVYOS_CLOUD_API_KEY"),
                priority=40,
                config={
                    "timeout_s": cloud_cfg.get("timeout_s", 120.0),
                },
            )
            try:
                self.registry.create(info)
            except Exception as e:
                log.warning("初始化云端后端失败: %s", e)

        # ---- Mock 后端 ----
        self._ensure_mock_backend()

    @staticmethod
    def _infer_provider_from_url(base_url: str) -> str:
        """根据 base_url 推断提供商类型。"""
        if not base_url:
            return "openai-compat"
        url = base_url.lower()
        if "ollama" in url or "11434" in url:
            return "ollama"
        if "vllm" in url or "8000" in url:
            return "vllm"
        if "deepseek" in url:
            return "deepseek"
        if "siliconflow" in url:
            return "siliconflow"
        if "dashscope" in url or "aliyun" in url:
            return "qwen"
        if "mistral" in url:
            return "mistral"
        if "openai" in url:
            return "openai"
        if "anthropic" in url:
            return "anthropic"
        if "google" in url or "generativelanguage" in url:
            return "google"
        if "azure" in url:
            return "azure-openai"
        if "bedrock" in url:
            return "bedrock"
        return "openai-compat"

    def _ensure_mock_backend(self) -> LLMBackend:
        """确保 mock 后端存在。"""
        if self._mock_backend is None:
            info = ProviderInfo(
                name="mock-default",
                provider="mock",
                model="mock-echo",
            )
            self._mock_backend = self.registry.create(info)
        return self._mock_backend

    # ====================================================================
    # 复杂度估计（沿用 Phase 1 逻辑）
    # ====================================================================

    @staticmethod
    def estimate_complexity(text: str, context_len: int = 0) -> str:
        """估计请求复杂度。

        Returns:
            simple_chat / coding / complex_reasoning / vision
        """
        t = text.lower()
        if any(k in t for k in VISION_KEYWORDS):
            return "vision"
        if any(k in t for k in CODING_KEYWORDS):
            return "coding"
        if any(k in t for k in COMPLEX_KEYWORDS) or context_len > 400:
            return "complex_reasoning"
        return "simple_chat"

    # ====================================================================
    # 路由决策
    # ====================================================================

    def route(
        self,
        text: str,
        context_len: int = 0,
        task_type: str = "chat",
        force_provider: Optional[str] = None,
    ) -> RouteDecision:
        """多维度路由决策。

        Args:
            text: 用户输入文本。
            context_len: 当前上下文长度（Token 数）。
            task_type: 任务类型（chat / coding / vision / complex_reasoning）。
            force_provider: 强制指定后端名称。

        Returns:
            RouteDecision: 包含选定后端名称、模型、决策原因。
        """
        mode = self.cfg.get("mode", "auto")

        # 确保 mock 后端存在（供强制模式和降级使用）
        self._ensure_mock_backend()

        # ---- 强制后端（用户通过 UI 指定）----
        if self._forced_backend:
            if self.registry.contains(self._forced_backend):
                backend = self.registry.get(self._forced_backend)
                if self.registry.can_execute(self._forced_backend):
                    return RouteDecision(
                        RouteMode.LOCAL if backend.provider in ("ollama", "vllm") else RouteMode.CLOUD,
                        backend.name,
                        f"用户强制指定: {self._forced_backend}",
                    )
                else:
                    log.warning("强制后端 %s 不可用，回退自动路由", self._forced_backend)

        # ---- 强制模式 ----
        if mode == "mock":
            mock = self._ensure_mock_backend()
            return RouteDecision(RouteMode.MOCK, mock.name, "强制 mock 模式")

        if force_provider:
            if self.registry.contains(force_provider):
                backend = self.registry.get(force_provider)
                return RouteDecision(
                    RouteMode.LOCAL if backend.provider in ("ollama", "vllm") else RouteMode.CLOUD,
                    backend.name,
                    f"强制指定后端: {force_provider}",
                )
            log.warning("强制指定的后端不存在: %s，回退自动路由", force_provider)

        # ---- Phase 1 强制模式兼容 ----
        if mode == "local":
            return self._route_phase1_local()
        if mode == "cloud":
            return self._route_phase1_cloud()

        # ---- auto：多维度路由 ----
        return self._route_auto(text, context_len, task_type)

    def _route_phase1_local(self) -> RouteDecision:
        """Phase 1 兼容：强制本地模式。"""
        backends = self._get_backends_by_provider("ollama") + self._get_backends_by_provider("vllm")
        available = [b for b in backends if self.registry.can_execute(b.name)]
        if available:
            b = available[0]
            return RouteDecision(RouteMode.LOCAL, b.name, "强制本地模式")
        mock = self._ensure_mock_backend()
        return RouteDecision(RouteMode.MOCK, mock.name, "强制本地模式但无可用后端，回退 mock", fallback=True)

    def _route_phase1_cloud(self) -> RouteDecision:
        """Phase 1 兼容：强制云端模式。"""
        backends = self._get_cloud_backends()
        available = [b for b in backends if self.registry.can_execute(b.name)]
        if available:
            b = available[0]
            return RouteDecision(RouteMode.CLOUD, b.name, "强制云端模式")
        mock = self._ensure_mock_backend()
        return RouteDecision(RouteMode.MOCK, mock.name, "强制云端模式但无可用后端，回退 mock", fallback=True)

    def _route_auto(self, text: str, context_len: int, task_type: str) -> RouteDecision:
        """自动路由：能力匹配 → 可用性 → 成本/延迟 → 降级。"""
        complexity = self.estimate_complexity(text, context_len)
        task_type = task_type if task_type != "chat" else complexity

        # Step 1：能力匹配
        required_caps = TASK_CAPABILITY_MAP.get(task_type, {})
        candidates = self._filter_by_capabilities(required_caps)

        # Step 2：过滤无 API Key 的云端后端（向后兼容 Phase 1）
        had_cloud_without_key = False
        filtered = []
        for b in candidates:
            info = self.registry.get_info(b.name)
            if info and info.provider in ("ollama", "vllm"):
                filtered.append(b)  # 本地后端始终可用
            elif info and info.api_key_env:
                key = os.environ.get(info.api_key_env, "")
                if not key:
                    # 尝试常见别名
                    key = self._resolve_cloud_key(info.api_key_env)
                if key:
                    filtered.append(b)
                else:
                    had_cloud_without_key = True
            elif info and not info.api_key_env:
                filtered.append(b)  # 显式配置无 key 的后端
        candidates = filtered

        # Step 3：过滤已禁用或熔断的后端
        healthy = [b for b in candidates if self.registry.can_execute(b.name)]

        if not healthy:
            log.warning("无健康后端匹配能力 %s，尝试所有健康后端", required_caps)
            healthy = [
                b for b in self._all_backends()
                if self.registry.can_execute(b.name)
            ]

        if not healthy:
            mock = self._ensure_mock_backend()
            return RouteDecision(
                RouteMode.MOCK, mock.name,
                f"所有后端不可用，回退 mock (task={task_type})",
                fallback=True,
            )

        # Step 4：按策略选择最优后端
        selected = self._select_by_strategy(healthy, task_type)
        info = self.registry.get_info(selected.name)

        reason = f"auto→{selected.name} (task={task_type}, strategy={self._strategy})"
        if info and info.priority < 50:
            reason += f", priority={info.priority}"

        mode = RouteMode.LOCAL if selected.provider in ("ollama", "vllm") else RouteMode.CLOUD
        needs_cloud_caps = task_type in ("complex_reasoning", "coding", "vision")
        fallback = had_cloud_without_key and mode == RouteMode.LOCAL and needs_cloud_caps
        return RouteDecision(mode, selected.name, reason, fallback=fallback)

    def _filter_by_capabilities(self, required: Dict[str, Any]) -> List[LLMBackend]:
        """过滤满足能力要求的后端。"""
        result = []
        for backend in self._all_backends():
            caps = backend.capabilities
            if required:
                if caps.supports(required):
                    result.append(backend)
            else:
                result.append(backend)
        return result

    def _select_by_strategy(
        self, backends: List[LLMBackend], task_type: str
    ) -> LLMBackend:
        """按路由策略从候选中选择最优后端。"""
        strategy = self._strategy

        if strategy == RoutingStrategy.COST_BASED:
            return min(
                backends,
                key=lambda b: (
                    b.capabilities.cost_per_1m_input + b.capabilities.cost_per_1m_output
                ),
            )

        if strategy == RoutingStrategy.LATENCY_BASED:
            # 延迟优先：按优先级近似排序（实际应基于历史测量数据）
            return min(
                backends,
                key=lambda b: self.registry.get_info(b.name).priority
                if self.registry.get_info(b.name)
                else 50,
            )

        if strategy == RoutingStrategy.CAPABILITY_BASED:
            # 能力最强优先
            return max(
                backends,
                key=lambda b: (
                    int(b.capabilities.thinking) * 100
                    + int(b.capabilities.vision) * 50
                    + int(b.capabilities.streaming) * 20
                    + b.capabilities.context_window // 1000
                ),
            )

        # auto：按优先级 + 能力 + 成本综合排序
        def score(b: LLMBackend) -> float:
            info = self.registry.get_info(b.name)
            priority_score = (info.priority if info else 50)
            free_score = 100 if b.capabilities.free_tier else 0
            cost_score = max(0, 50 - (b.capabilities.cost_per_1m_input * 1000))
            return priority_score + free_score + cost_score

        return min(backends, key=score)

    # ====================================================================
    # 后端调用
    # ====================================================================

    def _resolve_backend(self, model_id: str) -> LLMBackend:
        """通过唯一标识符或模型名查找后端（向后兼容）。

        Args:
            model_id: ProviderInfo.name（唯一标识符）或 LLM 模型名。

        Returns:
            LLMBackend 实例。

        Raises:
            LLMBackendError: 找不到对应后端。
        """
        # 1. 尝试精确匹配唯一标识符
        if self.registry.contains(model_id):
            return self.registry.get(model_id)

        # 2. 尝试按模型名匹配（向后兼容 Phase 1 代码）
        for backend in self._all_backends():
            if backend.model == model_id:
                return backend

        # 3. 尝试按 backend.name 匹配（即 ProviderInfo.name）
        for backend in self._all_backends():
            if backend.name == model_id:
                return backend

        raise LLMBackendError(f"找不到后端: {model_id}")

    async def complete(self, request: LLMRequest, decision: RouteDecision) -> LLMResponse:
        """执行路由决策并调用后端，支持熔断和自动降级。

        Args:
            request: LLM 请求。
            decision: 路由决策。

        Returns:
            LLMResponse: 后端响应。

        Raises:
            LLMBackendError: 所有后端均失败。
        """
        # 获取后端
        if decision.mode == RouteMode.MOCK:
            backend = self._ensure_mock_backend()
        else:
            try:
                backend = self._resolve_backend(decision.model)
            except LLMBackendError:
                log.error("路由指定的后端不存在: %s", decision.model)
                backend = self._ensure_mock_backend()
                decision = RouteDecision(RouteMode.MOCK, backend.name, "后端不存在，降级 mock", fallback=True)

        # 检查熔断
        if not self.registry.can_execute(backend.name):
            log.warning("后端 %s 熔断中，降级 mock", backend.name)
            mock = self._ensure_mock_backend()
            decision = RouteDecision(RouteMode.MOCK, mock.name, f"后端 {backend.name} 熔断，降级 mock", fallback=True)
            backend = mock

        # 执行调用
        try:
            response = await backend.complete(request)
            self.registry.record_success(backend.name)

            # 成本追踪：从 response.usage 中提取 token 用量
            input_tokens = response.usage.get("prompt_tokens", 0) or response.usage.get("input_tokens", 0)
            output_tokens = response.usage.get("completion_tokens", 0) or response.usage.get("output_tokens", 0)
            self.cost_tracker.record(
                backend_name=backend.name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=response.latency_ms,
                provider=backend.provider,
                model=backend.model,
            )
            return response
        except LLMBackendError as e:
            self.registry.record_failure(backend.name)
            log.error("后端 %s 调用失败: %s", backend.name, e)

            # 非 mock 后端失败 → 降级 mock
            if decision.mode != RouteMode.MOCK:
                mock = self._ensure_mock_backend()
                decision = RouteDecision(
                    RouteMode.MOCK, mock.name,
                    f"{backend.name} 调用失败，降级 mock",
                    fallback=True,
                )
                try:
                    response = await mock.complete(request)
                    return response
                except Exception as mock_e:
                    raise LLMBackendError(
                        f"后端 {backend.name} 失败({e}) + mock 也失败({mock_e})"
                    ) from mock_e
            raise

    async def stream(self, request: LLMRequest, decision: RouteDecision):
        """流式调用后端，支持降级。"""
        if decision.mode == RouteMode.MOCK:
            backend = self._ensure_mock_backend()
        else:
            try:
                backend = self._resolve_backend(decision.model)
            except LLMBackendError:
                backend = self._ensure_mock_backend()

        try:
            async for chunk in backend.stream(request):
                yield chunk
            self.registry.record_success(backend.name)
        except LLMBackendError as e:
            self.registry.record_failure(backend.name)
            log.error("流式调用失败 %s: %s", backend.name, e)
            # 降级到 mock 同步响应
            mock = self._ensure_mock_backend()
            fallback_request = LLMRequest(
                messages=request.messages,
                model=mock.name,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
            response = await mock.complete(fallback_request)
            yield response

    # ====================================================================
    # 后端查询
    # ====================================================================

    def _all_backends(self) -> List[LLMBackend]:
        """获取所有已实例化的后端。"""
        return [
            self.registry.get(name)
            for name in list(self.registry._instances.keys())
            if self.registry.contains(name)
        ]

    def _get_backends_by_provider(self, provider: str) -> List[LLMBackend]:
        """按提供商类型过滤后端。"""
        return [b for b in self._all_backends() if b.provider == provider]

    def _get_cloud_backends(self) -> List[LLMBackend]:
        """获取云端后端（非本地、非 mock）。"""
        local_providers = {"ollama", "vllm", "mock"}
        return [b for b in self._all_backends() if b.provider not in local_providers]

    def backends_status(self) -> List[Dict[str, Any]]:
        """返回所有后端状态（向后兼容 Phase 1 接口）。"""
        result = []
        for backend in self._all_backends():
            info = self.registry.get_info(backend.name)
            breaker = self.registry.get_breaker(backend.name)
            result.append({
                "mode": backend.provider,
                "model": backend.name,
                "provider": backend.provider,
                "available": self.registry.can_execute(backend.name),
                "breaker_state": breaker.state if breaker else "unknown",
                "priority": info.priority if info else 50,
                "capabilities": backend.capabilities.to_dict(),
                "active": backend.name == self._forced_backend,
            })
        # 确保 mock 后端始终展示
        mock = self._ensure_mock_backend()
        if not any(b["mode"] == "mock" for b in result):
            result.append({
                "mode": "mock",
                "model": mock.name,
                "provider": "mock",
                "available": True,
                "breaker_state": "closed",
                "priority": 100,
                "capabilities": mock.capabilities.to_dict(),
            })
        return result

    def backends_summary(self) -> str:
        """返回后端摘要字符串（日志用）。"""
        backends = self._all_backends()
        names = [f"{b.name}({b.provider})" for b in backends]
        return f"ModelRouter: {len(backends)} 后端 [{', '.join(names)}]"

    # ====================================================================
    # 动态管理
    # ====================================================================

    def add_provider(self, info: ProviderInfo) -> LLMBackend:
        """动态添加后端。"""
        return self.registry.create(info)

    def remove_provider(self, name: str) -> bool:
        """动态移除后端。"""
        return self.registry.remove(name)

    async def health_check_all(self) -> Dict[str, BackendStatus]:
        """健康检查所有后端。"""
        return await self.registry.health_check_all()

    def set_strategy(self, strategy: str) -> None:
        """动态切换路由策略。"""
        valid = {s.value for s in RoutingStrategy}
        if strategy not in valid:
            raise ValueError(f"无效策略: {strategy}，可选: {valid}")
        self._strategy = strategy
        log.info("路由策略切换为: %s", strategy)

    def set_forced_backend(self, name: Optional[str]) -> None:
        """强制使用指定后端（None 则取消强制）。"""
        if name is not None and not self.registry.contains(name):
            raise ValueError(f"后端不存在: {name}")
        self._forced_backend = name
        if name:
            log.info("强制后端设置为: %s", name)
        else:
            log.info("取消强制后端，恢复自动路由")

    @property
    def forced_backend(self) -> Optional[str]:
        return self._forced_backend

    # ====================================================================
    # Phase 1 兼容方法
    # ====================================================================

    @property
    def _probe_ok(self) -> bool:
        """Phase 1 兼容：本地探测状态（带 TTL 缓存）。"""
        return self._local_available()

    @property
    def _probe_at(self) -> Optional[float]:
        for name, (ok, ts) in self._probe_cache.items():
            if ok:
                return ts
        return None

    @property
    def _probe_ttl(self) -> float:
        return float(self.cfg.get("local", {}).get("probe_ttl_s", 20))

    def _local_available(self) -> bool:
        """Phase 1 兼容：本地后端是否可用（真实 HTTP 探测 + TTL 缓存）。"""
        if os.environ.get("AIVYOS_DISABLE_LOCAL") == "1":
            return False

        local_cfg = self.cfg.get("local", {})
        probe_enabled = local_cfg.get("probe", True)

        if not probe_enabled:
            # 探测关闭 → 乐观可用
            local_backends = self._get_backends_by_provider("ollama") + self._get_backends_by_provider("vllm")
            return len(local_backends) > 0

        # 带 TTL 缓存的真实探测
        probe_ttl = self._probe_ttl
        now = time.monotonic()

        # 检查缓存
        for name in list(self._probe_cache.keys()):
            ok, ts = self._probe_cache[name]
            if now - ts < probe_ttl:
                if ok:
                    return True
            else:
                del self._probe_cache[name]

        # 执行探测
        local_backends = self._get_backends_by_provider("ollama") + self._get_backends_by_provider("vllm")
        if not local_backends:
            # Phase 1 兼容：无本地后端配置，执行一次探测
            return self._do_probe_phase1(local_cfg)

        for backend in local_backends:
            ok = self._probe_backend(backend)
            self._probe_cache[backend.name] = (ok, now)
            if ok:
                return True
        return False

    def _probe_backend(self, backend: LLMBackend) -> bool:
        """对单个后端执行同步健康检查。"""
        info = self.registry.get_info(backend.name)
        if not info:
            return False
        base_url = info.base_url.rstrip("/")
        try:
            req = urllib.request.Request(f"{base_url}/models", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _do_probe_phase1(self, local_cfg: Dict[str, Any]) -> bool:
        """Phase 1 兼容：直接探测 local.base_url（无 ProviderInfo 后端时）。"""
        base_url = local_cfg.get("base_url", "http://127.0.0.1:11434/v1").rstrip("/")
        timeout = float(local_cfg.get("probe_timeout_s", 1.5))
        try:
            req = urllib.request.Request(f"{base_url}/models", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _cloud_api_key(self) -> Optional[str]:
        """Phase 1 兼容：云端 API Key。"""
        for backend in self._get_cloud_backends():
            info = self.registry.get_info(backend.name)
            if info and info.api_key_env:
                key = os.environ.get(info.api_key_env)
                if key:
                    return key
        # Phase 1 兼容：回退到 AIVYOS_CLOUD_API_KEY
        return os.environ.get("AIVYOS_CLOUD_API_KEY")

    # 常见 API Key 环境变量别名映射
    _CLOUD_KEY_ALIASES: Dict[str, List[str]] = {
        "AIVYOS_CLOUD_API_KEY": ["DEEPSEEK_API_KEY", "SILICONFLOW_API_KEY", "DASHSCOPE_API_KEY",
                                  "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"],
        "DEEPSEEK_API_KEY": ["AIVYOS_CLOUD_API_KEY", "DEEPSEEK_API_KEY"],
    }

    def _resolve_cloud_key(self, primary_env: str) -> str:
        """尝试从常见别名中查找 API Key。"""
        # 直接查找
        key = os.environ.get(primary_env, "")
        if key:
            return key
        # 查找别名
        aliases = self._CLOUD_KEY_ALIASES.get(primary_env, [])
        for alias in aliases:
            key = os.environ.get(alias, "")
            if key:
                return key
        return ""

    def _mock_cfg(self) -> Dict[str, Any]:
        return self.cfg.get("mock", {"model": "mock-echo"})