"""情感标签控制（文档 §6.1：CosyVoice 3 的 14 种细粒度情感标签）。

标签如 [laughter][breath][applause]…：LLM 可在回复中嵌入以控制 TTS 情感表达；
EmotionTagger 负责解析/剥离/回填（剥离后用于纯文本展示与 fallback TTS）。
"""

from __future__ import annotations

import re
from typing import List, Tuple

# §6.1 14 种细粒度情感标签（CosyVoice 3 支持集合的常用子集）
EMOTION_TAGS = [
    "laughter", "breath", "applause", "cough", "sigh", "whisper", "yawn",
    "gasp", "hum", "scream", "cry", "laugh", "sing", "groan",
]

_TAG_RE = re.compile(r"\[(laughter|breath|applause|cough|sigh|whisper|yawn|gasp|hum|scream|cry|laugh|sing|groan)\]")


class EmotionTagger:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def parse(self, text: str) -> List[str]:
        """提取文本中的情感标签（§6.1）。"""
        if not self.enabled:
            return []
        return _TAG_RE.findall(text)

    def strip(self, text: str) -> str:
        """剥离标签：纯文本展示 / fallback TTS 用。"""
        if not self.enabled:
            return text
        return _TAG_RE.sub("", text).strip()

    def enrich(self, text: str, tags: List[str]) -> str:
        """回填标签到文本开头（供 CosyVoice 3 情感表达）。"""
        if not self.enabled or not tags:
            return text
        head = "".join(f"[{t}]" for t in tags)
        return f"{head}{text}"

    def split(self, text: str) -> Tuple[List[str], str]:
        """同时返回 (标签列表, 剥离后的文本)。"""
        return self.parse(text), self.strip(text)
