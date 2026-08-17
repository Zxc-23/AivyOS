"""多模态融合测试（§3.4 晚期融合，T1.8）。"""

import asyncio
import unittest

from aivyos_core.multimodal import MultimodalFusion
from aivyos_core.vision.service import VisionService

from tests import AivyTestCase


class TestMultimodalFusion(AivyTestCase):
    def setUp(self):
        self.fusion = MultimodalFusion(VisionService({"ocr_backend": "mock", "understand_backend": "mock"}))

    def test_text_only(self):
        ctx = asyncio.run(self.fusion.fuse(text="你好"))
        self.assertEqual(ctx.text, "你好")
        self.assertTrue(any("文本输入" in b for b in ctx.blocks))

    def test_fuse_all_modalities(self):
        ctx = asyncio.run(self.fusion.fuse(text="看看这图", audio_text="语音内容", image=b"img"))
        joined = "\n".join(ctx.blocks)
        self.assertIn("文本输入", joined)
        self.assertIn("语音输入", joined)
        self.assertIn("视觉输入", joined)
        self.assertIn("OCR", joined)
        self.assertEqual(ctx.strategy, "late")

    def test_system_blocks_non_empty(self):
        ctx = asyncio.run(self.fusion.fuse(text="x", image=b"img"))
        blocks = ctx.system_blocks()
        self.assertTrue(blocks)
        self.assertTrue(all(isinstance(b, str) and b for b in blocks))


if __name__ == "__main__":
    unittest.main()
