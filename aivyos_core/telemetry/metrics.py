"""Prometheus 风格指标采集（文档 §21.2 / T10.2）：零依赖 Counter/Gauge/Histogram + 文本导出。

- Counter：单调累加（请求数、错误数）
- Gauge：可增可减（显存占用、GPU 利用率）
- Histogram：延迟分布（bucket 计数 + sum + count，§21.3 P95）
- 导出：Prometheus 文本格式（text/plain; version=0.0.4），Grafana 可抓取（可选增强）
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

# §21.3 延迟指标默认 bucket（毫秒）
DEFAULT_BUCKETS_MS = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]


class Metric:
    name: str = ""
    help_text: str = ""
    type_name: str = "untyped"

    def __init__(self, name: str, help_text: str = "", labels: Optional[List[str]] = None) -> None:
        self.name = name
        self.help_text = help_text
        self.labels = labels or []

    def _label_key(self, label_values: tuple) -> str:
        return "{" + ",".join(f'{k}="{v}"' for k, v in zip(self.labels, label_values)) + "}" if self.labels else ""


class Counter(Metric):
    type_name = "counter"

    def __init__(self, name: str, help_text: str = "", labels: Optional[List[str]] = None) -> None:
        super().__init__(name, help_text, labels)
        self._values: Dict[tuple, float] = {}
        self._lock = threading.Lock()

    def inc(self, value: float = 1.0, label_values: Optional[tuple] = None) -> None:
        with self._lock:
            k = tuple(label_values or ())
            self._values[k] = self._values.get(k, 0.0) + value

    def export(self) -> str:
        with self._lock:
            items = sorted(self._values.items())
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} counter"]
        for k, v in items:
            lines.append(f"{self.name}{self._label_key(k)} {v}")
        return "\n".join(lines)


class Gauge(Metric):
    type_name = "gauge"

    def __init__(self, name: str, help_text: str = "", labels: Optional[List[str]] = None) -> None:
        super().__init__(name, help_text, labels)
        self._values: Dict[tuple, float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, label_values: Optional[tuple] = None) -> None:
        with self._lock:
            self._values[tuple(label_values or ())] = float(value)

    def export(self) -> str:
        with self._lock:
            items = sorted(self._values.items())
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} gauge"]
        for k, v in items:
            lines.append(f"{self.name}{self._label_key(k)} {v}")
        return "\n".join(lines)


class Histogram(Metric):
    type_name = "histogram"

    def __init__(
        self, name: str, help_text: str = "", labels: Optional[List[str]] = None,
        buckets_ms: Optional[List[float]] = None,
    ) -> None:
        super().__init__(name, help_text, labels)
        self.buckets = sorted(buckets_ms or DEFAULT_BUCKETS_MS)
        self._counts: Dict[tuple, List[int]] = {}
        self._sums: Dict[tuple, float] = {}
        self._lock = threading.Lock()

    def observe(self, value_ms: float, label_values: Optional[tuple] = None) -> None:
        with self._lock:
            k = tuple(label_values or ())
            if k not in self._counts:
                self._counts[k] = [0] * len(self.buckets)
                self._sums[k] = 0.0
            self._counts[k] = [c + (1 if value_ms <= b else 0) for c, b in zip(self._counts[k], self.buckets)]
            self._sums[k] += value_ms

    def percentile(self, p: float = 95.0, label_values: Optional[tuple] = None) -> Optional[float]:
        """§21.3 P95：基于 bucket 直方图近似（bucket 为累积计数，total = 最大 bucket）。"""
        with self._lock:
            k = tuple(label_values or ())
            if k not in self._counts:
                return None
            total = self._counts[k][-1] if self._counts[k] else 0
            if total == 0:
                return None
            target = total * p / 100.0
            # bucket 计数本身为累积值：直接找首个累积计数 ≥ target 的 bucket
            for i, c in enumerate(self._counts[k]):
                if c >= target:
                    return self.buckets[i]
            return self.buckets[-1]

    def export(self) -> str:
        with self._lock:
            keys = sorted(set(self._counts) | set(self._sums))
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} histogram"]
        for k in keys:
            counts = self._counts.get(k, [0] * len(self.buckets))
            lines.append(f'{self.name}_bucket{self._label_key(k + ("le",))}')
            for b, c in zip(self.buckets, counts):
                le = self._label_key(k + (f"{b:g}",))
                lines.append(f"{self.name}_bucket{le} {c}")
            lines.append(f"{self.name}_bucket{self._label_key(k + ('+Inf',))} {counts[-1]}")
            lines.append(f"{self.name}_sum{self._label_key(k)} {self._sums.get(k, 0.0)}")
            lines.append(f"{self.name}_count{self._label_key(k)} {counts[-1]}")
        return "\n".join(lines)


class MetricsRegistry:
    """指标注册表（§21.2）：注册 + Prometheus 文本导出。"""

    def __init__(self) -> None:
        self._metrics: Dict[str, Metric] = {}
        self._lock = threading.Lock()

    def register(self, metric: Metric) -> Metric:
        with self._lock:
            if metric.name in self._metrics:
                raise ValueError(f"指标已注册: {metric.name}")
            self._metrics[metric.name] = metric
        return metric

    def counter(self, name: str, help_text: str = "", labels: Optional[List[str]] = None) -> Counter:
        return self.register(Counter(name, help_text, labels))

    def gauge(self, name: str, help_text: str = "", labels: Optional[List[str]] = None) -> Gauge:
        return self.register(Gauge(name, help_text, labels))

    def histogram(self, name: str, help_text: str = "", labels: Optional[List[str]] = None, buckets_ms: Optional[List[float]] = None) -> Histogram:
        return self.register(Histogram(name, help_text, labels, buckets_ms))

    def get(self, name: str) -> Optional[Metric]:
        with self._lock:
            return self._metrics.get(name)

    def render(self) -> str:
        """Prometheus 文本格式（§21.2，Grafana 可抓取）。"""
        with self._lock:
            names = sorted(self._metrics)
        blocks = [self._metrics[n].export() for n in names]
        return "\n\n".join(blocks)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {n: m.export() for n, m in self._metrics.items()}
