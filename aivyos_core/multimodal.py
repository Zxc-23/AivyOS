"""多模态融合（文档 §3.4 晚期融合 Late Fusion）。

流程：各模态独立预处理 → 时间戳对齐 → 统一编码拼接 → 送入 LLM。
T1.8：语音（ASR 文本）+ 视觉（OCR/描述）+ 文本 → 结构化上下文块。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from aivyos_core.vision.service import VisionService


@dataclass
class MultimodalInput:
    text: str = ""
    audio_text: str = ""
    image: Optional[bytes] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class FusedContext:
    text: str
    blocks: List[str] = field(default_factory=list)
    strategy: str = "late"

    def system_blocks(self) -> List[str]:
        """生成可注入 System Prompt 的上下文块（§3.4 统一编码）。"""
        blocks = []
        for b in self.blocks:
            if b:
                blocks.append(b)
        return blocks


class MultimodalFusion:
    """多模态晚期融合（§3.4）：文本/语音文本/视觉 → 统一上下文。"""

    def __init__(self, vision: VisionService, strategy: str = "late", max_vision_tokens: int = 2048) -> None:
        self.vision = vision
        self.strategy = strategy
        self.max_vision_tokens = max_vision_tokens

    async def fuse(self, text: str = "", audio_text: str = "", image: Optional[bytes] = None) -> FusedContext:
        """各模态独立预处理后统一编码（§3.4 步骤 1-3）。"""
        blocks: List[str] = []

        if text:
            blocks.append(f"## 文本输入\n{text}")
        if audio_text:
            blocks.append(f"## 语音输入（ASR）\n{audio_text}")
        if image is not None:
            vision_result = self.vision.analyze_image(image)
            combined = vision_result.combined_text()
            if combined:
                combined = combined[: self.max_vision_tokens * 2]
                blocks.append(f"## 视觉输入（{vision_result.ocr_backend} / {vision_result.understand_backend}）\n{combined}")

        main_text = text or audio_text or ""
        return FusedContext(text=main_text, blocks=blocks, strategy=self.strategy)

    def status(self) -> Dict[str, Any]:
        return {"strategy": self.strategy, "vision": self.vision.status()}
