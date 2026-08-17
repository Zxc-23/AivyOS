"""声纹认证测试（§9.2：注册多模板 / 余弦阈值 0.75 / 同音色识别 / 跨音色拒绝）。"""

import os
import shutil
import unittest

from aivyos_core.auth.cli import synth_voice
from aivyos_core.auth.voiceprint import (
    VoiceprintAuth,
    cosine_similarity,
    extract_embedding,
)

from tests import _TMP, AivyTestCase


def _dir(name: str) -> str:
    p = os.path.join(_TMP, name)
    shutil.rmtree(p, ignore_errors=True)
    return p


class TestEmbedding(AivyTestCase):
    def test_same_speaker_high_similarity(self):
        e1 = extract_embedding(synth_voice(1.0, duration_s=3.0))
        e2 = extract_embedding(synth_voice(1.0, duration_s=3.5))  # 同音色不同时长
        self.assertGreater(cosine_similarity(e1, e2), 0.9)

    def test_different_speakers_low_similarity(self):
        a = extract_embedding(synth_voice(1.0))
        b = extract_embedding(synth_voice(2.5))
        self.assertLess(cosine_similarity(a, b), cosine_similarity(a, a) - 0.3)

    def test_embedding_normalized(self):
        from aivyos_core.auth.voiceprint import EMBEDDING_DIM

        emb = extract_embedding(synth_voice(1.0))
        self.assertEqual(len(emb), EMBEDDING_DIM)
        norm = sum(v * v for v in emb) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)


class TestVoiceprintAuth(AivyTestCase):
    def setUp(self):
        self.dir = _dir("vp_auth")
        self.auth = VoiceprintAuth(self.dir, threshold=0.75)

    def test_register_verify_roundtrip(self):
        self.auth.register("张三", synth_voice(1.0))
        user, score = self.auth.verify(synth_voice(1.0, duration_s=3.0))
        self.assertIsNotNone(user)
        self.assertGreaterEqual(score, 0.75)
        self.assertEqual(self.auth.list_users()[0]["name"], "张三")

    def test_reject_unknown_speaker(self):
        self.auth.register("张三", synth_voice(1.0))
        user, score = self.auth.verify(synth_voice(9.0))
        self.assertIsNone(user)
        self.assertLess(score, 0.75)

    def test_multi_template_registration(self):
        self.auth.register("李四", synth_voice(2.5))
        self.auth.register("李四", synth_voice(2.5, duration_s=3.5))  # 第二模板
        self.assertEqual(self.auth.list_users()[0]["templates"], 2)
        user, _ = self.auth.verify(synth_voice(2.5, duration_s=2.0))
        self.assertIsNotNone(user)

    def test_short_sample_rejected(self):
        with self.assertRaises(ValueError):
            self.auth.register("短样本", synth_voice(1.0, duration_s=1.0))

    def test_persona_stored_per_user(self):
        self.auth.register("张三", synth_voice(1.0), persona={"tone": "casual"})
        profile = self.auth._load(self.auth.list_users()[0]["user_id"])
        self.assertEqual(profile.persona["tone"], "casual")

    def test_speechbrain_unavailable_falls_back(self):
        # speechbrain 未安装 → auto 应降级到零依赖频谱嵌入
        auth = VoiceprintAuth(_dir("vp_sb"), extractor="auto")
        self.assertEqual(auth.extractor_name, "simple-spectral")


if __name__ == "__main__":
    unittest.main()
