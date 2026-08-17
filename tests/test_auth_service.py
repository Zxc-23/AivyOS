"""认证服务 + 语音门控集成测试（§9 全流程 + T6.7 多用户人格）。"""

import asyncio
import os
import shutil
import uuid
import unittest

from aivyos_core.auth.cli import synth_voice
from aivyos_core.auth.service import AuthService
from aivyos_core.voice.session import VoiceSession

from tests import AivyTestCase, _TMP, make_config


def auth_config(**overrides) -> dict:
    cfg = make_config()
    cfg["home"] = os.path.join(_TMP, "auth_" + uuid.uuid4().hex[:8])
    cfg["auth"]["enabled"] = True
    if overrides:
        from aivyos_core.config import deep_merge

        cfg = deep_merge(cfg, {"auth": overrides})
    return cfg


class TestAuthService(AivyTestCase):
    def test_register_and_authenticate(self):
        cfg = auth_config()
        auth = AuthService(cfg)
        r = auth.register("张三", pcm=synth_voice(1.0), persona={"tone": "casual"})
        ok = asyncio.run(auth.authenticate(pcm=synth_voice(1.0, duration_s=3.0)))
        self.assertTrue(ok.accepted)
        self.assertEqual(ok.user_id, r["user_id"])
        self.assertGreaterEqual(ok.voice_score, 0.75)
        self.assertEqual(auth.sm.state.value, "authenticated")

    def test_reject_unknown(self):
        auth = AuthService(auth_config())
        auth.register("张三", pcm=synth_voice(1.0))
        bad = asyncio.run(auth.authenticate(pcm=synth_voice(9.0)))
        self.assertFalse(bad.accepted)
        self.assertEqual(bad.reason, "声纹未匹配")
        self.assertEqual(auth.sm.state.value, "rejected")

    def test_multi_user_persona(self):
        cfg = auth_config()
        auth = AuthService(cfg)
        r1 = auth.register("张三", pcm=synth_voice(1.0), persona={"tone": "casual"})
        r2 = auth.register("李四", pcm=synth_voice(2.5), persona={"tone": "serious"})
        self.assertEqual(auth.get_user_persona(r1["user_id"]).get("tone"), "casual")
        self.assertEqual(auth.get_user_persona(r2["user_id"]).get("tone"), "serious")
        # 各自语音 → 各自用户
        ok1 = asyncio.run(auth.authenticate(pcm=synth_voice(1.0, duration_s=3.0)))
        self.assertEqual(ok1.user_id, r1["user_id"])
        ok2 = asyncio.run(auth.authenticate(pcm=synth_voice(2.5, duration_s=3.0)))
        self.assertEqual(ok2.user_id, r2["user_id"])

    def test_status(self):
        auth = AuthService(auth_config())
        st = auth.status()
        self.assertTrue(st["enabled"])
        self.assertIn("users", st)
        self.assertIn("state_machine", st)


class TestVoiceSessionAuthGate(AivyTestCase):
    def test_auth_gate_rejects_unregistered(self):
        cfg = auth_config()
        cfg["asr"]["backend"] = "mock"
        cfg["tts"]["backend"] = "mock"
        cfg["audio"]["vad_backend"] = "energy"
        cfg["audio"]["input_backend"] = "synthetic"
        session = VoiceSession(cfg)
        self.assertIsNotNone(session.auth)

        # 未注册任何用户 → 采集路径认证被拒 → 静默（reply=None）
        from tests.test_voice import FakeSource

        session.source = FakeSource()
        result = asyncio.run(session.run_turn())
        self.assertIsNotNone(result)
        self.assertIsNone(result["reply"])
        self.assertFalse(result["auth"]["accepted"])

    def test_text_override_bypasses_auth(self):
        cfg = auth_config()
        cfg["asr"]["backend"] = "mock"
        cfg["tts"]["backend"] = "mock"
        session = VoiceSession(cfg)
        result = asyncio.run(session.run_turn(text_override="你好"))
        self.assertTrue(result["reply"])
        self.assertTrue(result["auth"]["bypassed"])


if __name__ == "__main__":
    unittest.main()
