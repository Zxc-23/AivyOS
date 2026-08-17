"""OCR 文字识别（文档 §3.3：PaddleOCR PP-OCRv4 可选 + mock 回退）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class OCRUnavailable(RuntimeError):
    pass


class OCRBackend(ABC):
    name: str = "base"

    @abstractmethod
    def ocr(self, image: bytes) -> str:
        """图像字节 → 识别文本。"""
        raise NotImplementedError


class MockOCR(OCRBackend):
    """mock 回退：不伪装识别，返回可配置文本（默认占位）。"""

    name = "mock-ocr"

    def __init__(self, text: str | None = None) -> None:
        self._fixed = text

    def ocr(self, image: bytes) -> str:
        if not image:
            return ""
        if self._fixed is not None:
            return self._fixed
        return "（mock OCR）图片文字识别占位，接入 PaddleOCR 后返回真实文本"


class PaddleOCREngine(OCRBackend):
    """PaddleOCR PP-OCRv4（可选依赖）。"""

    name = "paddleocr-ppocrv4"

    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as e:
            raise OCRUnavailable(
                "paddleocr 未安装：pip install paddleocr paddlepaddle（见 requirements-ml.txt）。"
                "已降级到 mock OCR。"
            ) from e
        self.engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)

    def ocr(self, image: bytes) -> str:
        import io

        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore

        img = Image.open(io.BytesIO(image))
        result = self.engine.ocr(np.array(img), cls=True)
        lines = []
        for page in result or []:
            for item in page or []:
                lines.append(item[1][0])
        return "\n".join(lines)


def create_ocr(cfg: Dict[str, Any]) -> OCRBackend:
    backend = cfg.get("ocr_backend", "auto")
    if backend == "mock":
        return MockOCR()
    if backend in ("paddleocr", "auto"):
        try:
            return PaddleOCREngine()
        except OCRUnavailable:
            return MockOCR()
    return MockOCR()
