"""核心数据模型（Phase 1 + Phase 2 扩展）：消息、会话、LLM 请求/响应、路由决策、后端能力标签。

会话状态对应文档 §14.3 状态快照中的"会话上下文"（JSON 序列化，可恢复）。
Phase 2 新增：BackendCapability、BackendStatus、ProviderInfo，用于多提供商适配器层。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, ClassVar


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ChatMessage:
    role: str
    content: str
    name: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChatMessage":
        return cls(
            role=d["role"],
            content=d.get("content", ""),
            name=d.get("name"),
            timestamp=d.get("timestamp", time.time()),
        )


@dataclass
class LLMRequest:
    messages: List[Dict[str, str]]
    model: str
    max_tokens: int = 2048
    temperature: float = 0.7
    stream: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LLMResponse:
    text: str
    model: str
    latency_ms: float = 0.0
    usage: Dict[str, int] = field(default_factory=dict)
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RouteMode(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"
    MOCK = "mock"


@dataclass
class RouteDecision:
    mode: RouteMode
    model: str
    reason: str
    fallback: bool = False  # True 表示本应走真实模型但降级

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "model": self.model,
            "reason": self.reason,
            "fallback": self.fallback,
        }


@dataclass
class SessionState:
    """会话状态（§14.3 快照对象：会话上下文，JSON 序列化 <100ms）。"""

    session_id: str = field(default_factory=lambda: "sess_" + uuid.uuid4().hex[:8])
    persona_name: str = "Aivy"
    messages: List[ChatMessage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add(self, role: str, content: str) -> None:
        self.messages.append(ChatMessage(role=role, content=content))
        self.updated_at = time.time()

    def recent(self, n: int) -> List[ChatMessage]:
        return self.messages[-n:] if n > 0 else list(self.messages)

    def snapshot(self) -> Dict[str, Any]:
        """原子快照（§14.3）：JSON 可序列化，用于热交换/重启恢复。"""
        return {
            "session_id": self.session_id,
            "persona_name": self.persona_name,
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_snapshot(cls, data: Dict[str, Any]) -> "SessionState":
        return cls(
            session_id=data.get("session_id"),
            persona_name=data.get("persona_name", "Aivy"),
            messages=[ChatMessage.from_dict(m) for m in data.get("messages", [])],
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


# ============================================================================
# Phase 2: 多提供商适配器层数据类型
# ============================================================================


@dataclass
class BackendCapability:
    """后端能力标签 — 每个 LLM 后端声明自身支持的功能集合。"""

    streaming: bool = False
    vision: bool = False
    json_schema: bool = False
    thinking: bool = False
    tool_use: bool = False
    structured_output: bool = False
    context_window: int = 4096
    max_output_tokens: int = 2048
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0
    free_tier: bool = False
    setup_time_s: float = 0.0

    def supports(self, required: Dict[str, Any]) -> bool:
        """检查后端是否满足所需能力集合。"""
        for key, value in required.items():
            if getattr(self, key, None) != value:
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackendStatus:
    """后端健康检查结果。"""

    provider: str
    model: str
    status: str = "unknown"       # ok / degraded / down / unknown
    latency_ms: float = 0.0
    detail: str = ""
    last_check: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderInfo:
    """提供商元数据 — 描述一个已注册的 LLM 后端。"""

    name: str                     # 唯一标识，如 "ollama-local"
    provider: str                 # 提供商类型，如 "ollama" / "deepseek"
    model: str                    # 默认模型名
    base_url: str = ""
    api_key_env: str = ""
    capabilities: BackendCapability = field(default_factory=BackendCapability)
    enabled: bool = True
    priority: int = 50            # 路由优先级（越小越优先）
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["capabilities"] = self.capabilities.to_dict()
        return d


class RoutingStrategy(str, Enum):
    """路由策略枚举。"""
    AUTO = "auto"               # 综合策略：能力 → 可用性 → 成本
    COST_BASED = "cost-based"   # 成本最优
    LATENCY_BASED = "latency-based"  # 延迟最优
    CAPABILITY_BASED = "capability-based"  # 能力匹配


# ============================================================================
# Phase 1 原有数据类型（保持不变）
# ============================================================================


@dataclass
class AssistantReply:
    text: str
    session_id: str
    model: str
    route: RouteDecision
    latency_ms: float
    memory_hits: List[Dict[str, Any]] = field(default_factory=list)
    context_stats: Dict[str, Any] = field(default_factory=dict)
