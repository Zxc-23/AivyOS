"""Mock LLM — 零依赖回退后端。

未安装/未配置任何真实模型时保证对话链路可运行、可测试、可演示。
回复规则化且明确标注 mock，不伪装真实推理。
"""

from __future__ import annotations

import time

from aivyos_core.llm.base import LLMBackend
from aivyos_core.models import LLMRequest, LLMResponse


class MockLLM(LLMBackend):
    """规则化 mock：识别常见意图并给出结构化回复。"""

    name = "mock-echo"

    def __init__(self, model: str = "mock-echo") -> None:
        self.model = model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        user_text = next(
            (m["content"] for m in reversed(request.messages) if m["role"] == "user"),
            "",
        )
        text = self._reply(user_text)
        latency_ms = (time.perf_counter() - start) * 1000
        return LLMResponse(
            text=text,
            model=self.model,
            latency_ms=latency_ms,
            usage={"prompt_tokens": self._est_tokens(request.messages), "completion_tokens": self._est_tokens(text)},
        )

    # ---- 内部 ----

    @staticmethod
    def _est_tokens(text: str | list) -> int:
        if isinstance(text, list):
            return sum(len(m.get("content", "")) for m in text) // 2
        return len(text) // 2

    def _reply(self, user_text: str) -> str:
        t = user_text.strip().lower()
        if not t:
            return "（mock）请说点什么，例如：你好 / 今天天气 / 写一个计算器。"
        if any(k in t for k in ("你好", "hi", "hello", "在吗")):
            return "（mock）您好，我是 Aivy，您的私人助理。当前处于 mock 模式：配置本地或云端模型后即可获得真实回复。"
        if any(k in t for k in ("天气", "气温", "下雨")):
            return "（mock）天气查询需要启用 search 工具或接入天气 API（Phase 2 能力）。当前无法提供实时数据。"
        if any(k in t for k in ("代码", "写个", "实现", "函数", "脚本", "计算器")):
            return (
                "（mock）代码生成需启用 Cline SDK 链路（Phase 2，文档 §10）。\n"
                "当前 mock 模式无法生成真实代码，但您可以先体验对话框架。"
            )
        if any(k in t for k in ("记住", "我叫", "我喜欢", "别忘了")):
            return "（mock）已调用记忆接口，这条信息将被保存（记忆链路见 §4.2）。重启后仍可检索。"
        if any(k in t for k in ("你是谁", "介绍")):
            return "（mock）我是 AivyOS —— 本地优先的私人 AI 伴侣系统（文档编号 AIVY-TDD-2026-001 V2.1）。"
        # 默认回复：回显 + 提示
        return f"（mock）收到：{user_text.strip()[:80]}。配置 `AIVYOS_LLM_MODE=local` 并启动 Ollama 后切换到真实模型。"
