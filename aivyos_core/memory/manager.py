"""记忆管理器：按配置选择后端（mem0 优先，缺失自动降级 simple）。

事实抽取（A2 清理）：extract_backend=auto|rules|llm
- llm：真实 LLM 后端可用时用 LLM 抽取（更自然），否则回退规则
- rules：朴素句式规则（原行为）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from aivyos_core.memory.base import MemoryBackend, MemoryHit
from aivyos_core.memory.mem0_backend import Mem0Backend, Mem0Unavailable
from aivyos_core.memory.simple import SimpleFileMemory

log = logging.getLogger(__name__)

# 规则抽取句式（LLM 不可用时的回退）
_EXTRACT_PATTERNS = (
    ("记住", 0.8),
    ("我喜欢", 0.9),
    ("我讨厌", 0.9),
    ("我叫", 1.0),
    ("我是", 0.7),
    ("我的名字", 1.0),
    ("别忘了", 0.9),
    ("记得", 0.7),
)

_EXTRACT_PROMPT = """从下面用户话语中提取一条值得长期记住的事实或偏好。

要求：
- 只输出提取到的事实本身，用 <fact> 标签包裹
- 第一人称、简洁（不超过 50 字）
- 不要复述原话、不要解释、不要添加原文没有的信息
- 若没有值得长期记住的信息（如寒暄、天气闲聊、一次性请求），输出 <fact>无</fact>

示例：
话语：我叫小明，喜欢喝咖啡 → <fact>我叫小明，喜欢喝咖啡</fact>
话语：今天天气不错 → <fact>无</fact>

用户话语：{text}
"""

_EXTRACT_EMPTY = {"无", "没有", "空", "none", "n/a", "null", "空行"}


def _clean_extract(out: str) -> Optional[str]:
    """清洗 LLM 抽取结果：解析 <fact> 标签，拒绝模板回显/解释。"""
    import re

    out = (out or "").strip()
    m = re.search(r"<fact>(.*?)</fact>", out, re.S)
    if m:
        fact = m.group(1).strip()
    else:
        # 无标签：拒绝疑似回显/解释的内容，只接受简短陈述
        if any(k in out for k in ("话语", "用户话语", "要求", "提取", "输出", "不要", "若", "第一人称")):
            return None
        fact = out
    fact = fact.strip().strip('"').strip("“”").strip("。.")
    if not fact or fact.lower() in _EXTRACT_EMPTY:
        return None
    if len(fact) > 100:
        return None
    return fact


class MemoryManager:
    """统一记忆入口：add / search / get_all / try_extract / backend_name。"""

    def __init__(self, cfg: Dict[str, Any], home: Path, router=None) -> None:
        self.cfg = cfg
        self.home = home
        self.router = router
        self._backend: Optional[MemoryBackend] = None

    @property
    def backend(self) -> MemoryBackend:
        if self._backend is None:
            self._backend = self._create_backend()
        return self._backend

    def _create_backend(self) -> MemoryBackend:
        mode = self.cfg.get("backend", "auto")
        if mode == "mem0" or mode == "auto":
            try:
                b = Mem0Backend(
                    persist_path=str(Path(self.home) / "memory_db"),
                    collection_name=self.cfg.get("mem0_collection", "aivyos_memory"),
                    embedder_model=self.cfg.get("mem0_embedder_model", "BAAI/bge-m3"),
                    llm_model=self.cfg.get("mem0_llm_model", "qwen2.5:7b"),
                )
                log.info("记忆后端：Mem0 + ChromaDB（文档 §4.2）")
                return b
            except Mem0Unavailable as e:
                if mode == "mem0":
                    log.warning("配置要求 mem0 但不可用：%s", e)
                else:
                    log.info("mem0 不可用，回退 simple：%s", e)
        return SimpleFileMemory(Path(self.home) / self.cfg.get("simple_path", "memory.jsonl"))

    @property
    def backend_name(self) -> str:
        return self.backend.name

    async def add(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        return await self.backend.add(text, metadata)

    async def search(self, query: str, top_k: int = 5) -> List[MemoryHit]:
        return await self.backend.search(query, top_k=top_k)

    async def get_all(self) -> List[MemoryHit]:
        return await self.backend.get_all()

    async def try_extract(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """抽取值得长期记忆的事实（A2：LLM 优先，规则回退）。返回记忆 id 或 None。"""
        if not self.cfg.get("auto_extract", True):
            return None
        backend = self.cfg.get("extract_backend", "auto")
        if backend in ("llm", "auto") and self.router is not None and self._real_llm():
            fact = await self._llm_extract(text)
            if fact:
                return await self.add(f"[LLM抽取] {fact}", metadata)
        return await self._rules_extract(text, metadata)

    def _real_llm(self) -> bool:
        try:
            return self.router._local_available() or bool(self.router._cloud_api_key())
        except Exception:
            return False

    async def _llm_extract(self, text: str) -> Optional[str]:
        from aivyos_core.models import LLMRequest, RouteDecision, RouteMode

        decision = RouteDecision(
            mode=RouteMode.LOCAL if self.router._local_available() else RouteMode.CLOUD,
            model=self.router.cfg["local"]["model"] if self.router._local_available() else self.router.cfg["cloud"]["model"],
            reason="事实抽取",
        )
        request = LLMRequest(
            messages=[
                {"role": "system", "content": _EXTRACT_PROMPT.format(text=text[:500])},
            ],
            model=decision.model,
            max_tokens=128,
            temperature=0.2,
        )
        resp = await self.router.complete(request, decision)
        if "mock" in resp.model.lower():
            return None  # 降级到 mock → 视为无真实 LLM，走规则
        return _clean_extract(resp.text)

    async def _rules_extract(self, text: str, metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        for pattern, _ in _EXTRACT_PATTERNS:
            if pattern in text:
                return await self.add(f"[自动抽取] {text.strip()}", metadata)
        return None
