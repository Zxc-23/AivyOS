"""面部认证测试（§9.2：mock 哈希比对 + insightface 缺失降级）。"""

import os
import shutil
import unittest

from aivyos_core.auth.face import FaceAuth, FaceUnavailable, InsightFaceAuth

from tests import _TMP, AivyTestCase


class TestMockFace(AivyTestCase):
    def setUp(self):
        d = os.path.join(_TMP, "face_mock")
        shutil.rmtree(d, ignore_errors=True)
        self.face = FaceAuth(d, threshold=0.6, backend="mock")

    def test_register_verify_same_image(self):
        img = b"\x89PNG fake-image-bytes-1"
        self.face.register("u1", img)
        user, score = self.face.verify(img)
        self.assertEqual(user, "u1")
        self.assertGreaterEqual(score, 0.6)

    def test_different_image_rejected(self):
        self.face.register("u1", b"image-A")
        user, _ = self.face.verify(b"image-B")
        self.assertIsNone(user)


class TestInsightFaceGuard(AivyTestCase):
    def test_missing_insightface_raises(self):
        with self.assertRaises(FaceUnavailable):
            InsightFaceAuth()

    def test_auto_falls_back_to_mock(self):
        d = os.path.join(_TMP, "face_auto")
        shutil.rmtree(d, ignore_errors=True)
        face = FaceAuth(d, backend="auto")
        self.assertEqual(face.backend_name, "mock-face")


if __name__ == "__main__":
    unittest.main()
