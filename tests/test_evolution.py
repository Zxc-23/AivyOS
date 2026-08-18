"""自进化引擎测试（§5.2.2 / T3.9）：gate 容差接受/拒绝、启发式候选。"""

import asyncio
import unittest

from aivyos_core.evolution import EvalResult, SpecSearchEngine

from tests import AivyTestCase


def make_evaluator(scores_by_spec):
    """按 spec 快照返回分数的求值器。"""

    def key(spec):
        return tuple(sorted(spec.items()))

    def evaluator(spec):
        return EvalResult(score=scores_by_spec.get(key(spec), 0.0))  # 未见过的 spec 得 0 分

    return evaluator


class TestSpecSearchEngine(AivyTestCase):
    def test_accepts_improving_edit(self):
        scores = {(("lr", 0.1),): 0.5, (("lr", 0.11),): 0.6}
        engine = SpecSearchEngine(evaluator=make_evaluator(scores))
        best = asyncio.run(engine.search_and_optimize({"lr": 0.1}, max_rounds=2))
        self.assertEqual(best["lr"], 0.11)
        self.assertTrue(any(h["accepted"] for h in engine.history))

    def test_rejects_degrading_edit(self):
        # 所有候选都退化 → 保持原 spec
        scores = {(("lr", 0.1),): 0.9, (("lr", 0.11),): 0.2, (("lr", 0.09),): 0.1}
        engine = SpecSearchEngine(evaluator=make_evaluator(scores))
        best = asyncio.run(engine.search_and_optimize({"lr": 0.1}, max_rounds=1))
        self.assertEqual(best["lr"], 0.1)  # 未接受任何退化

    def test_tolerance_allows_slight_degradation(self):
        # 容差内轻微退化可接受
        scores = {(("x", 1.0),): 1.0, (("x", 1.1),): 0.995}  # 0.5% 退化 < 1% 容差
        engine = SpecSearchEngine(evaluator=make_evaluator(scores), tolerance=0.01)
        best = asyncio.run(engine.search_and_optimize({"x": 1.0}, max_rounds=1))
        self.assertEqual(best["x"], 1.1)

    def test_custom_candidate_generator(self):
        def gen(spec, failures):
            from aivyos_core.evolution import SpecEdit

            return [SpecEdit("设为 2.0", lambda s: {**s, "y": 2.0})]

        scores = {(("y", 1.0),): 0.5, (("y", 2.0),): 0.8}
        engine = SpecSearchEngine(evaluator=make_evaluator(scores), candidate_generator=gen)
        best = asyncio.run(engine.search_and_optimize({"y": 1.0}))
        self.assertEqual(best["y"], 2.0)

    def test_failure_clustering(self):
        traces = [{"error": "timeout"}, {"error": "timeout"}, {"error": "oom"}]
        clusters = SpecSearchEngine._cluster_failures(traces)
        self.assertEqual(clusters[0], "timeout")


if __name__ == "__main__":
    unittest.main()
