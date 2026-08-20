"""唤醒词检测（文档 §3.1 语音唤醒 + §9 认证前置）。

支持：
- 精确匹配：英文大小写不敏感 + 空格归一化
- 中文子串匹配：允许前后冗余字（如 "艾薇儿" 仍可匹配 "艾薇"）
- 近音字匹配：支持常见同音/近音变体（如 "哎维" ≈ "艾薇"）
- 英文边界检测：防止 "aivory" 误匹配 "aivy"

Phase 4 认证（声纹）就绪后，此处可叠加说话人验证。
"""

from __future__ import annotations

import re
from typing import List, Optional


# 常见近音字映射（用于唤醒词容错匹配）
# 基于实际 FunASR 识别错误模式构建
_HOMOPHONE_MAP = {
    "艾": ["艾", "哎", "爱", "阿", "还", "哎", "唉"],
    "薇": ["薇", "维", "微", "威", "喂", "味"],
    "贾": ["贾", "假", "价"],
    "维": ["维", "围", "唯"],
}

# 额外直接变体（不依赖单字映射的特殊情况）
_DIRECT_VARIANTS = {
    "艾薇": ["阿威", "爱威", "哎威", "还威", "艾薇", "爱薇", "艾维", "艾微", "哎维", "爱维", "哎微", "爱微"],
}


def _build_fuzzy_variants(word: str) -> List[str]:
    """构建唤醒词的近音变体。

    三层容错策略：
    1. 直接变体表（手工整理的高频 ASR 错误）
    2. 同音字笛卡尔积
    3. 单字独立匹配（每个字符独立出现即触发）

    例如 "艾薇" → ["艾薇", "阿威", "爱威", "还威", ...]
    """
    variants = {word}

    # 第一层：直接变体
    if word in _DIRECT_VARIANTS:
        variants.update(_DIRECT_VARIANTS[word])

    # 第二层：单字映射 + 笛卡尔积
    chars = list(word)
    position_options = []
    for ch in chars:
        if ch in _HOMOPHONE_MAP:
            position_options.append(_HOMOPHONE_MAP[ch])
        else:
            position_options.append([ch])

    from itertools import product
    for combo in product(*position_options):
        variants.add("".join(combo))

    return list(variants)


class WakeWordDetector:
    """唤醒词检测器。

    支持中英文唤醒词，具备近音容错和英文边界检测。
    """

    def __init__(self, words: Optional[List[str]] = None) -> None:
        raw_words = words or ["Aivy", "艾薇", "贾维斯"]
        self.words: List[str] = []
        self._word_variants: List[List[str]] = []
        self._is_chinese: List[bool] = []

        for w in raw_words:
            norm = w.lower().replace(" ", "")
            self.words.append(norm)
            # 构建近音变体
            variants = _build_fuzzy_variants(norm)
            self._word_variants.append(variants)
            # 判断是否中文（包含中文字符）
            has_chinese = any("\u4e00" <= c <= "\u9fff" for c in norm)
            self._is_chinese.append(has_chinese)

    def detect(self, text: str) -> bool:
        """检测文本是否包含唤醒词。

        三层容错策略：
        1. 完整变体匹配（精确 + 近音变体）
        2. 单字独立匹配（双字变体必须同时出现）
        3. 英文词边界匹配
        """
        norm = text.lower().replace(" ", "")
        for i, word in enumerate(self.words):
            if self._is_chinese[i]:
                # 第一层：完整变体匹配
                for variant in self._word_variants[i]:
                    if variant in norm:
                        return True

                # 第二层：单字独立匹配（容错 ASR 丢字/错字）
                if self._char_level_match(norm, word):
                    return True
            else:
                # 英文：保留原始空格进行边界匹配
                # 这样 "hello aivy" 能正确匹配
                raw_lower = text.lower()
                if self._english_match(raw_lower, word):
                    return True
                # 同时尝试无空格版本
                if self._english_match(norm, word):
                    return True
        return False

    def _char_level_match(self, text: str, word: str) -> bool:
        """单字独立匹配 — 处理 ASR 丢字场景。

        仅使用双字匹配策略：文本必须同时包含两个字符位置的变体。
        这是最可靠的容错方式，避免因单个常见汉字导致误触发。

        例如 "艾薇" 的变体池为：
          位置1: 艾/哎/爱/阿/还
          位置2: 薇/维/微/威/喂
        若文本同时包含位置1和位置2的任意字，则触发。
        """
        chars = list(word)
        if len(chars) < 2:
            return False

        pos1_chars = set(_HOMOPHONE_MAP.get(chars[0], [chars[0]]))
        pos2_chars = set(_HOMOPHONE_MAP.get(chars[1], [chars[1]]))

        has_pos1 = any(c in text for c in pos1_chars)
        has_pos2 = any(c in text for c in pos2_chars)

        # 必须两个位置的变体都出现
        # 文本长度 >= 3 以避免双字误触（如"爱维"刚好命中）
        if has_pos1 and has_pos2 and len(text) >= 3:
            return True

        return False

    def _english_match(self, text: str, word: str) -> bool:
        """英文唤醒词边界匹配，防止子串误匹配。

        使用正则确保唤醒词前后为非字母数字字符（或边界）。
        例如："aivy" 可匹配 "aivy 帮我" 但不匹配 "aivory"。
        """
        pattern = re.compile(r'(?:^|[^a-z0-9])' + re.escape(word) + r'(?:$|[^a-z0-9])')
        return bool(pattern.search(text))

    def strip(self, text: str) -> str:
        """去除文本开头的唤醒词（如 "Aivy，帮我..." → "帮我..."）。"""
        norm = text.strip()
        lower = norm.lower().replace(" ", "")

        for i, word in enumerate(self.words):
            # 尝试各种变体
            for variant in self._word_variants[i]:
                if lower.startswith(variant):
                    # 找到唤醒词在原始文本中的位置
                    orig_lower = norm.lower()
                    idx = orig_lower.find(variant)
                    if idx >= 0:
                        return norm[idx + len(variant):].lstrip("，,。！! \t").strip()

        return norm