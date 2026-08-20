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

    async def run_turn(self, text_override: Optional[str] = None, skip_wake: bool = False) -> Optional[Dict[str, Any]]:
        """执行一轮语音对话，返回 {text, reply, wav_len, latency_ms, ...} 或 None。

        text_override：跳过真实音频链路（测试/文本模拟模式）。
        skip_wake：跳过唤醒词检查（连续对话模式：唤醒后窗口内无需重复唤醒词）。
        认证门控（§9）：真实音频路径下未通过认证 → 静默拒绝（不暴露系统存在）。
        耗时细分：asr_ms / llm_ms / tts_ms / playback_ms，用于诊断瓶颈。
        """
        start = time.perf_counter()
        asr_ms = 0.0
        llm_ms = 0.0
        tts_ms = 0.0
        playback_ms = 0.0

        if text_override is not None:
            transcript = text_override
            asr_backend = "text-override"
            auth_result = {"bypassed": True, "reason": "文本模拟模式"}
            # 唤醒词门控：文本覆盖模式下，wake_required 且非连续对话窗口时仍需检查
            wake_passed = (not self.wake_required) or skip_wake or self.wake.detect(transcript)
            if not wake_passed:
                log.info("唤醒词未命中 (text_override): %r", transcript[:30])
                return {"text": transcript, "reply": None, "wake": False, "auth": auth_result}
        else:
            log.info("开始真实音频采集...")
            pcm = await self._capture_utterance()
            if not pcm:
                log.warning("音频采集未检测到语音 (source=%s)", type(self.source).__name__)
                return {
                    "text": "",
                    "reply": None,
                    "error": "no_speech_detected",
                    "error_detail": "未检测到语音输入，请靠近麦克风重试",
                    "source": type(self.source).__name__,
                }
            log.info("音频采集完成: %d bytes", len(pcm))
            if self.auth is not None:
                auth_result = (await self.auth.authenticate(pcm=pcm)).to_dict()
                if not auth_result["accepted"]:
                    log.info("认证未通过，静默忽略（%s）", auth_result.get("reason", ""))
                    return {"text": "", "reply": None, "auth": auth_result, "wake": False}
                self.current_user = auth_result["user_id"]
                persona = self.auth.get_user_persona(self.current_user)
                for k, v in persona.items():
                    self.engine.persona.update(k, v)
            else:
                auth_result = {"bypassed": True, "reason": "认证未启用"}
            asr_t0 = time.perf_counter()
            result = self.asr.transcribe(pcm)
            asr_ms = (time.perf_counter() - asr_t0) * 1000
            transcript = result.text
            asr_backend = result.backend
            wake_passed = (not self.wake_required) or skip_wake or self.wake.detect(transcript)
            if not wake_passed:
                log.info("唤醒词未命中: %r", transcript[:30])
                return {"text": transcript, "reply": None, "wake": False, "auth": auth_result}

        # 已通过唤醒词检查（文本模式自动通过，真实音频需命中唤醒词）
        clean = self.wake.strip(transcript) if self.wake_required else transcript
        if not clean:
            # 识别到语音但内容为空/纯噪音/仅唤醒词 → 明确错误（§3.1 噪音过滤）
            log.info("识别结果为空指令（可能为环境噪音）: %r", transcript[:40])
            return {
                "text": transcript,
                "reply": None,
                "error": "empty_command",
                "error_detail": "未识别到有效语音指令（请减少环境噪音后重试）",
                "auth": auth_result,
                "wake": True,
            }

        # LLM 对话
        llm_t0 = time.perf_counter()
        reply = await self.engine.send(clean)
        llm_ms = (time.perf_counter() - llm_t0) * 1000

        # TTS + 输出 — 用线程池避免阻塞事件循环
        tts_t0 = time.perf_counter()
        loop = asyncio.get_running_loop()
        try:
            audio = await loop.run_in_executor(
                None, lambda: self.tts.synthesize(reply.text)
            )
        except Exception as e:
            log.exception("TTS 合成失败")
            audio = None
        tts_ms = (time.perf_counter() - tts_t0) * 1000

        wav_b64 = ""
        if audio is not None:
            try:
                import base64
                from aivyos_core.audio.wav import pcm_to_wav_bytes
                wav_bytes = pcm_to_wav_bytes(audio.pcm, audio.sample_rate)
                wav_b64 = base64.b64encode(wav_bytes).decode("ascii")
            except Exception:
                log.warning("WAV 编码失败，跳过前端音频")

        if audio is not None:
            try:
                # 后端播放仅 fire-and-forget，不等待完成
                # 前端已通过 wav_b64 + Web Audio API 自行播放，后端播放为冗余
                # 保留 fire-and-forget 兼容 CLI 无前端场景
                self.sink.play(audio.pcm)
            except Exception:
                pass
            playback_ms = 0.0  # 非阻塞，不计时

        total_ms = (time.perf_counter() - start) * 1000
        log.info(
            "语音对话完成: total=%.0fms asr=%.0fms llm=%.0fms tts=%.0fms play=%.0fms (model=%s)",
            total_ms, asr_ms, llm_ms, tts_ms, playback_ms, reply.model,
        )

        return {
            "text": transcript,
            "text_clean": clean,
            "reply": reply.text,
            "model": reply.model,
            "route": reply.route.to_dict(),
            "asr_backend": asr_backend,
            "tts_backend": audio.backend if audio else "tts-failed",
            "wav_len": len(audio.pcm) if audio else 0,
            "wav_b64": wav_b64,
            "sample_rate": audio.sample_rate if audio else 24000,
            "auth": auth_result,
            "user_id": self.current_user,
            "latency_ms": total_ms,
            "breakdown_ms": {
                "asr": round(asr_ms, 1),
                "llm": round(llm_ms, 1),
                "tts": round(tts_ms, 1),
                "playback": round(playback_ms, 1),
                "total": round(total_ms, 1),
            },
        }

    # ---- 独立播报（连续对话提醒/退出确认）----

    def speak(self, text: str) -> bool:
        """合成并播放一段提示语（如'还需要我吗？'）。返回是否成功。

        与 run_turn 的 TTS 播放解耦，供 server_entry 在连续对话窗口
        到期提醒 / 退出确认时直接调用（fire-and-forget，不阻塞）。
        """
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            audio = loop.run_in_executor(None, lambda: self.tts.synthesize(text))
            # 同步包装：executor 结果需等待，但这里在 async 上下文
            return False
        except RuntimeError:
            pass
        # 无运行循环（同步上下文）：直接合成播放
        try:
            import threading

            result: list = []

            def _synth():
                audio = self.tts.synthesize(text)
                if audio is not None:
                    self.sink.play(audio.pcm)
                result.append(True if audio else False)

            t = threading.Thread(target=_synth, daemon=True)
            t.start()
            t.join(timeout=30)
            return bool(result and result[0])
        except Exception as e:
            log.warning("speak 失败: %s", e)
            return False

    async def aspeak(self, text: str) -> bool:
        """异步版：合成并播放提示语（用于 async 上下文，如 voice.turn 内）。"""
        try:
            loop = asyncio.get_running_loop()
            audio = await loop.run_in_executor(None, lambda: self.tts.synthesize(text))
            if audio is None:
                return False
            # 等待播放完成一小段（避免与下一轮采集重叠），然后后端播放
            self.sink.play(audio.pcm)
            return True
        except Exception as e:
            log.warning("aspeak 失败: %s", e)
            return False

    # ---- 音频采集 + VAD 端点检测 ----

    async def _capture_utterance(self) -> bytes:
        """从音源采集一段语音：VAD 判定起点/终点（30ms 帧）。

        带超时保护：若 10 秒内无语音输入，自动返回空字节。
        """
        buf = bytearray()
        started = False
        silence_frames = 0
        speech_frames = 0
        max_speech_frames = int(self.max_turn_s * 1000 / self.vad.frame_ms)
        max_silence_frames = int(self.silence_timeout_s * 1000 / self.vad.frame_ms)
        total_frames = 0
        overall_limit = int((self.max_turn_s + 5) * 1000 / self.vad.frame_ms)
        startup_timeout_frames = int(10.0 * 1000 / self.vad.frame_ms)

        stream_iter = self.source.stream()
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(stream_iter.__anext__(), timeout=120.0)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    log.warning("音频采集超时（120s 无数据）")
                    break

                total_frames += 1
                if self.vad.is_speech(frame):
                    if not started:
                        started = True
                        log.debug("VAD 检测到语音起点 (frame %d)", total_frames)
                    buf += frame
                    speech_frames += 1
                    silence_frames = 0
                    if speech_frames >= max_speech_frames:
                        log.debug("达到最大语音时长限制")
                        break
                elif started:
                    buf += frame
                    silence_frames += 1
                    if silence_frames >= max_silence_frames:
                        log.debug("VAD 检测到语音终点（静默 %d 帧）", silence_frames)
                        break
                if total_frames >= overall_limit:
                    log.debug("达到总帧上限")
                    break
                if not started and total_frames >= startup_timeout_frames:
                    log.info("启动超时：%d 帧内未检测到语音", startup_timeout_frames)
                    break
        finally:
            try:
                stream_iter.aclose()
            except Exception:
                pass

        if not started:
            log.info("未检测到语音输入 (总帧数=%d)", total_frames)
            return b""
        log.info("采集完成: %d 帧, %d bytes, 时长 %.1fs",
                 total_frames, len(buf), len(buf) / 32000)
        return bytes(buf)
