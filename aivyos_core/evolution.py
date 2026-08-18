"""自进化引擎（文档 §5.2.2 / T3.9）：LLM 引导的 Spec 搜索（参考 OpenJarvis）。

流程（§5.2.2）：
  基线评估 → 采集运行 trace → （云端/本地）分析失败簇 → 提出配置编辑候选
  → 逐个评估 → gate（默认 1% 容差）只接受不退化的修改 → 优化后完全本地运行
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

# 默认容差：score >= baseline * (1 - tolerance) 才接受（§5.2.2 gate）
DEFAULT_TOLERANCE = 0.01


@dataclass
class EvalResult:
    score: float
    traces: List[Dict[str, Any]] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)


@dataclass
class SpecEdit:
    description: str
    apply: Callable[[Dict[str, Any]], Dict[str, Any]]


class SpecSearchEngine:
    """LLM 引导的 Spec 搜索（§5.2.2 简化实现，可插拔候选生成器）。"""

    def __init__(
        self,
        evaluator: Callable[[Dict[str, Any]], EvalResult],
        candidate_generator: Optional[Callable[[Dict[str, Any], List[str]], List[SpecEdit]]] = None,
        tolerance: float = DEFAULT_TOLERANCE,
        max_edits: int = 5,
    ) -> None:
        self.evaluate = evaluator
        self.candidates = candidate_generator  # (spec, failure_clusters) -> edits
        self.tolerance = tolerance
        self.max_edits = max_edits
        self.history: List[Dict[str, Any]] = []

    async def search_and_optimize(self, spec: Dict[str, Any], max_rounds: int = 3) -> Dict[str, Any]:
        """迭代优化 spec，保证不退化（gate 容差）。"""
        best_spec = dict(spec)
        baseline = await self._eval_async(spec)
        for round_idx in range(max_rounds):
            failure_clusters = self._cluster_failures(baseline.traces)
            edits = self._generate_edits(best_spec, failure_clusters)
            if not edits:
                break
            improved = False
            for edit in edits[: self.max_edits]:
                candidate = edit.apply(dict(best_spec))
                score = await self._eval_async(candidate)
                self.history.append({
                    "round": round_idx + 1,
                    "edit": edit.description,
                    "baseline": baseline.score,
                    "candidate": score.score,
                    "accepted": score.score >= baseline.score * (1 - self.tolerance),
                })
                if score.score >= baseline.score * (1 - self.tolerance):
                    if score.score > baseline.score:
                        improved = True
                    best_spec = candidate
                    baseline = score
                else:
                    log.info("[进化] 拒绝退化: %.4f < %.4f（容差 %.1f%%）", score.score, baseline.score, self.tolerance * 100)
            if not improved:
                break
        return best_spec

    # ---- 内部 ----

    async def _eval_async(self, spec: Dict[str, Any]) -> EvalResult:
        result = self.evaluate(spec)
        if not isinstance(result, EvalResult):
            return EvalResult(score=float(result))
        return result

    @staticmethod
    def _cluster_failures(traces: List[Dict[str, Any]]) -> List[str]:
        """失败簇：按 error 关键词聚合（朴素聚类）。"""
        clusters: Dict[str, int] = {}
        for t in traces:
            err = str(t.get("error", ""))[:60]
            if err:
                clusters[err] = clusters.get(err, 0) + 1
        return sorted(clusters, key=clusters.get, reverse=True)[:5]

    def _generate_edits(self, spec: Dict[str, Any], failure_clusters: List[str]) -> List[SpecEdit]:
        """候选生成：优先外部（LLM）生成器，缺省用启发式参数微调。"""
        if self.candidates is not None:
            edits = self.candidates(spec, failure_clusters)
            if edits:
                return edits
        return self._heuristic_edits(spec)

    @staticmethod
    def _heuristic_edits(spec: Dict[str, Any]) -> List[SpecEdit]:
        """启发式候选：对数值参数做 ±10% 微调（无 LLM 时的保底）。"""
        edits: List[SpecEdit] = []

        def _mk(key: str, factor: float, desc: str) -> SpecEdit:
            def apply(s: Dict[str, Any]) -> Dict[str, Any]:
                out = dict(s)
                if key in out and isinstance(out[key], (int, float)):
                    out[key] = round(float(out[key]) * factor, 4)
                return out

            return SpecEdit(description=desc, apply=apply)

        for key, value in spec.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                edits.append(_mk(key, 1.1, f"调大 {key} 10%"))
                edits.append(_mk(key, 0.9, f"调小 {key} 10%"))
        return edits
