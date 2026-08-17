"""视觉输入测试（§3.3：OCR/理解回退 + 截图降级）。"""

import os
import unittest

from aivyos_core.vision.capture import CaptureUnavailable, ScreenCapture, load_image
from aivyos_core.vision.ocr import MockOCR, OCRUnavailable, PaddleOCREngine, create_ocr
from aivyos_core.vision.service import VisionService
from aivyos_core.vision.understand import MockUnderstand, QwenVLBackend, UnderstandUnavailable, create_understand

from tests import _TMP, AivyTestCase


class TestOCR(AivyTestCase):
    def test_mock_fixed_text(self):
        ocr = MockOCR(text="发票号码 12345")
        self.assertEqual(ocr.ocr(b"image"), "发票号码 12345")

    def test_mock_empty_image(self):
        self.assertEqual(MockOCR().ocr(b""), "")

    def test_paddleocr_missing_raises(self):
        with self.assertRaises(OCRUnavailable):
            PaddleOCREngine()

    def test_create_ocr_falls_back_to_mock(self):
        ocr = create_ocr({"ocr_backend": "auto"})
        self.assertIsInstance(ocr, MockOCR)


class TestUnderstand(AivyTestCase):
    def test_mock(self):
        u = MockUnderstand()
        self.assertIn("mock", u.describe(b"img"))

    def test_qwen_without_endpoint_raises(self):
        with self.assertRaises(OSError):  # 无端点 → urllib 连接失败
            QwenVLBackend("http://127.0.0.1:1/v1").describe(b"img")

    def test_create_understand_falls_back(self):
        u = create_understand({"understand_backend": "auto"})
        self.assertIsInstance(u, MockUnderstand)


class TestScreenCapture(AivyTestCase):
    def test_mss_missing_raises(self):
        with self.assertRaises(CaptureUnavailable):
            ScreenCapture()

    def test_load_image_roundtrip(self):
        path = os.path.join(_TMP, "test_img.bin")
        with open(path, "wb") as f:
            f.write(b"\x89PNG-fake")
        self.assertEqual(load_image(path), b"\x89PNG-fake")


class TestVisionService(AivyTestCase):
    def test_analyze_image_mock(self):
        vs = VisionService({"ocr_backend": "mock", "understand_backend": "mock"})
        r = vs.analyze_image(b"image-bytes")
        self.assertEqual(r.ocr_backend, "mock-ocr")
        self.assertEqual(r.understand_backend, "mock-vision")
        self.assertIn("OCR", r.combined_text())
        self.assertIn("视觉理解", r.combined_text())


if __name__ == "__main__":
    unittest.main()
