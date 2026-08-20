"""Phase 2 成本追踪模块：Token 用量统计 + 费用计算。

功能：
    - 每后端独立统计 input/output token 数
    - 按请求维度记录（可追溯）
    - 按时间窗口聚合（1h/1d 滚动窗口）
    - 基于 ProviderInfo 中 cost_per_1m 计算费用
    - 提供实时仪表盘数据

对应报告 §Phase 2 成本追踪任务。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any, Deque, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class CostEntry:
    """单次请求成本记录。"""
    timestamp: float
    backend_name: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackendCostStats:
    """后端聚合统计。"""
    backend_name: str
    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    last_updated: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CostTracker:
    """Token 用量与费用追踪器（线程安全）。

    用法：
        tracker = CostTracker()
        tracker.register_backend("ollama-local", cost_per_1m_input=0.0, cost_per_1m_output=0.0)
        tracker.record("ollama-local", input_tokens=100, output_tokens=50, latency_ms=200)
        stats = tracker.get_stats()
    """

    def __init__(self, max_history: int = 10000) -> None:
        """初始化成本追踪器。

        Args:
            max_history: 每后端最大历史记录数（LRU 截断）。
        """
        self._lock = threading.Lock()
        self._max_history = max_history
        self._history: Dict[str, Deque[CostEntry]] = defaultdict(
            lambda: deque(maxlen=max_history)
        )
        self._aggregates: Dict[str, BackendCostStats] = {}
        self._cost_rates: Dict[str, tuple] = {}  # backend_name → (input_per_1m, output_per_1m)

    def register_backend(
        self,
        backend_name: str,
        provider: str = "",
        model: str = "",
        cost_per_1m_input: float = 0.0,
        cost_per_1m_output: float = 0.0,
    ) -> None:
        """注册后端及其费率。

        Args:
            backend_name: 后端唯一标识符。
            provider: 提供商类型。
            model: 模型名。
            cost_per_1m_input: 每 100 万 input token 费用（USD）。
            cost_per_1m_output: 每 100 万 output token 费用（USD）。
        """
        with self._lock:
            self._cost_rates[backend_name] = (cost_per_1m_input, cost_per_1m_output)
            if backend_name not in self._aggregates:
                self._aggregates[backend_name] = BackendCostStats(
                    backend_name=backend_name,
                )

    def record(
        self,
        backend_name: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float = 0.0,
        provider: str = "",
        model: str = "",
        timestamp: Optional[float] = None,
    ) -> CostEntry:
        """记录一次请求的 Token 用量。

        Args:
            backend_name: 后端唯一标识符。
            input_tokens: 输入 token 数。
            output_tokens: 输出 token 数。
            latency_ms: 响应延迟（毫秒）。
            provider: 提供商类型。
            model: 模型名。
            timestamp: 时间戳（默认当前时间）。

        Returns:
            CostEntry 记录对象。
        """
        ts = timestamp or time.monotonic()
        cost = self._calculate_cost(backend_name, input_tokens, output_tokens)

        entry = CostEntry(
            timestamp=ts,
            backend_name=backend_name,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
        )

        with self._lock:
            self._history[backend_name].append(entry)
            stats = self._aggregates.get(backend_name)
            if stats:
                total = stats.total_requests
                stats.total_requests += 1
                stats.total_input_tokens += input_tokens
                stats.total_output_tokens += output_tokens
                stats.total_cost_usd += cost
                if total > 0:
                    stats.avg_latency_ms = (
                        stats.avg_latency_ms * total + latency_ms
                    ) / (total + 1)
                else:
                    stats.avg_latency_ms = latency_ms
                stats.last_updated = ts

        return entry

    def _calculate_cost(
        self, backend_name: str, input_tokens: int, output_tokens: int
    ) -> float:
        """计算请求费用。

        Args:
            backend_name: 后端唯一标识符。
            input_tokens: 输入 token 数。
            output_tokens: 输出 token 数。

        Returns:
            费用（USD），保留 6 位小数。
        """
        rates = self._cost_rates.get(backend_name, (0.0, 0.0))
        input_cost = (input_tokens / 1_000_000) * rates[0]
        output_cost = (output_tokens / 1_000_000) * rates[1]
        return round(input_cost + output_cost, 6)

    def get_stats(self, backend_name: Optional[str] = None) -> Dict[str, Any]:
        """获取成本统计。

        Args:
            backend_name: 指定后端（None 表示全部）。

        Returns:
            统计数据字典。
        """
        with self._lock:
            if backend_name:
                stats = self._aggregates.get(backend_name)
                return stats.to_dict() if stats else {}
            return {
                name: s.to_dict()
                for name, s in self._aggregates.items()
            }

    def get_recent(
        self, backend_name: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """获取最近 N 条记录。

        Args:
            backend_name: 指定后端（None 表示全部）。
            limit: 返回条数。

        Returns:
            记录列表（按时间倒序）。
        """
        with self._lock:
            results = []
            names = [backend_name] if backend_name else list(self._history.keys())
            for name in names:
                entries = list(self._history.get(name, deque()))
                entries.reverse()
                results.extend(e.to_dict() for e in entries[:limit])
            results.sort(key=lambda x: x["timestamp"], reverse=True)
            return results[:limit]

    def get_dashboard(self) -> Dict[str, Any]:
        """获取仪表盘汇总数据。

        Returns:
            仪表盘数据字典，包含：
            - total_requests: 总请求数
            - total_tokens: 总 token 数
            - total_cost_usd: 总费用
            - backends: 每后端统计
            - recent: 最近 10 条记录
        """
        with self._lock:
            total_requests = sum(
                s.total_requests for s in self._aggregates.values()
            )
            total_tokens = sum(
                s.total_input_tokens + s.total_output_tokens
                for s in self._aggregates.values()
            )
            total_cost = sum(
                s.total_cost_usd for s in self._aggregates.values()
            )

            # 内联实现 recent（避免死锁）
            recent_results = []
            for name in self._history:
                entries = list(self._history[name])
                entries.reverse()
                recent_results.extend(e.to_dict() for e in entries[:10])
            recent_results.sort(key=lambda x: x["timestamp"], reverse=True)
            recent_results = recent_results[:10]

            return {
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 4),
                "backend_count": len(self._aggregates),
                "backends": {
                    name: s.to_dict()
                    for name, s in self._aggregates.items()
                },
                "recent": recent_results,
                "timestamp": time.monotonic(),
            }

    def reset(self, backend_name: Optional[str] = None) -> None:
        """重置统计数据。

        Args:
            backend_name: 指定后端（None 表示全部）。
        """
        with self._lock:
            if backend_name:
                self._history.pop(backend_name, None)
                if backend_name in self._aggregates:
                    self._aggregates[backend_name] = BackendCostStats(
                        backend_name=backend_name
                    )
            else:
                self._history.clear()
                self._aggregates.clear()
                for name in self._cost_rates:
                    self._aggregates[name] = BackendCostStats(backend_name=name)

    def export_json(self) -> str:
        """导出为 JSON 字符串。

        Returns:
            JSON 格式的仪表盘数据。
        """
        return json.dumps(self.get_dashboard(), indent=2, ensure_ascii=False)