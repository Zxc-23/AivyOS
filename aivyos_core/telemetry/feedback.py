"""自进化反馈闭环（文档 §5.2.2 / T3.9 深化）：用户反馈 → 失败簇 → SpecSearchEngine 进化。

闭环（§5.2.2 / §12 周目标）：
  用户反馈（评分/文本）→ 采集运行 trace → 失败簇 → 触发 SpecSearchEngine
  → gate 只接受不退化的修改 → 优化后本地运行。

LLM 候选生成器（OpenJarvis 式"教师"）为可选增强；缺省启发式保底（evolution.py）。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aivyos_core.evolution import EvalResult, SpecSearchEngine

log = logging.getLogger(__name__)


class FeedbackCollector:
    """收集用户反馈与运行 trace，达到阈值触发进化（§5.2.2 反馈闭环）。"""

    def __init__(
        self,
        engine: SpecSearchEngine,
        trigger_threshold: int = 3,
        history_path: Optional[Path] = None,
    ) -> None:
        self.engine = engine
        self.trigger_threshold = trigger_threshold  # 负反馈达到阈值触发进化
        self.history_path = Path(history_path) if history_path else None
        self._feedbacks: List[Dict[str, Any]] = []
        self.evolution_runs: int = 0

    # ---- 反馈采集 ----

    def collect(self, feedback: Dict[str, Any]) -> Dict[str, Any]:
        """采集一条反馈：{score(1-5), text?, trace?}。负反馈（score<3）累积触发进化。"""
        item = {
            "score": float(feedback.get("score", 3)),
            "text": feedback.get("text", ""),
            "trace": feedback.get("trace", []),
            "ts": int(time.time()),
        }
        self._feedbacks.append(item)
        self._persist(item)
        if self._negative_count() >= self.trigger_threshold:
            return {"evolve": True, "pending": self._negative_count()}
        return {"evolve": False, "pending": self._negative_count()}

    def _negative_count(self) -> int:
        return sum(1 for f in self._feedbacks if f["score"] < 3)

    # ---- 触发进化（§5.2.2）----

    async def evolve(self, spec: Dict[str, Any], max_rounds: int = 2) -> Dict[str, Any]:
        """用全部负反馈的 trace 做失败簇，驱动 SpecSearchEngine 优化 spec。"""
        traces: List[Dict[str, Any]] = []
        for f in self._feedbacks:
            traces.extend(f.get("trace") or [])
        if not traces:
            log.info("[反馈闭环] 无 trace，直接按 spec 进化")
        # 注入失败簇 → 候选生成
        cluster_fn = self.engine._cluster_failures(traces)
        original_candidates = self.engine.candidates
        if cluster_fn:
            def gen_with_clusters(s, failures):
                if original_candidates is not None:
                    edits = original_candidates(s, failures)
                    if edits:
                        return edits
                return self.engine._heuristic_edits(s)
            self.engine.candidates = gen_with_clusters
        try:
            best = await self.engine.search_and_optimize(spec, max_rounds=max_rounds)
        finally:
            self.engine.candidates = original_candidates
        self.evolution_runs += 1
        # 清空已消费的反馈（避免重复触发）
        self._feedbacks = [f for f in self._feedbacks if f["score"] >= 3]
        return {
            "best_spec": best,
            "history": self.engine.history[-10:],
            "evolution_runs": self.evolution_runs,
        }

    # ---- 持久化 ----

    def _persist(self, item: Dict[str, Any]) -> None:
        if self.history_path is None:
            return
        try:
            import json

            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.history_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def status(self) -> Dict[str, Any]:
        return {
            "feedbacks": len(self._feedbacks),
            "negative": self._negative_count(),
            "threshold": self.trigger_threshold,
            "evolution_runs": self.evolution_runs,
        }
