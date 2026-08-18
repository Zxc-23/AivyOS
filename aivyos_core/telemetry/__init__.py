"""可观测性与自进化反馈闭环（Phase 3 Week 12 / T10.x）。

- trace：OpenTelemetry 风格链路追踪（T10.1）
- metrics：Prometheus 指标采集（T10.2）
- logs：结构化 JSON 日志 + 安全审计（T10.4）
- feedback：自进化反馈闭环（§5.2.2 深化）
- workflow_trace：工作流追踪（检查点回放，T10.3）
"""

from aivyos_core.telemetry.feedback import FeedbackCollector
from aivyos_core.telemetry.logs import JsonlHandler, SecurityAuditLog, attach_json_logging, log_fields
from aivyos_core.telemetry.metrics import Counter, Gauge, Histogram, MetricsRegistry
from aivyos_core.telemetry.trace import Span, Tracer
from aivyos_core.telemetry.workflow_trace import replay_workflow, to_mermaid, trace_workflow_run

__all__ = [
    "Span", "Tracer",
    "Counter", "Gauge", "Histogram", "MetricsRegistry",
    "JsonlHandler", "SecurityAuditLog", "attach_json_logging", "log_fields",
    "FeedbackCollector",
    "trace_workflow_run", "replay_workflow",
]
