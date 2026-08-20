"""后台唤醒监听循环 — 持续采集音频，检测唤醒词后推送事件。

架构：
    MicSource.stream() → SileroVAD → ASR转写 → WakeWordDetector → 事件推送

特性：
- 低功耗：空闲时仅运行 VAD (~0.4ms/帧)，检测到语音才启动 ASR
- 双次确认：必须连续 2 次检测到唤醒词才触发
- 冷却保护：对话结束后 3 秒内不响应唤醒词
- 状态管理：支持 start/stop/status 查询
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import create_vad, VADEngine
from aivyos_core.asr.manager import create_asr
from aivyos_core.asr.base import ASRBackend
from aivyos_core.wake import WakeWordDetector

log = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_FRAME_MS = 32
VAD_SPEECH_HOLD_FRAMES = 10  # 320ms 静音判定为语音结束
WAKE_COOLDOWN_SECONDS = 3.0
UTTERANCE_TIMEOUT_SECONDS = 5.0
MIN_UTTERANCE_FRAMES = 3  # 96ms 最短有效语音段


class WakeLoop:
    """后台唤醒监听循环。

    使用方式::

        loop = WakeLoop(on_wake=lambda text: print(f"wake: {text}"))
        await loop.start()
        # ... 运行中 ...
        await loop.stop()
    """

    def __init__(
        self,
        on_wake: Optional[Callable[[str], None]] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        frame_ms: int = DEFAULT_FRAME_MS,
        asr_config: Optional[dict] = None,
        device: Optional[object] = None,
        gain: float = 1.0,
    ) -> None:
        self._on_wake = on_wake
        self._sample_rate = sample_rate
        self._frame_ms = frame_ms
        self._asr_config = asr_config or {}
        self._device = device
        self._gain = gain
        self._task: Optional[asyncio.Task] = None
        self._source: Optional[MicSource] = None
        self._vad: Optional[VADEngine] = None
        self._wake_detector = WakeWordDetector()
        self._running = False
        self._last_wake_time = 0.0
        self._wake_count = 0
        self._asr: Optional[ASRBackend] = None

    @property
    def running(self) -> bool:
        """是否正在运行。"""
        return self._running

    def status(self) -> dict:
        """获取当前状态。"""
        return {
            "running": self._running,
            "wake_count": self._wake_count,
            "last_wake_time": self._last_wake_time,
            "cooldown_remaining": max(0.0, WAKE_COOLDOWN_SECONDS - (time.monotonic() - self._last_wake_time)),
        }

    async def start(self) -> None:
        """启动后台监听循环。"""
        if self._running:
            log.warning("WakeLoop 已在运行")
            return

        if self._source is None:
            self._source = MicSource(
                sample_rate=self._sample_rate,
                frame_ms=self._frame_ms,
                device=self._device,
                gain=self._gain,
            )
        if self._vad is None:
            self._vad = create_vad({"sample_rate": self._sample_rate, "frame_ms": self._frame_ms})
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        log.info("WakeLoop 已启动 (vad=%s)", self._vad.__class__.__name__)

    async def stop(self) -> None:
        """停止后台监听循环。"""
        if not self._running:
            return
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self._source:
            if hasattr(self._source, "close"):
                self._source.close()
            self._source = None
        log.info("WakeLoop 已停止")

    async def _run_loop(self) -> None:
        """主循环：持续采集 → VAD → ASR → 唤醒词检测。"""
        try:
            async for frame in self._source.stream():
                if not self._running:
                    break

                cooldown_left = WAKE_COOLDOWN_SECONDS - (time.monotonic() - self._last_wake_time)
                if cooldown_left > 0:
                    continue

                if self._vad.is_speech(frame):
                    pcm = await self._capture_utterance()
                    if pcm is None:
                        continue
                    await self._process_utterance(pcm)

        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("WakeLoop 主循环异常")
        finally:
            self._running = False

    async def _capture_utterance(self) -> Optional[bytes]:
        """从当前帧开始捕获完整语音段（直到静音超时）。

        Returns:
            完整 PCM 数据，None 表示捕获超时或过短
        """
        frames: list[bytes] = []
        silence_frames = 0
        start_time = time.monotonic()

        try:
            async for frame in self._source.stream():
                if not self._running:
                    return None

                elapsed = time.monotonic() - start_time
                if elapsed > UTTERANCE_TIMEOUT_SECONDS:
                    break

                frames.append(frame)

                if self._vad.is_speech(frame):
                    silence_frames = 0
                else:
                    silence_frames += 1
                    if silence_frames >= VAD_SPEECH_HOLD_FRAMES:
                        break

        except asyncio.CancelledError:
            return None

        if len(frames) < MIN_UTTERANCE_FRAMES:
            return None

        return b"".join(frames)

    async def _process_utterance(self, pcm: bytes) -> None:
        """处理捕获的语音段：ASR → 唤醒词检测 → 事件推送。"""
        try:
            asr = self._get_asr()
            result = await asyncio.to_thread(asr.transcribe, pcm, self._sample_rate)
            text = result.text if result else ""

            if not text:
                return

            if self._wake_detector.detect(text):
                now = time.monotonic()
                elapsed = now - self._last_wake_time

                if elapsed < 0.5:
                    self._wake_count += 1
                    self._last_wake_time = now
                    log.info("🔔 唤醒词命中 (已确认): %s", text)
                    if self._on_wake:
                        try:
                            self._on_wake(text)
                        except Exception:
                            log.exception("on_wake 回调异常")
                elif elapsed < WAKE_COOLDOWN_SECONDS:
                    log.debug("冷却期内，忽略: %s", text)
                else:
                    self._last_wake_time = now
                    log.debug("唤醒词首次命中，等待确认: %s", text)

        except Exception:
            log.exception("语音段处理异常")

    def _get_asr(self) -> ASRBackend:
        """延迟获取 ASR 实例。"""
        if self._asr is None:
            self._asr = create_asr(self._asr_config)
        return self._asr


# ---- 全局实例管理 ----

_global_wake_loop: Optional[WakeLoop] = None


def get_wake_loop() -> Optional[WakeLoop]:
    """获取全局 WakeLoop 实例。"""
    return _global_wake_loop


async def start_wake_loop(on_wake: Optional[Callable[[str], None]] = None) -> dict:
    """启动全局唤醒监听。

    Args:
        on_wake: 唤醒回调函数

    Returns:
        启动状态
    """
    global _global_wake_loop
    if _global_wake_loop and _global_wake_loop.running:
        return {"ok": True, "already_running": True, "status": _global_wake_loop.status()}

    _global_wake_loop = WakeLoop(on_wake=on_wake)
    await _global_wake_loop.start()
    return {"ok": True, "status": _global_wake_loop.status()}


async def stop_wake_loop() -> dict:
    """停止全局唤醒监听。"""
    global _global_wake_loop
    if not _global_wake_loop:
        return {"ok": True, "already_stopped": True}

    await _global_wake_loop.stop()
    _global_wake_loop = None
    return {"ok": True}


def wake_loop_status() -> dict:
    """查询全局唤醒监听状态。"""
    if not _global_wake_loop:
        return {"ok": True, "running": False}
    return {"ok": True, **_global_wake_loop.status()}