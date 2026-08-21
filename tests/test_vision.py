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

    def test_probe_returns_real_model_id(self):
        """探测返回实际匹配的模型 id（配置名命中量化变体）。"""
        from unittest.mock import MagicMock, patch

        from aivyos_core.vision.understand import _probe_vision_model

        fake_resp = MagicMock()
        fake_resp.read.return_value = (
            b'{"data": [{"id": "qwen2.5vl:7b-q4_K_M"}, {"id": "qwen2.5:3b"}]}'
        )
        fake_cm = MagicMock()
        fake_cm.__enter__.return_value = fake_resp
        with patch("urllib.request.urlopen", return_value=fake_cm) as mock_urlopen:
            real = _probe_vision_model("http://127.0.0.1:11434/v1", "qwen2.5vl:7b")
            self.assertEqual(real, "qwen2.5vl:7b-q4_K_M")

    def test_probe_exact_match(self):
        from unittest.mock import MagicMock, patch

        from aivyos_core.vision.understand import _probe_vision_model

        fake_resp = MagicMock()
        fake_resp.read.return_value = b'{"data": [{"id": "qwen2.5:3b"}]}'
        fake_cm = MagicMock()
        fake_cm.__enter__.return_value = fake_resp
        with patch("urllib.request.urlopen", return_value=fake_cm):
            self.assertEqual(_probe_vision_model("http://x/v1", "qwen2.5:3b"), "qwen2.5:3b")

    def test_probe_no_match_returns_none(self):
        from unittest.mock import MagicMock, patch

        from aivyos_core.vision.understand import _probe_vision_model

        fake_resp = MagicMock()
        fake_resp.read.return_value = b'{"data": [{"id": "qwen2.5:0.5b"}]}'
        fake_cm = MagicMock()
        fake_cm.__enter__.return_value = fake_resp
        with patch("urllib.request.urlopen", return_value=fake_cm):
            self.assertIsNone(_probe_vision_model("http://x/v1", "qwen2.5vl:7b"))

    def test_probe_connection_error_returns_none(self):
        from aivyos_core.vision.understand import _probe_vision_model

        self.assertIsNone(_probe_vision_model("http://127.0.0.1:1/v1", "qwen2.5vl:7b"))

    def test_dynamic_load_release(self):
        """动态加载/释放：ensure_loaded 触发加载请求，release 发 keep_alive=0。"""
        from unittest.mock import patch

        b = QwenVLBackend("http://127.0.0.1:11434/v1", model="qwen2.5vl:7b-q4_K_M")
        self.assertEqual(b._ollama_base, "http://127.0.0.1:11434")
        with patch.object(b, "_ollama_request", return_value=True) as mock_req:
            b.ensure_loaded()
            body = mock_req.call_args[0][0]
            self.assertEqual(body["model"], "qwen2.5vl:7b-q4_K_M")
            self.assertGreater(body["keep_alive"], 0)
            b.release()
            body2 = mock_req.call_args[0][0]
            self.assertEqual(body2["keep_alive"], 0)

    def test_dynamic_load_release_non_ollama(self):
        """非 Ollama 端点（无 11434）→ 加载管理静默跳过。"""
        b = QwenVLBackend("https://api.example.com/v1", model="gpt-4o")
        self.assertIsNone(b._ollama_base)
        b.ensure_loaded()  # 不抛异常
        b.release()

    def test_create_understand_uses_real_id(self):
        """create_understand 用探测到的真实 id 构建后端。"""
        from unittest.mock import patch

        with patch("aivyos_core.vision.understand._probe_vision_model", return_value="qwen2.5vl:7b-q4_K_M"):
            u = create_understand({
                "understand_backend": "auto",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen2.5vl:7b",
                "keep_alive_s": 600,
                "idle_unload_s": 300,
                "load_timeout_s": 300,
            })
        self.assertIsInstance(u, QwenVLBackend)
        self.assertEqual(u.model, "qwen2.5vl:7b-q4_K_M")


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
