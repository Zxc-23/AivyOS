"""唤醒词检测（文档 §3.1 语音唤醒 + §9 认证前置）。

简单关键词检测：ASR 结果文本中包含任一唤醒词即命中。
Phase 4 认证（声纹）就绪后，此处可叠加说话人验证。
"""

from __future__ import annotations

from typing import List


class WakeWordDetector:
    def __init__(self, words: List[str] | None = None) -> None:
        # 归一化：小写 + 去空格，支持中英文唤醒词
        self.words = [w.lower().replace(" ", "") for w in (words or ["Aivy", "艾维", "贾维斯"])]

    def detect(self, text: str) -> bool:
        norm = text.lower().replace(" ", "")
        return any(w in norm for w in self.words)

    def strip(self, text: str) -> str:
        """去除文本开头的唤醒词（如 "Aivy，帮我..." → "帮我..."）。"""
        norm = text.strip()
        for w in self.words:
            lower = norm.lower()
            if lower.startswith(w):
                return norm[len(w) :].lstrip("，,。！! ").strip()
        return norm
