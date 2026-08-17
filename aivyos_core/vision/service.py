"""视觉服务编排（文档 §3.3）：截图/图像 → OCR + 图像理解 → 统一视觉文本块。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from aivyos_core.vision.capture import CaptureUnavailable, ScreenCapture, load_image
from aivyos_core.vision.ocr import create_ocr
from aivyos_core.vision.understand import create_understand

log = logging.getLogger(__name__)


@dataclass
class VisionResult:
    image: Optional[bytes] = None
    ocr_text: str = ""
    description: str = ""
    source: str = ""
    ocr_backend: str = ""
    understand_backend: str = ""

    def combined_text(self) -> str:
        """OCR 与描述拼接（供多模态融合注入上下文，§3.4 统一编码）。"""
        parts = [p for p in (self.ocr_text, self.description) if p]
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "ocr_backend": self.ocr_backend,
            "understand_backend": self.understand_backend,
            "ocr_text": self.ocr_text[:200],
            "description": self.description[:200],
        }


class VisionService:
    """视觉输入统一入口：capture_screen / analyze_image。"""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg
        self.ocr = create_ocr(cfg)
        self.understand = create_understand(cfg)
        self._screen: Optional[ScreenCapture] = None

    @property
    def screen(self) -> ScreenCapture:
        if self._screen is None:
            if self.cfg.get("screenshot_backend") == "none":
                raise CaptureUnavailable("截图采集已禁用（screenshot_backend=none）")
            self._screen = ScreenCapture()
        return self._screen

    def capture_screen(self, region=None) -> VisionResult:
        """截图 → OCR + 理解（§3.3 屏幕捕获）。"""
        image = self.screen.capture(region)
        return self.analyze_image(image, source="screen")

    def analyze_image(self, image: bytes, source: str = "file") -> VisionResult:
        """图像字节 → OCR + 理解。"""
        ocr_text = self.ocr.ocr(image)
        description = self.understand.describe(image)
        return VisionResult(
            image=image,
            ocr_text=ocr_text,
            description=description,
            source=source,
            ocr_backend=self.ocr.name,
            understand_backend=self.understand.name,
        )

    def status(self) -> Dict[str, Any]:
        return {"ocr": self.ocr.name, "understand": self.understand.name}
