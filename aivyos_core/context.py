"""上下文管理器（文档 §4.4）：窗口分配、滑动窗口、压缩策略。

Week 1 实现：
- §4.4.1 Token 预算分配（system / memory / history / input / output 预留）
- §4.4.2 近期保留（原样）+ 中期摘要（朴素截断占位，Week 3 接 LLM 摘要）
- 远期归档钩子（调用记忆后端归档旧轮次）
"""

from __future__ import annotations

import logging
log = logging.getLogger(__name__)

import time
from typing import Any, Dict, List, Optional

from aivyos_core.models import ChatMessage, Role

ARCHIVE_MARKER = "[早期对话已归档至长期记忆]"


def estimate_tokens(text: str) -> int:
    """启发式 Token 估算：CJK 字符 ≈ 1 token/字，拉丁 ≈ 1 token/4 字符。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f")
    other = len(text) - cjk
    return cjk + max(0, other // 4)


class ContextManager:
    """按预算组装一次推理的 messages（对齐 §4.4.1 分配表）。"""

    def __init__(
        self,
        context_window: int = 32768,
        history_turns: int = 12,
        summarize_from_turn: int = 12,
        system_prompt_tokens: int = 2048,
        memory_tokens: int = 8192,
        max_input_tokens: int = 4096,
        output_reserve_tokens: int = 8192,
    ) -> None:
        self.context_window = context_window
        self.history_turns = history_turns
        self.summarize_from_turn = summarize_from_turn
        self.system_prompt_tokens = system_prompt_tokens
        self.memory_tokens = memory_tokens
        self.max_input_tokens = max_input_tokens
        self.output_reserve_tokens = output_reserve_tokens

    # ---- 预算分配（§4.4.1）----

    def allocate_budget(self, memory_hits_tokens: int = 0) -> Dict[str, int]:
        """返回各组成部分的 Token 预算（保证总和 ≤ 窗口）。"""
        system = min(self.system_prompt_tokens, self.context_window // 8)
        memory = min(memory_hits_tokens or self.memory_tokens, self.context_window // 4)
        output = min(self.output_reserve_tokens, self.context_window // 4)
        input_ = min(self.max_input_tokens, self.context_window // 8)
        history = max(0, self.context_window - system - memory - input_ - output)
        return {
            "system": system,
            "memory": memory,
            "history": history,
            "input": input_,
            "output": output,
            "total": system + memory + history + input_ + output,
        }

    # ---- 消息组装 ----

    def build_messages(
        self,
        persona_prompt: str,
        memory_hits: List[Dict[str, Any]],
        history: List[ChatMessage],
        current_input: str,
        archive_callback=None,
        extra_blocks: Optional[List[str]] = None,
    ) -> tuple[List[Dict[str, str]], Dict[str, Any]]:
        """组装最终 messages，返回 (messages, stats)。

        - 记忆命中注入为 system 上下文块（§4.4.1 检索记忆 8K）
        - 近期保留原样（§4.4.2），超出预算的旧轮次调用 archive_callback 归档
        - 中期摘要：朴素截断占位（Week 3 替换为 LLM 摘要）
        - extra_blocks：多模态融合上下文块（§3.4，T1.8）
        """
        budget = self.allocate_budget()
        stats: Dict[str, Any] = {"budget": budget, "archived": 0, "summarized": 0}

        # 1) system：人格 + 记忆命中 + 多模态块
        system_parts = [persona_prompt]
        if memory_hits:
            mem_block = "\n".join(
                f"- [{h.get('created_at', '')[:19]}][score={h.get('score', 0):.2f}] {h.get('text', '')}"
                for h in memory_hits
            )
            system_parts.append(f"## 检索到的长期记忆\n{mem_block}")
        if extra_blocks:
            system_parts.extend(extra_blocks)
        system_text = "\n\n".join(system_parts)
        if estimate_tokens(system_text) > budget["system"]:
            system_text = system_text[: budget["system"] * 2] + "\n…(截断)"
        messages: List[Dict[str, str]] = [{"role": Role.SYSTEM.value, "content": system_text}]

        # 2) history：近期保留 + 归档/截断
        history_budget = budget["history"]
        used = estimate_tokens(system_text)
        kept: List[ChatMessage] = []
        for msg in reversed(history):
            cost = estimate_tokens(msg.content) + 16
            if used + cost > history_budget:
                break
            kept.append(msg)
            used += cost
        kept.reverse()

        # 归档被挤出预算且可回调的旧轮次（远期归档，§4.4.2）
        archived_count = len(history) - len(kept)
        if archived_count > 0 and archive_callback is not None:
            old = history[: len(history) - len(kept)]
            try:
                archive_callback(old)
                stats["archived"] = len(old)
            except Exception as e:
                log.debug("忽略预期内异常: %s", e, exc_info=True)

        if kept:
            messages.append({"role": Role.SYSTEM.value, "content": ARCHIVE_MARKER})
            messages.extend(m.to_dict() for m in kept)

        # 3) 当前输入（超长截断）
        input_text = current_input[: self.max_input_tokens * 2]
        messages.append({"role": Role.USER.value, "content": input_text})

        stats["messages"] = len(messages)
        stats["history_kept"] = len(kept)
        stats["tokens_estimate"] = estimate_tokens("\n".join(m["content"] for m in messages))
        return messages, stats

    # ---- 会话级压缩（§4.4.2 中期摘要占位）----

    def compress_history(self, history: List[ChatMessage], max_turns: int = 12) -> List[ChatMessage]:
        """超过 max_turns 时，将最早的部分压缩为一条摘要消息（朴素实现）。"""
        if len(history) <= max_turns:
            return history
        old, recent = history[:-max_turns], history[-max_turns:]
        summary = "；".join(f"{m.role}: {m.content[:40]}" for m in old[:6])
        summary_msg = ChatMessage(
            role=Role.SYSTEM.value,
            content=f"[中期摘要（朴素占位，Week 3 升级 LLM 摘要）] {summary}",
            timestamp=time.time(),
        )
        return [summary_msg] + recent
