"""可观测性与自进化反馈闭环测试（Phase 3 Week 12 / T10.x）：
span 嵌套/耗时/导出 / 指标累加·直方图·P95 / JSON 日志·安全审计 / 反馈闭环触发进化 / 工作流追踪。"""

import asyncio
import json
import os
import shutil
import time
import unittest
from pathlib import Path

from aivyos_core.evolution import EvalResult, SpecSearchEngine
from aivyos_core.telemetry import (
    Counter,
    FeedbackCollector,
    Gauge,
    Histogram,
    JsonlHandler,
    MetricsRegistry,
    SecurityAuditLog,
    Span,
    Tracer,
    attach_json_logging,
    replay_workflow,
    to_mermaid,
    trace_workflow_run,
)

from tests import AivyTestCase, _TMP


class TestTracer(AivyTestCase):
    def test_span_nesting_and_duration(self):
        t = Tracer()
        with t.span("root", {"modality": "voice"}) as root:
            time.sleep(0.01)
            with t.span("llm") as child:
                time.sleep(0.01)
        spans = t.spans()
        self.assertEqual(len(spans), 2)
        # 完成顺序：子 span 先结束 → spans[0]=child, spans[1]=root
        child_s, root_s = spans[0], spans[1]
        self.assertEqual(child_s["parent_id"], root_s["span_id"])  # 自动嵌套
        self.assertEqual(root_s["trace_id"], child_s["trace_id"])
        self.assertGreaterEqual(root_s["duration_ms"], child_s["duration_ms"])
        self.assertEqual(root_s["status"], "ok")
        self.assertEqual(root_s["attributes"], {"modality": "voice"})

    def test_span_error_status(self):
        t = Tracer()
        try:
            with t.span("boom"):
                raise ValueError("x")
        except ValueError:
            pass
        s = t.spans()[0]
        self.assertEqual(s["status"], "error")
        self.assertIn("x", s["error"])

    def test_jsonl_export(self):
        path = Path(_TMP) / "traces.jsonl"
        if path.exists():
            path.unlink()
        t = Tracer(export_path=path)
        with t.span("a"):
            pass
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["name"], "a")
        self.assertIn("duration_ms", entry)

    def test_otlp_fallback_honest(self):
        t = Tracer()
        r = t.export_otlp("http://localhost:4317")
        self.assertFalse(r["exported"])  # 未装 OTLP → 诚实降级 JSONL
        self.assertIn("backend", r)


class TestMetrics(AivyTestCase):
    def test_counter_accumulate(self):
        reg = MetricsRegistry()
        c = reg.counter("requests_total", "总请求数")
        c.inc()
        c.inc(2)
        out = reg.render()
        self.assertIn("# TYPE requests_total counter", out)
        self.assertIn("requests_total 3.0", out)

    def test_gauge_set(self):
        reg = MetricsRegistry()
        g = reg.gauge("gpu_memory_used", "显存占用")
        g.set(0.7)
        self.assertIn("gpu_memory_used 0.7", reg.render())

    def test_histogram_buckets_and_p95(self):
        reg = MetricsRegistry()
        h = reg.histogram("llm_ttft_ms", "LLM 首 Token 延迟", buckets_ms=[10, 50, 100, 500])
        for v in (20, 30, 200, 200):
            h.observe(v)
        self.assertEqual(h.percentile(50), 50)   # 中位 → bucket 50
        self.assertEqual(h.percentile(95), 500)  # P95 → bucket 500
        out = reg.render()
        self.assertIn("_bucket", out)
        self.assertIn("_sum", out)
        self.assertIn("_count", out)

    def test_duplicate_registration_rejected(self):
        reg = MetricsRegistry()
        reg.counter("x")
        with self.assertRaises(ValueError):
            reg.counter("x")


class TestJsonLogs(AivyTestCase):
    def test_jsonl_handler(self):
        import logging

        path = Path(_TMP) / "app.jsonl"
        if path.exists():
            path.unlink()
        logger = logging.getLogger("test.telemetry")
        logger.setLevel(logging.INFO)  # 确保 INFO 通过 logger 级别
        handler = attach_json_logging(logger, path, level=logging.INFO)
        try:
            logger.info("hello %s", "world", extra={"fields": {"model": "qwen2.5:3b"}})
        finally:
            logger.removeHandler(handler)
        entry = json.loads(path.read_text(encoding="utf-8").strip().split("\n")[0])
        self.assertEqual(entry["level"], "INFO")
        self.assertEqual(entry["message"], "hello world")
        self.assertEqual(entry["model"], "qwen2.5:3b")

    def test_security_audit(self):
        path = Path(_TMP) / "security.jsonl"
        if path.exists():
            path.unlink()
        audit = SecurityAuditLog(path)
        audit.event("SIGNATURE_INVALID", "签名失败", version="1.2.3")
        entries = audit.read()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["code"], "SIGNATURE_INVALID")
        self.assertEqual(entries[0]["version"], "1.2.3")


class TestFeedbackLoop(AivyTestCase):
    def _engine(self):
        """evaluator：score 随 spec 的 temperature 越接近 0.7 越高。"""
        def evaluator(spec):
            temp = float(spec.get("temperature", 0.7))
            score = 1.0 - abs(temp - 0.7)  # 越接近 0.7 分越高
            return EvalResult(score=score, traces=[{"error": "quality_low"}])

        return SpecSearchEngine(evaluator=evaluator, max_edits=5)

    def test_feedback_trigger_evolve(self):
        engine = self._engine()
        fb = FeedbackCollector(engine, trigger_threshold=2)
        for i in range(2):
            r = fb.collect({"score": 1, "text": "回答不好", "trace": [{"error": "quality_low"}]})
        self.assertTrue(r["evolve"])  # 负反馈达阈值 → 触发进化

        best = asyncio.run(fb.evolve({"temperature": 0.3}))
        self.assertIn("best_spec", best)
        self.assertEqual(fb.evolution_runs, 1)
        self.assertEqual(fb.status()["negative"], 0)  # 消费后清零

    def test_below_threshold_no_evolve(self):
        fb = FeedbackCollector(self._engine(), trigger_threshold=5)
        r = fb.collect({"score": 2})
        self.assertFalse(r["evolve"])

    def test_feedback_history_persist(self):
        path = Path(_TMP) / "feedback.jsonl"
        if path.exists():
            path.unlink()
        fb = FeedbackCollector(self._engine(), trigger_threshold=99, history_path=path)
        fb.collect({"score": 4, "text": "不错"})
        entry = json.loads(path.read_text(encoding="utf-8").strip().split("\n")[0])
        self.assertEqual(entry["score"], 4.0)


class TestWorkflowTrace(AivyTestCase):
    def test_trace_and_mermaid(self):
        import os
        import shutil

        from aivyos_core.workflow.checkpointer import SqliteCheckpointer
        from aivyos_core.workflow.workflows import build_vibe_coding_graph

        ck = SqliteCheckpointer(os.path.join(_TMP, "ck_trace.db"))
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
        trace = trace_workflow_run(app, {"user_request": "做一个天气网页"}, thread_id="wf_trace")
        self.assertEqual(trace["trace"][0], "understand")
        self.assertIn("node_timings_ms", trace)
        self.assertIn("understand", trace["node_timings_ms"])
        self.assertGreaterEqual(trace["total_ms"], 0)
        mermaid = to_mermaid(trace)
        self.assertIn("sequenceDiagram", mermaid)
        self.assertIn("understand", mermaid)

    def test_replay_workflow(self):
        import os

        from aivyos_core.workflow.checkpointer import SqliteCheckpointer
        from aivyos_core.workflow.workflows import build_vibe_coding_graph

        ck = SqliteCheckpointer(os.path.join(_TMP, "ck_replay.db"))
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
        import asyncio

        asyncio.run(app.invoke({"user_request": "做个网页"}, thread_id="wf_replay"))
        replay = replay_workflow(ck, "wf_replay")
        self.assertIsNotNone(replay)
        self.assertEqual(replay["thread_id"], "wf_replay")
        self.assertIn("state_keys", replay)

    def test_node_timings_recorded(self):
        import os

        from aivyos_core.workflow.checkpointer import SqliteCheckpointer
        from aivyos_core.workflow.workflows import build_vibe_coding_graph

        ck = SqliteCheckpointer(os.path.join(_TMP, "ck_timing.db"))
        app = build_vibe_coding_graph(ck).compile(checkpointer=ck)
        import asyncio

        asyncio.run(app.invoke({"user_request": "网页"}, thread_id="wf_timing"))
        self.assertIn("understand", app.node_timings_ms)
        self.assertIn("generate", app.node_timings_ms)
        self.assertGreater(app.node_timings_ms["understand"], 0)


if __name__ == "__main__":
    unittest.main()
