"""Phase 3: 声明式降级链 (FallbackChain) — YAML/JSON 配置驱动的多 Provider 降级。

允许通过配置文件声明复杂的降级策略，如：
    primary (DashScope) -> secondary (Ollama) -> tertiary (mock)

功能：
    - 支持任意长度的降级链
    - 每级可指定模型、超时、重试次数
    - 支持基于错误类型的选择性降级
    - 动态启用/禁用某级
    - 与 CircuitBreaker 集成自动熔断

用法：
    from aivyos_core.llm.fallback_chain import FallbackChain, load_fallback_config

    chain = FallbackChain.from_config({
        "steps": [
            {"name": "primary", "model": "qwen-plus", "provider": "dashscope"},
            {"name": "secondary", "model": "llama3", "provider": "ollama"},
            {"name": "fallback", "model": "mock", "provider": "mock"},
        ]
    })
    result = await chain.execute(request, router)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


@dataclass
class FallbackStep:
    """降级链中的单个步骤。"""

    name: str
    model: str
    provider: str = ""
    temperature: float = 0.7
    max_retries: int = 1
    timeout_s: float = 60.0
    enabled: bool = True
    # 触发降级的错误类型
    fallback_on: List[str] = field(default_factory=lambda: [
        "timeout", "connection_error", "rate_limit", "server_error", "circuit_open"
    ])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "model": self.model,
            "provider": self.provider,
            "temperature": self.temperature,
            "max_retries": self.max_retries,
            "timeout_s": self.timeout_s,
            "enabled": self.enabled,
            "fallback_on": self.fallback_on,
        }


@dataclass
class FallbackResult:
    """降级链执行结果。"""

    success: bool
    step_used: str
    text: str = ""
    error: str = ""
    total_latency_ms: float = 0.0
    steps_attempted: List[str] = field(default_factory=list)
    # 每步结果摘要
    step_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "step_used": self.step_used,
            "text": self.text,
            "error": self.error,
            "total_latency_ms": self.total_latency_ms,
            "steps_attempted": self.steps_attempted,
            "step_results": self.step_results,
        }


class FallbackChain:
    """声明式降级链。

    按顺序尝试每个步骤，遇到可降级错误时自动切换到下一步。
    与 ModelRouter 集成，复用已有的后端实例和熔断器。

    用法：
        chain = FallbackChain(steps=[...])
        result = await chain.execute(llm_request, router)
    """

    def __init__(self, steps: List[FallbackStep]):
        """初始化降级链。

        Args:
            steps: 有序降级步骤列表。
        """
        self._steps = steps
        self._enabled_steps = [s for s in steps if s.enabled]

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "FallbackChain":
        """从配置字典创建降级链。

        Args:
            config: 配置字典，包含 steps 列表。

        Returns:
            FallbackChain 实例。
        """
        steps = []
        for step_cfg in config.get("steps", []):
            steps.append(FallbackStep(
                name=step_cfg.get("name", ""),
                model=step_cfg.get("model", ""),
                provider=step_cfg.get("provider", ""),
                temperature=step_cfg.get("temperature", 0.7),
                max_retries=step_cfg.get("max_retries", 1),
                timeout_s=step_cfg.get("timeout_s", 60.0),
                enabled=step_cfg.get("enabled", True),
                fallback_on=step_cfg.get("fallback_on", [
                    "timeout", "connection_error", "rate_limit", "server_error", "circuit_open"
                ]),
            ))
        return cls(steps)

    @property
    def steps(self) -> List[FallbackStep]:
        return self._steps

    def enable(self, name: str) -> None:
        """启用指定步骤。"""
        for s in self._steps:
            if s.name == name:
                s.enabled = True
        self._enabled_steps = [s for s in self._steps if s.enabled]

    def disable(self, name: str) -> None:
        """禁用指定步骤。"""
        for s in self._steps:
            if s.name == name:
                s.enabled = False
        self._enabled_steps = [s for s in self._steps if s.enabled]

    async def execute(self, request, router) -> FallbackResult:
        """执行降级链。

        Args:
            request: LLMRequest 实例。
            router: ModelRouter 实例。

        Returns:
            FallbackResult 实例。
        """
        total_start = time.monotonic()
        results: List[Dict[str, Any]] = []

        for step in self._enabled_steps:
            step_start = time.monotonic()
            attempts = 0

            while attempts < step.max_retries:
                attempts += 1
                try:
                    result = await self._try_step(step, request, router)
                    if result is not None:
                        elapsed = (time.monotonic() - step_start) * 1000
                        results.append({
                            "step": step.name,
                            "attempt": attempts,
                            "status": "success",
                            "latency_ms": round(elapsed, 1),
                        })
                        return FallbackResult(
                            success=True,
                            step_used=step.name,
                            text=result.text,
                            total_latency_ms=round((time.monotonic() - total_start) * 1000, 1),
                            steps_attempted=[s.name for s in self._enabled_steps[:self._enabled_steps.index(step) + 1]],
                            step_results=results,
                        )
                except Exception as e:
                    error_type = self._classify_error(e)
                    elapsed = (time.monotonic() - step_start) * 1000
                    results.append({
                        "step": step.name,
                        "attempt": attempts,
                        "status": "error",
                        "error_type": error_type,
                        "error_msg": str(e)[:200],
                        "latency_ms": round(elapsed, 1),
                    })

                    # 检查是否可降级
                    if error_type not in step.fallback_on:
                        # 不可降级的错误，直接失败
                        return FallbackResult(
                            success=False,
                            step_used=step.name,
                            error=f"[{error_type}] {e}",
                            total_latency_ms=round((time.monotonic() - total_start) * 1000, 1),
                            steps_attempted=[s.name for s in self._enabled_steps[:self._enabled_steps.index(step) + 1]],
                            step_results=results,
                        )

                    log.warning(
                        "降级链步骤 %s 失败 (尝试 %d/%d, 类型: %s)，尝试下一级",
                        step.name, attempts, step.max_retries, error_type,
                    )

        # 所有步骤都失败
        return FallbackResult(
            success=False,
            step_used="",
            error="所有降级步骤均失败",
            total_latency_ms=round((time.monotonic() - total_start) * 1000, 1),
            steps_attempted=[s.name for s in self._enabled_steps],
            step_results=results,
        )

    async def _try_step(
        self, step: FallbackStep, request, router
    ):
        """尝试单个降级步骤。

        Args:
            step: 降级步骤配置。
            request: LLM 请求。
            router: 路由器实例。

        Returns:
            LLMResponse 或 None。

        Raises:
            Exception: 触发降级的错误。
        """
        from aivyos_core.models import RouteDecision, RouteMode

        # 构建路由决策
        mode = RouteMode.CLOUD if step.provider and step.provider != "mock" else RouteMode.LOCAL
        decision = RouteDecision(
            mode=mode,
            model=step.model,
            reason=f"降级链: {step.name}",
        )

        # 设置超时
        try:
            response = await asyncio.wait_for(
                router.complete(request, decision),
                timeout=step.timeout_s,
            )
            return response
        except asyncio.TimeoutError:
            raise TimeoutError(f"步骤 {step.name} 超时 ({step.timeout_s}s)")

    @staticmethod
    def _classify_error(error: Exception) -> str:
        """将异常分类为错误类型。

        Args:
            error: 捕获的异常。

        Returns:
            错误类型标识符。
        """
        err_str = str(error).lower()
        if isinstance(error, TimeoutError) or "timeout" in err_str:
            return "timeout"
        if "connection" in err_str or "connect" in err_str or "refused" in err_str:
            return "connection_error"
        if "rate" in err_str or "429" in err_str or "too many" in err_str:
            return "rate_limit"
        if "circuit" in err_str or "breaker" in err_str or "open" in err_str:
            return "circuit_open"
        if "5" in err_str[:3] or "server" in err_str or "internal" in err_str:
            return "server_error"
        return "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "steps": [s.to_dict() for s in self._steps],
            "enabled_steps": [s.name for s in self._enabled_steps],
        }


def load_fallback_config(config_path: str) -> FallbackChain:
    """从 YAML/JSON 文件加载降级链配置。

    Args:
        config_path: 配置文件路径（支持 .yaml/.yml/.json）。

    Returns:
        FallbackChain 实例。
    """
    import os

    ext = os.path.splitext(config_path)[1].lower()
    with open(config_path, "r", encoding="utf-8") as f:
        if ext in (".yaml", ".yml"):
            try:
                import yaml
                config = yaml.safe_load(f)
            except ImportError:
                raise ImportError("需要 pyyaml 库: pip install pyyaml")
        elif ext == ".json":
            import json
            config = json.load(f)
        else:
            raise ValueError(f"不支持的配置格式: {ext}")

    return FallbackChain.from_config(config)