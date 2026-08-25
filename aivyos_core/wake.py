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
import time
from typing import List, Optional


# 常见近音字映射（用于唤醒词容错匹配）
# 基于实际 FunASR 识别错误模式构建
_HOMOPHONE_MAP = {
    "艾": ["艾", "哎", "爱", "阿", "还", "哎", "唉"],
    "薇": ["薇", "维", "微", "威", "喂", "味"],
    "贾": ["贾", "假", "价", "加", "嘉", "甲"],
    "维": ["维", "围", "唯"],
    "斯": ["斯", "丝", "思", "司", "私"],
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
    """唤醒词检测器类。

    功能：支持中英文唤醒词检测，具备近音容错、英文边界检测和 1 秒同文本去重能力。
    参数：无（实例化时通过 __init__ 传入 words）。
    返回：无。
    异常：无。
    """

    def __init__(self, words: Optional[List[str]] = None) -> None:
        """初始化唤醒词检测器。

        功能：构建唤醒词变体池，初始化去重状态字段。
        参数：
            words: 自定义唤醒词列表，默认为 ["Aivy", "艾薇", "贾维斯"]。
        返回：无。
        异常：无。
        """
        raw_words = words or ["Aivy", "艾薇", "贾维斯"]
        self.words: List[str] = []
        self._word_variants: List[List[str]] = []
        self._is_chinese: List[bool] = []
        self._last_trigger_ts: float = 0.0
        self._last_trigger_norm: str = ""

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

        功能：三层容错策略匹配唤醒词，并做 1 秒同文本去重（防抖动）。
        参数：
            text: 待检测的原始文本字符串。
        返回：
            bool: True=命中唤醒词且通过去重检查；False=未命中或同文本 1 秒内重复。
        异常：无。
        三层容错策略：
        1. 完整变体匹配（精确 + 近音变体）
        2. 单字独立匹配（双字变体必须同时出现）
        3. 英文词边界匹配
        """
        norm = text.lower().replace(" ", "")
        hit = False
        for i, word in enumerate(self.words):
            if self._is_chinese[i]:
                for variant in self._word_variants[i]:
                    if variant in norm:
                        hit = True
                        break
                if not hit and self._char_level_match(norm, word):
                    hit = True
            else:
                raw_lower = text.lower()
                if self._english_match(raw_lower, word):
                    hit = True
                if not hit and self._english_match(norm, word):
                    hit = True
            if hit:
                break
        if not hit:
            return False
        norm_dedup = text.lower().replace(" ", "")
        if norm_dedup == self._last_trigger_norm and (time.time() - self._last_trigger_ts) < 1.0:
            return False
        self._last_trigger_norm = norm_dedup
        self._last_trigger_ts = time.time()
        return True

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
        """去除文本开头的唤醒词前缀。

        功能：匹配开头的唤醒词（含变体）并剔除，返回用户真正的指令内容。
        参数：
            text: 原始文本，如 "Aivy，帮我查天气"。
        返回：
            str: 去除唤醒词后的干净文本，如 "帮我查天气"；未命中唤醒词则返回原文本。
        异常：无。
        """
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