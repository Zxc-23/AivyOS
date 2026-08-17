"""视觉输入（文档 §3.3：屏幕捕获 / OCR / 图像理解，全部可选依赖 + 回退）。"""

from aivyos_core.vision.capture import CaptureUnavailable, ScreenCapture, load_image
from aivyos_core.vision.ocr import MockOCR, OCRBackend, OCRUnavailable, PaddleOCREngine, create_ocr
from aivyos_core.vision.service import VisionResult, VisionService
from aivyos_core.vision.understand import (
    MockUnderstand,
    QwenVLBackend,
    UnderstandBackend,
    UnderstandUnavailable,
    create_understand,
)

__all__ = [
    "CaptureUnavailable", "ScreenCapture", "load_image",
    "OCRBackend", "MockOCR", "PaddleOCREngine", "OCRUnavailable", "create_ocr",
    "UnderstandBackend", "MockUnderstand", "QwenVLBackend", "UnderstandUnavailable", "create_understand",
    "VisionService", "VisionResult",
]
