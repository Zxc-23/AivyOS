"""记忆 LLM 抽取测试（A2：真实 LLM 可用 → LLM 抽取；否则规则回退）。"""

import asyncio
import os
import unittest

from aivyos_core.memory.manager import MemoryManager
from aivyos_core.models import LLMResponse

from tests import _TMP, AivyTestCase


class StubRealRouter:
    """模拟真实 LLM 后端可用的路由（避免依赖网络探测）。"""

    def __init__(self, text: str = "用户喜欢喝咖啡", model: str = "real-model"):
        self._text = text
        self._model = model
        self.cfg = {"local": {"model": "qwen2.5:7b"}, "cloud": {"model": "claude-latest"}}

    def _local_available(self):
        return True

    def _cloud_api_key(self):
        return None

    async def complete(self, request, decision):
        return LLMResponse(text=self._text, model=self._model)


class TestMemoryLlmExtract(AivyTestCase):
    def _manager(self, cfg_overrides: dict, router=None) -> MemoryManager:
        cfg = {"backend": "simple", "auto_extract": True, "simple_path": "mem.jsonl"}
        cfg.update(cfg_overrides)
        return MemoryManager(cfg, os.path.join(_TMP, "ext_" + str(len(os.listdir(_TMP)))), router=router)

    def test_llm_extract_when_real_available(self):
        m = self._manager({"extract_backend": "llm"}, router=StubRealRouter(text="用户喜欢喝咖啡"))
        rid = asyncio.run(m.try_extract("我跟你说，用户喜欢喝咖啡，别的不用记"))
        self.assertIsNotNone(rid)
        hits = asyncio.run(m.get_all())
        self.assertTrue(any("[LLM抽取]" in h.text for h in hits))

    def test_rules_fallback_when_llm_unavailable(self):
        m = self._manager({"extract_backend": "auto"})  # router=None → 规则
        rid = asyncio.run(m.try_extract("记住我叫小明"))
        self.assertIsNotNone(rid)
        hits = asyncio.run(m.get_all())
        self.assertTrue(any("[自动抽取]" in h.text for h in hits))

    def test_rules_backend_forced(self):
        m = self._manager({"extract_backend": "rules"}, router=StubRealRouter())
        rid = asyncio.run(m.try_extract("我喜欢喝咖啡"))
        self.assertIsNotNone(rid)
        hits = asyncio.run(m.get_all())
        self.assertTrue(any("[自动抽取]" in h.text for h in hits))

    def test_mock_llm_output_rejected(self):
        # LLM 返回 mock 模型（降级）→ 视为无真实 LLM → 规则回退
        m = self._manager({"extract_backend": "llm"}, router=StubRealRouter(text="用户喜欢咖啡", model="mock-echo"))
        rid = asyncio.run(m.try_extract("记住我叫小明"))
        self.assertIsNotNone(rid)
        hits = asyncio.run(m.get_all())
        self.assertTrue(any("[自动抽取]" in h.text for h in hits))
        self.assertFalse(any("[LLM抽取]" in h.text for h in hits))

    def test_auto_extract_disabled(self):
        m = self._manager({"auto_extract": False}, router=StubRealRouter())
        self.assertIsNone(asyncio.run(m.try_extract("记住X")))


if __name__ == "__main__":
    unittest.main()
