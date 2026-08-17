"""语音会话编排（文档 §3.1 → §4.1 → §6.1 全链路）。

采集 → VAD 端点检测 → ASR → 唤醒词 → LLM 对话 → TTS → 播放。
全部组件优雅降级：无麦克风/无模型时自动回退到合成音源 + 规则 ASR + 占位 TTS，
保证链路在任何环境下可运行、可测试、可演示。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from aivyos_core.asr.manager import create_asr
from aivyos_core.audio.sink import create_sink
from aivyos_core.audio.source import create_source
from aivyos_core.audio.vad import create_vad
from aivyos_core.auth.service import AuthService
from aivyos_core.chat.engine import ChatEngine
from aivyos_core.config import load_config
from aivyos_core.tts.manager import create_tts
from aivyos_core.wake import WakeWordDetector

log = logging.getLogger(__name__)


class VoiceSession:
    """一轮语音对话的编排器（§3.1 → §9 认证 → §4.1 → §6.1）。"""

    def __init__(self, config: Dict[str, Any], engine: Optional[ChatEngine] = None) -> None:
        self.config = config
        self.engine = engine or ChatEngine(config)
        self.asr = create_asr(config.get("asr", {}))
        self.tts = create_tts(config.get("tts", {}))

        audio_cfg = config.get("audio", {})
        self.vad = create_vad(audio_cfg)  # auto：Silero 优先，缺失降级能量 VAD
        self.source = create_source(audio_cfg)
        self.sink = create_sink({**config.get("tts", {}), "sample_rate": self.tts.sample_rate})

        voice_cfg = config.get("voice", {})
        self.wake = WakeWordDetector(voice_cfg.get("wake_words"))
        self.wake_required = bool(voice_cfg.get("wake_required", False))
        self.silence_timeout_s = float(voice_cfg.get("silence_timeout_s", 3.0))
        self.max_turn_s = float(voice_cfg.get("max_turn_s", 20.0))

        # Week 4：专属认证门控（§9）
        self.auth = AuthService(config) if config.get("auth", {}).get("enabled", False) else None
        self.current_user: Optional[str] = None

    def status(self) -> Dict[str, Any]:
        st = {
            "asr": self.asr.name,
            "tts": self.tts.name,
            "vad": type(self.vad).__name__,
            "source": type(self.source).__name__,
            "sink": type(self.sink).__name__,
            "wake_required": self.wake_required,
            "wake_words": self.wake.words,
            "llm_route_mode": self.config["llm"].get("mode", "auto"),
            "auth_enabled": self.auth is not None,
        }
        if self.auth is not None:
            st["auth_state"] = self.auth.sm.state.value
            st["current_user"] = self.current_user
        return st

    # ---- 一轮对话 ----

    async def run_turn(self, text_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """执行一轮语音对话，返回 {text, reply, wav_len, latency_ms, ...} 或 None。

        text_override：跳过真实音频链路（测试/文本模拟模式）。
        认证门控（§9）：真实音频路径下未通过认证 → 静默拒绝（不暴露系统存在）。
        """
        start = time.perf_counter()

        if text_override is not None:
            transcript = text_override
            asr_backend = "text-override"
            auth_result = {"bypassed": True, "reason": "文本模拟模式"}
        else:
            pcm = await self._capture_utterance()
            if not pcm:
                return None
            # 专属认证（§9.1：声纹比对 → 活体 → 面部可选）
            if self.auth is not None:
                auth_result = (await self.auth.authenticate(pcm=pcm)).to_dict()
                if not auth_result["accepted"]:
                    log.info("认证未通过，静默忽略（%s）", auth_result.get("reason", ""))
                    return {"text": "", "reply": None, "auth": auth_result, "wake": False}
                self.current_user = auth_result["user_id"]
                # T6.7：应用该用户的人格配置
                persona = self.auth.get_user_persona(self.current_user)
                for k, v in persona.items():
                    self.engine.persona.update(k, v)
            else:
                auth_result = {"bypassed": True, "reason": "认证未启用"}
            result = self.asr.transcribe(pcm)
            transcript = result.text
            asr_backend = result.backend

        # 唤醒词门控
        if self.wake_required and not self.wake.detect(transcript):
            log.info("唤醒词未命中: %r", transcript[:30])
            return {"text": transcript, "reply": None, "wake": False, "auth": auth_result}

        clean = self.wake.strip(transcript) if self.wake_required else transcript
        if not clean:
            return None

        # LLM 对话
        reply = await self.engine.send(clean)
        # TTS + 输出
        audio = self.tts.synthesize(reply.text)
        self.sink.play(audio.pcm)

        return {
            "text": transcript,
            "text_clean": clean,
            "reply": reply.text,
            "model": reply.model,
            "route": reply.route.to_dict(),
            "asr_backend": asr_backend,
            "tts_backend": audio.backend,
            "wav_len": len(audio.pcm),
            "auth": auth_result,
            "user_id": self.current_user,
            "latency_ms": (time.perf_counter() - start) * 1000,
        }

    # ---- 音频采集 + VAD 端点检测 ----

    async def _capture_utterance(self) -> bytes:
        """从音源采集一段语音：VAD 判定起点/终点（30ms 帧）。"""
        buf = bytearray()
        started = False
        silence_frames = 0
        speech_frames = 0
        max_speech_frames = int(self.max_turn_s * 1000 / self.vad.frame_ms)
        max_silence_frames = int(self.silence_timeout_s * 1000 / self.vad.frame_ms)
        total_frames = 0
        overall_limit = int((self.max_turn_s + 5) * 1000 / self.vad.frame_ms)

        async for frame in self.source.stream():
            total_frames += 1
            if self.vad.is_speech(frame):
                if not started:
                    started = True
                buf += frame
                speech_frames += 1
                silence_frames = 0
                if speech_frames >= max_speech_frames:
                    break
            elif started:
                buf += frame  # 保留少量尾音，便于 ASR 断句
                silence_frames += 1
                if silence_frames >= max_silence_frames:
                    break
            if total_frames >= overall_limit:
                break

        if not started:
            return b""
        return bytes(buf)
