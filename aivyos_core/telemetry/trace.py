"""OpenTelemetry 风格链路追踪（文档 §21.2 / T10.1）：零依赖实现 + JSONL 导出。

- Tracer：创建根/子 Span，自动嵌套（父子关系），记录耗时与属性
- Span：name / trace_id / span_id / parent_id / start / duration / status / attributes
- 导出：JSONL 本地落盘（缺省）；OTLP/gRPC 为可选增强（缺库时优雅降级为 JSONL）

链路示例（§21.2）：ASR → LLM → 工具 → TTS 完整调用链。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class Span:
    """单个追踪段（§21.2 调用链节点）。"""

    def __init__(
        self,
        name: str,
        trace_id: str,
        span_id: str,
        parent_id: Optional[str],
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_id = parent_id
        self.attributes = attributes or {}
        self.start_ts = time.time()
        self.duration_ms: Optional[float] = None
        self.status: str = "ok"
        self.error: Optional[str] = None

    def finish(self, status: str = "ok", error: Optional[str] = None) -> None:
        self.duration_ms = round((time.time() - self.start_ts) * 1000, 2)
        self.status = status
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "start_ts": round(self.start_ts, 3),
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "attributes": self.attributes,
        }


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class Tracer:
    """线程安全追踪器：span 自动嵌套（thread-local 栈）。"""

    def __init__(self, export_path: Optional[Path] = None, enabled: bool = True) -> None:
        self.enabled = enabled
        self.export_path = Path(export_path) if export_path else None
        self._local = threading.local()
        self._spans: List[Span] = []
        self._lock = threading.Lock()

    # ---- 当前上下文 ----

    def _current_span_id(self) -> Optional[str]:
        stack = getattr(self._local, "stack", None)
        return stack[-1].span_id if stack else None

    # ---- 手动 span ----

    def start_span(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> Span:
        """开始 span（自动挂到当前栈顶为父）。"""
        if not self.enabled:
            return Span(name, "disabled", "0", None)
        parent_id = self._current_span_id()
        trace_id = getattr(self._local, "trace_id", None) or _new_id()
        span = Span(name, trace_id, _new_id(), parent_id, attributes)
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = []
            self._local.stack = stack
            self._local.trace_id = trace_id
        stack.append(span)
        return span

    def end_span(self, span: Span, status: str = "ok", error: Optional[str] = None) -> None:
        """结束 span 并记录。"""
        if not self.enabled:
            return
        span.finish(status, error)
        stack = getattr(self._local, "stack", [])
        if stack and stack[-1] is span:
            stack.pop()
            if not stack:
                self._local.trace_id = None
        with self._lock:
            self._spans.append(span)
        if self.export_path is not None:
            self._export(span)

    # ---- 上下文管理器（with tracer.span("name")）----

    def span(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        return _SpanCtx(self, name, attributes)

    # ---- 导出（§21.2 本地 JSONL；OTLP 可选降级）----

    def _export(self, span: Span) -> None:
        try:
            self.export_path.parent.mkdir(parents=True, exist_ok=True)
            with self.export_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(span.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("span 导出失败: %s", e)

    def export_otlp(self, endpoint: str) -> Dict[str, Any]:
        """OTLP 上报（可选增强）：无 otlp 客户端时诚实降级，返回未上报说明。"""
        try:
            import grpc  # noqa: F401
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # noqa: F401

            return {"exported": False, "backend": "otlp", "note": "OTLP 客户端可用；接入 grpc 通道后启用"}
        except ImportError:
            return {"exported": False, "backend": "jsonl", "note": "未安装 OTLP 依赖，span 已本地 JSONL 落盘"}

    def spans(self, trace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            all_spans = [s.to_dict() for s in self._spans]
        if trace_id is None:
            return all_spans
        return [s for s in all_spans if s["trace_id"] == trace_id]

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()

    def status(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "spans": len(self._spans), "export": str(self.export_path) if self.export_path else "memory"}


class _SpanCtx:
    """with tracer.span(...) 上下文管理器。"""

    def __init__(self, tracer: Tracer, name: str, attributes: Optional[Dict[str, Any]]) -> None:
        self.tracer = tracer
        self.name = name
        self.attributes = attributes

    def __enter__(self) -> Span:
        self.span = self.tracer.start_span(self.name, self.attributes)
        return self.span

    def __exit__(self, exc_type, exc, tb) -> bool:
        status = "error" if exc_type is not None else "ok"
        self.tracer.end_span(self.span, status=status, error=str(exc) if exc else None)
        return False  # 不吞异常
