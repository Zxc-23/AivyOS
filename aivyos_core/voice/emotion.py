"""Phase 2 情感标签注入器（报告 §4.4.3）。

为 TTS 引擎提供情感控制，通过在文本中注入 CosyVoice 3 风格的情感标签，
驱动 TTS 引擎生成带有情感色彩的语音。

支持的情感标签：
    happy, sad, angry, surprised, whisper, laugh, cry, breath, neutral

用法：
    ctrl = EmotionController()
    text = ctrl.inject("今天天气真好", emotion="happy")
    # → "今天天气真好 [laughter]"
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# CosyVoice 3 情感标签映射
# 参考: CosyVoice 3 Instruction Control 规范
EMOTION_TAG_MAP: Dict[str, str] = {
    "happy": "[laughter]",
    "laugh": "[laughter]",
    "sad": "[cry]",
    "cry": "[cry]",
    "angry": "[angry]",
    "surprised": "[surprised]",
    "whisper": "[whisper]",
    "breath": "[breath]",
    "neutral": "",
}

# 情感关键词 → 情感标签自动推断
EMOTION_KEYWORDS: Dict[str, List[str]] = {
    "happy": ["开心", "高兴", "快乐", "哈哈", "笑", "有趣", "好玩", "太棒了", "nice", "happy", "great"],
    "sad": ["难过", "伤心", "遗憾", "可惜", "遗憾", "哭", "泪", "sad", "sorry", "unfortunately"],
    "angry": ["生气", "愤怒", "讨厌", "烦", "气", "恨", "angry", "hate", "damn"],
    "surprised": ["惊讶", "吃惊", "没想到", "居然", "竟然", "哇", "啊", "wow", "surprise"],
    "whisper": ["小声", "悄悄", "耳语", "秘密", "confidential", "quietly"],
}


class EmotionController:
    """情感标签注入器。

    功能：
    1. 手动注入：inject(text, emotion="happy")
    2. 自动推断：detect(text) → 从文本关键词推断情感
    3. 批量处理：process_batch([...])
    4. 标签清理：strip_tags(text) → 移除所有情感标签

    支持 CosyVoice 3 / GPT-SoVITS 等引擎的情感标签格式。
    """

    def __init__(self, enabled: bool = True) -> None:
        """初始化情感控制器。

        Args:
            enabled: 是否启用心感注入（可通过配置关闭）。
        """
        self._enabled = enabled
        self._tag_pattern = re.compile(r'\[(laughter|cry|angry|surprised|whisper|breath)\]')

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        """启用心感控制。"""
        self._enabled = value

    def inject(self, text: str, emotion: str = "neutral") -> str:
        """在文本中注入情感标签。

        Args:
            text: 原始文本。
            emotion: 情感标签名（happy/sad/angry/surprised/whisper/laugh/cry/breath/neutral）。

        Returns:
            注入情感标签后的文本。
        """
        if not self._enabled or emotion == "neutral":
            return text

        tag = EMOTION_TAG_MAP.get(emotion.lower(), "")
        if not tag:
            log.debug("未知情感标签: %s", emotion)
            return text

        # 移除已存在的情感标签，避免重复
        clean_text = self.strip_tags(text)
        return f"{clean_text} {tag}".strip()

    def detect(self, text: str) -> str:
        """从文本关键词自动推断情感。

        Args:
            text: 输入文本。

        Returns:
            推断的情感标签名。
        """
        text_lower = text.lower()
        scores: Dict[str, int] = {}

        for emotion, keywords in EMOTION_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scores[emotion] = score

        if not scores:
            return "neutral"

        return max(scores, key=scores.get)

    def auto_inject(self, text: str, fallback: str = "neutral") -> str:
        """自动推断情感并注入标签。

        Args:
            text: 输入文本。
            fallback: 无关键词时使用的默认情感。

        Returns:
            注入情感标签后的文本。
        """
        emotion = self.detect(text)
        if emotion == "neutral":
            emotion = fallback
        return self.inject(text, emotion)

    def process_batch(self, texts: List[str], auto_detect: bool = True) -> List[str]:
        """批量处理文本列表。

        Args:
            texts: 文本列表。
            auto_detect: 是否自动推断情感。

        Returns:
            处理后的文本列表。
        """
        if not self._enabled:
            return texts
        if auto_detect:
            return [self.auto_inject(t) for t in texts]
        return texts

    def strip_tags(self, text: str) -> str:
        """移除文本中的所有情感标签。

        Args:
            text: 可能包含情感标签的文本。

        Returns:
            清理后的文本。
        """
        return self._tag_pattern.sub("", text).strip()

    def has_tag(self, text: str) -> bool:
        """检查文本是否包含情感标签。

        Args:
            text: 输入文本。

        Returns:
            是否包含情感标签。
        """
        return bool(self._tag_pattern.search(text))

    def get_supported_emotions(self) -> List[str]:
        """获取所有支持的情感标签列表。

        Returns:
            情感标签名列表。
        """
        return list(EMOTION_TAG_MAP.keys())

    def stats(self) -> Dict[str, str]:
        """获取映射表统计。"""
        return {
            "supported_emotions": str(len(EMOTION_TAG_MAP)),
            "detect_keywords": str(sum(len(kws) for kws in EMOTION_KEYWORDS.values())),
            "enabled": str(self._enabled),
        }