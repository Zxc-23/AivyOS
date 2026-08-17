"""对话摘要（文档 §4.4.2 中期摘要：LLM 生成，朴素截断回退）。

- LLMSummarizer：真实 LLM 后端（本地/云端）可用时用 LLM 生成摘要
- naive_summary：零依赖朴素回退（旧轮次拼接截断）
- 自动检测：路由到 mock（无真实后端）→ 朴素回退，避免 mock 罐头文本冒充摘要
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from aivyos_core.llm.router import ModelRouter
from aivyos_core.models import ChatMessage, LLMRequest, RouteDecision, RouteMode

log = logging.getLogger(__name__)

_SUMMARY_PROMPT = """请将以下对话压缩为一段简洁摘要（中文，不超过 120 字），
保留：关键事实、用户偏好、待办事项、当前上下文。不要添加原文没有的信息。

对话：
{transcript}
"""


def naive_summary(messages: List[ChatMessage], max_chars: int = 400) -> str:
    """零依赖朴素摘要：拼接最近轮次并截断（回退实现）。"""
    lines = [f"{m.role}: {m.content}" for m in messages[-6:]]
    text = "；".join(lines)
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


class LLMSummarizer:
    """LLM 摘要（真实后端可用时）+ 朴素回退。"""

    def __init__(self, router: ModelRouter, backend: str = "auto") -> None:
        self.router = router
        self.backend = backend

    def _real_available(self) -> bool:
        if self.backend == "naive":
            return False
        try:
            return self.router._local_available() or bool(self.router._cloud_api_key())
        except Exception:
            return False

    async def summarize(self, messages: List[ChatMessage]) -> str:
        """生成摘要；真实 LLM 不可用/失败 → 朴素回退。"""
        transcript = "\n".join(f"{m.role}: {m.content}" for m in messages)
        if not transcript.strip():
            return ""
        if self._real_available():
            try:
                text = await self._llm_summarize(transcript)
                if text and "mock" not in text.lower():
                    return text
                log.info("LLM 摘要不可用/疑似降级，使用朴素摘要")
            except Exception as e:
                log.warning("LLM 摘要失败，使用朴素摘要: %s", e)
        return naive_summary(messages)

    async def _llm_summarize(self, transcript: str) -> str:
        decision = RouteDecision(
            mode=RouteMode.LOCAL if self.router._local_available() else RouteMode.CLOUD,
            model=self.router.cfg["local"]["model"] if self.router._local_available() else self.router.cfg["cloud"]["model"],
            reason="摘要任务",
        )
        request = LLMRequest(
            messages=[{"role": "system", "content": _SUMMARY_PROMPT.format(transcript=transcript[:4000])}],
            model=decision.model,
            max_tokens=256,
            temperature=0.3,
        )
        resp = await self.router.complete(request, decision)
        return resp.text.strip()
