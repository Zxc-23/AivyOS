"""第一阶段端到端联调测试（§23 目标：能听、能想、能说、能记、认主、能看）。

覆盖完整链路：
  1. 语音认证 → ASR → LLM → TTS → 输出（§9 → §3.1 → §4.1 → §6.1）
  2. 视觉输入 → 多模态融合 → LLM（§3.3/§3.4）
  3. 多模态输出路由（§6.3）
  4. 记忆/MemFS 持久化（§4.2/§8.1）
"""

import asyncio
import os
import shutil
import unittest

from aivyos_core.auth.cli import synth_voice
from aivyos_core.chat.engine import ChatEngine
from aivyos_core.output import OutputChannel
from aivyos_core.voice.session import VoiceSession

from tests import AivyTestCase, FakeVoiceSource, _TMP, make_config


def e2e_config() -> dict:
    import uuid

    cfg = make_config()
    cfg["home"] = os.path.join(_TMP, "e2e_" + uuid.uuid4().hex[:8])
    shutil.rmtree(cfg["home"], ignore_errors=True)
    cfg["auth"]["enabled"] = True
    cfg["asr"]["backend"] = "mock"
    cfg["tts"]["backend"] = "mock"
    cfg["audio"]["vad_backend"] = "energy"
    cfg["audio"]["input_backend"] = "synthetic"
    return cfg


class TestPhase1E2E(AivyTestCase):
    def test_voice_auth_chat_tts_chain(self):
        """能听/能认主/能想/能说：语音采集→认证→ASR→LLM→TTS。"""
        cfg = e2e_config()
        engine = ChatEngine(cfg)
        session = VoiceSession(cfg, engine=engine)

        # 注册主人（声纹）
        session.auth.register("主人", pcm=synth_voice(1.0), persona={"tone": "witty"})

        # 主人语音 → 全链路
        session.source = FakeVoiceSource(synth_voice(1.0, duration_s=3.0))
        result = asyncio.run(session.run_turn())
        self.assertIsNotNone(result)
        self.assertTrue(result["auth"]["accepted"], f"认证应通过: {result['auth']}")
        self.assertTrue(result["reply"], "应得到 LLM 回复")
        self.assertEqual(result["tts_backend"], "mock-tts")
        self.assertGreater(result["wav_len"], 0)
        self.assertEqual(session.current_user, session.auth.voice.list_users()[0]["user_id"])

        # 陌生人语音 → 静默拒绝（不暴露系统存在）
        session2 = VoiceSession(cfg, engine=ChatEngine(cfg))
        session2.source = FakeVoiceSource(synth_voice(9.0, duration_s=3.0))
        rejected = asyncio.run(session2.run_turn())
        self.assertIsNone(rejected["reply"])
        self.assertFalse(rejected["auth"]["accepted"])

    def test_vision_fusion_chat_chain(self):
        """能看：视觉输入 → 多模态融合（§3.4）→ LLM。"""
        cfg = make_config()
        # 测试不依赖真实视觉模型（本地/云端探测一律 mock，保证离线可跑）
        cfg["vision"]["understand_backend"] = "mock"
        cfg["vision"]["ocr_backend"] = "mock"
        engine = ChatEngine(cfg)
        reply = asyncio.run(engine.send_multimodal(text="帮我看看这张图", image=b"fake-image", session_id=None))
        self.assertTrue(reply.text)
        # 融合块已生成（OCR + 视觉理解均为 mock 回退）
        ctx = asyncio.run(engine.fusion.fuse(text="x", image=b"img"))
        self.assertTrue(any("视觉输入" in b for b in ctx.blocks))

    def test_chat_send_with_image_b64(self):
        """chat.send 带 image_b64 → 走多模态链路，返回 vision_used。"""
        from aivyos_core.server_entry import build_server

        import base64

        cfg = make_config()
        cfg["vision"]["understand_backend"] = "mock"
        cfg["vision"]["ocr_backend"] = "mock"
        engine = ChatEngine(cfg)
        server = build_server(engine, cfg)
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["chat.send"]({
            "text": "看看这张图",
            "session_id": None,
            "image_b64": base64.b64encode(b"fake-image-bytes").decode(),
        }))
        self.assertTrue(result["text"])
        self.assertTrue(result.get("vision_used"))

    def test_chat_send_with_image_path(self):
        """chat.send 带 image_path → 后端读文件 → 多模态。"""
        import base64
        import os

        from aivyos_core.server_entry import build_server

        cfg = make_config()
        cfg["vision"]["understand_backend"] = "mock"
        cfg["vision"]["ocr_backend"] = "mock"
        engine = ChatEngine(cfg)
        server = build_server(engine, cfg)
        handlers = {m: h for m, h in server._handlers.items()}
        img_path = os.path.join(_TMP, "chat_img.png")
        with open(img_path, "wb") as f:
            f.write(b"\x89PNG-fake")
        try:
            result = asyncio.run(handlers["chat.send"]({
                "text": "看看这张图",
                "session_id": None,
                "image_path": img_path,
            }))
            self.assertTrue(result["text"])
            self.assertTrue(result.get("vision_used"))
        finally:
            os.remove(img_path)

    def test_chat_send_without_image_unchanged(self):
        """chat.send 无图片参数 → 普通链路，vision_used=False。"""
        from aivyos_core.server_entry import build_server

        cfg = make_config()
        engine = ChatEngine(cfg)
        server = build_server(engine, cfg)
        handlers = {m: h for m, h in server._handlers.items()}
        result = asyncio.run(handlers["chat.send"]({"text": "你好", "session_id": None}))
        self.assertTrue(result["text"])
        self.assertFalse(result.get("vision_used", False))

    def test_output_routing_chain(self):
        """输出路由（§6.3）：文本/语音/通知/文件 四通道。"""
        cfg = make_config()
        engine = ChatEngine(cfg)
        router = engine.output
        # 语音通道
        plan = router.decide("语音回答", modality_hint="voice")
        self.assertEqual(plan.channel, OutputChannel.VOICE)
        # 代码 → 文件
        plan2 = router.decide("```\nprint(1)\n```")
        self.assertEqual(plan2.channel, OutputChannel.FILE)
        res = router.deliver(plan2)
        self.assertTrue(os.path.exists(res["path"]))
        os.remove(res["path"])

    def test_memory_persists_through_chain(self):
        """能记：对话 → 记忆/MemFS 持久化，重启可检索。"""
        cfg = e2e_config()
        engine1 = ChatEngine(cfg)
        asyncio.run(engine1.send("记住我叫小明"))
        engine2 = ChatEngine(cfg)  # 重启
        hits = asyncio.run(engine2.memory.search("小明"))
        self.assertTrue(any("小明" in h.text for h in hits))
        self.assertIn("小明", engine2.memfs.read("facts.md"))


if __name__ == "__main__":
    unittest.main()
