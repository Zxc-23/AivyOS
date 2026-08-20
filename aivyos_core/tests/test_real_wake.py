"""真实环境唤醒测试 — 验证不同距离、噪音下的唤醒词识别表现。

测试协议：
  1. 安静近距 (30cm)：正常语速说"你好艾薇"/"艾薇" 5 次
  2. 安静中距 (1m)：正常语速说唤醒词 5 次
  3. 噪音环境：播放背景音乐/键盘声时测试
  4. 远距测试 (2-3m)：远距离测试唤醒词

用法:
  python test_real_wake.py                    # 60秒自动测试
  python test_real_wake.py --duration 120     # 120秒测试
  python test_real_wake.py --vad energy       # 使用能量VAD（低延迟）
  python test_real_wake.py --save-audio       # 保存捕获的语音段为WAV
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import struct
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource, AudioUnavailable
from aivyos_core.audio.vad import create_vad, VADEngine, EnergyVAD, _rms
from aivyos_core.asr.manager import create_asr
from aivyos_core.asr.base import ASRBackend
from aivyos_core.wake import WakeWordDetector

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
)
log = logging.getLogger("wake_test")
log.setLevel(logging.INFO)

SAMPLE_RATE = 16000
FRAME_MS = 32
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000  # 1024 bytes
UTTERANCE_TIMEOUT = 5.0
SILENCE_HOLD_FRAMES = 10  # 320ms
MIN_UTTERANCE_FRAMES = 3
WAKE_COOLDOWN = 3.0
DUAL_CONFIRM_WINDOW = 0.5


@dataclass
class TestMetrics:
    """测试指标收集。"""
    started_at: float = field(default_factory=time.monotonic)
    total_frames: int = 0
    speech_frames: int = 0
    utterances_captured: int = 0
    asr_transcriptions: list[dict] = field(default_factory=list)
    wake_events: list[dict] = field(default_factory=list)
    false_triggers: int = 0
    vad_calibration: Optional[dict] = None
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "\n" + "=" * 60,
            "📊 真实环境唤醒测试报告",
            "=" * 60,
            f"  测试时长: {time.monotonic() - self.started_at:.1f}s",
            f"  总帧数: {self.total_frames}",
            f"  语音帧: {self.speech_frames} ({self.speech_frames / max(1, self.total_frames) * 100:.1f}%)",
            f"  捕获语音段: {self.utterances_captured}",
            f"  ASR 转写次数: {len(self.asr_transcriptions)}",
            f"  成功唤醒次数: {len(self.wake_events)}",
            f"  误触发次数: {self.false_triggers}",
        ]
        if self.vad_calibration:
            lines.append(f"  VAD 校准: {json.dumps(self.vad_calibration)}")

        lines.append("\n── ASR 转写详情 ──")
        for i, t in enumerate(self.asr_transcriptions):
            wake_mark = " 🔔" if t.get("is_wake") else ""
            lines.append(f"  [{i+1}] \"{t['text']}\" (len={len(t['text'])}){wake_mark}")

        lines.append("\n── 唤醒事件详情 ──")
        for i, w in enumerate(self.wake_events):
            lines.append(f"  [{i+1}] \"{w['text']}\" @ {w['time']:.1f}s (latency={w['latency_ms']:.0f}ms)")

        if self.errors:
            lines.append(f"\n── 错误 ({len(self.errors)}) ──")
            for e in self.errors:
                lines.append(f"  ⚠️ {e}")

        lines.append("=" * 60)

        if self.wake_events:
            lines.append("\n✅ 唤醒功能验证通过！")
        elif self.asr_transcriptions:
            non_wake = [t for t in self.asr_transcriptions if not t.get("is_wake")]
            lines.append(f"\n⚠️ ASR 工作正常 ({len(self.asr_transcriptions)} 次转写)，但未检测到唤醒词")
            lines.append(f"   非唤醒词转写: {len(non_wake)} 次")
            lines.append("   建议：增大说话音量、靠近麦克风、或检查发音清晰度")
        else:
            lines.append("\n❌ 未检测到任何语音，环境可能过于安静或麦克风未正常工作")

        return "\n".join(lines)


class RealWakeTest:
    """真实环境唤醒测试引擎。"""

    def __init__(
        self,
        duration: float = 60.0,
        vad_backend: str = "silero",
        save_audio: bool = False,
        device: Optional[str] = None,
        gain: float = 1.0,
    ) -> None:
        self.duration = duration
        self.save_audio = save_audio
        self.gain = gain
        self._device: Optional[object] = None
        if device is not None:
            try:
                self._device = int(device)
            except ValueError:
                self._device = device
        self.metrics = TestMetrics()
        self.wake_detector = WakeWordDetector()
        self._running = False
        self._last_wake_time = 0.0
        self._wake_count = 0
        self._noise_levels: deque[float] = deque(maxlen=100)
        self._speech_rms: deque[float] = deque(maxlen=50)
        self._asr: Optional[ASRBackend] = None
        self._vad: Optional[VADEngine] = None
        self._vad_backend = vad_backend
        self._audio_save_dir = "test_audio_saves" if save_audio else None
        self._save_counter = 0

    async def run(self) -> TestMetrics:
        """运行真实环境唤醒测试。"""
        self._running = True
        end_time = time.monotonic() + self.duration

        print(f"\n🎤 真实环境唤醒测试 ({self.duration:.0f}s)")
        print(f"   VAD: {self._vad_backend}")
        print(f"   唤醒词: {', '.join(self.wake_detector.words)}")
        print(f"   保存音频: {'是' if self.save_audio else '否'}")
        print(f"\n请在 {self.duration:.0f}s 内对着麦克风说唤醒词...")
        print(f"测试开始: ", end="", flush=True)

        try:
            source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device=self._device, gain=self.gain)
            self._vad = create_vad({"sample_rate": SAMPLE_RATE, "frame_ms": FRAME_MS, "vad_backend": self._vad_backend})

            if self._audio_save_dir:
                os.makedirs(self._audio_save_dir, exist_ok=True)

            last_status_time = 0.0
            async for frame in source.stream():
                if not self._running or time.monotonic() > end_time:
                    break

                self.metrics.total_frames += 1
                rms = _rms(frame)
                self._noise_levels.append(rms)

                now = time.monotonic()

                if self._vad.is_speech(frame):
                    self.metrics.speech_frames += 1
                    self._speech_rms.append(rms)

                    if now - last_status_time > 2.0:
                        last_status_time = now
                        self._print_status(rms)

                    pcm = await self._capture_utterance(source, end_time)
                    if pcm and len(pcm) >= MIN_UTTERANCE_FRAMES * FRAME_BYTES:
                        self.metrics.utterances_captured += 1
                        await self._process_utterance(pcm)

                elif self.metrics.total_frames % 100 == 0:
                    self._print_idle_status(rms)

        except KeyboardInterrupt:
            print("\n\n⏹️ 测试被用户中断")
        except Exception as e:
            self.metrics.errors.append(str(e))
            log.exception("测试异常")
        finally:
            self._running = False

        self._print_final_report()
        return self.metrics

    async def _capture_utterance(self, source: MicSource, end_time: float) -> Optional[bytes]:
        """捕获完整语音段。"""
        frames: list[bytes] = []
        silence_count = 0
        start_time = time.monotonic()

        try:
            async for frame in source.stream():
                if not self._running or time.monotonic() > end_time:
                    break

                elapsed = time.monotonic() - start_time
                if elapsed > UTTERANCE_TIMEOUT:
                    break

                frames.append(frame)

                if self._vad.is_speech(frame):
                    silence_count = 0
                else:
                    silence_count += 1
                    if silence_count >= SILENCE_HOLD_FRAMES:
                        break

        except asyncio.CancelledError:
            return None

        if len(frames) < MIN_UTTERANCE_FRAMES:
            return None

        pcm = b"".join(frames)

        if self.save_audio:
            self._save_pcm(pcm, elapsed)

        return pcm

    async def _process_utterance(self, pcm: bytes) -> None:
        """处理语音段：ASR → 唤醒检测。"""
        try:
            asr = self._get_asr()
            t0 = time.monotonic()
            result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
            latency_ms = (time.monotonic() - t0) * 1000
            text = result.text if result else ""

            entry = {
                "text": text,
                "latency_ms": round(latency_ms, 1),
                "length_ms": len(pcm) // 2,
                "time": round(time.monotonic() - self.metrics.started_at, 1),
                "is_wake": False,
            }

            if text:
                is_wake = self._check_wake(text)
                entry["is_wake"] = is_wake

                if is_wake:
                    self.metrics.wake_events.append({
                        "text": text,
                        "time": round(time.monotonic() - self.metrics.started_at, 1),
                        "latency_ms": round(latency_ms, 1),
                    })
                    print(f"\n  🔔 唤醒触发! \"{text}\" (ASR: {latency_ms:.0f}ms)", flush=True)
                else:
                    print(f"\n  🗣️  \"{text}\" (ASR: {latency_ms:.0f}ms)", end="", flush=True)
            else:
                entry["text"] = "(空)"

            self.metrics.asr_transcriptions.append(entry)

        except Exception as e:
            self.metrics.errors.append(f"处理语音段异常: {e}")
            log.exception("处理异常")

    def _check_wake(self, text: str) -> bool:
        """带双确认的唤醒词检测。"""
        if not self.wake_detector.detect(text):
            return False

        now = time.monotonic()
        elapsed = now - self._last_wake_time

        if elapsed < DUAL_CONFIRM_WINDOW:
            self._wake_count += 1
            self._last_wake_time = now
            return True
        elif elapsed < WAKE_COOLDOWN:
            return False
        else:
            self._last_wake_time = now
            return False

    def _get_asr(self) -> ASRBackend:
        """延迟初始化 ASR。"""
        if self._asr is None:
            print("\n  ⏳ 加载 ASR 模型...", end="", flush=True)
            self._asr = create_asr({})
            print("就绪", flush=True)
        return self._asr

    def _print_status(self, rms: float) -> None:
        """打印实时状态。"""
        avg_noise = sum(self._noise_levels) / max(1, len(self._noise_levels))
        speech_rms = sum(self._speech_rms) / max(1, len(self._speech_rms)) if self._speech_rms else 0
        progress = max(0, self.duration - (time.monotonic() - self.metrics.started_at))

        bar_len = 20
        elapsed_ratio = min(1.0, (time.monotonic() - self.metrics.started_at) / self.duration)
        filled = int(bar_len * elapsed_ratio)
        bar = "█" * filled + "░" * (bar_len - filled)

        sys.stdout.write(
            f"\r  [{bar}] {progress:.0f}s | "
            f"噪音={avg_noise:.0f} RMS | 语音={speech_rms:.0f} RMS | "
            f"唤醒={len(self.metrics.wake_events)} | "
            f"ASR={len(self.metrics.asr_transcriptions)}"
        )
        sys.stdout.flush()

    def _print_idle_status(self, rms: float) -> None:
        """空闲状态打印。"""
        avg_noise = sum(self._noise_levels) / max(1, len(self._noise_levels))
        progress = max(0, self.duration - (time.monotonic() - self.metrics.started_at))

        bar_len = 20
        elapsed_ratio = min(1.0, (time.monotonic() - self.metrics.started_at) / self.duration)
        filled = int(bar_len * elapsed_ratio)
        bar = "█" * filled + "░" * (bar_len - filled)

        sys.stdout.write(
            f"\r  [{bar}] {progress:.0f}s | "
            f"噪音={avg_noise:.0f} RMS | "
            f"等待语音中..."
        )
        sys.stdout.flush()

    def _print_final_report(self) -> None:
        """打印最终报告。"""
        print(self.metrics.summary())

    def _save_pcm(self, pcm: bytes, duration_ms: float) -> None:
        """保存 PCM 数据为 WAV 文件。"""
        import wave
        filename = os.path.join(
            self._audio_save_dir,
            f"utterance_{self._save_counter:03d}_{int(time.monotonic())}.wav"
        )
        self._save_counter += 1
        with wave.open(filename, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm)

    def stop(self) -> None:
        """停止测试。"""
        self._running = False


async def main():
    parser = argparse.ArgumentParser(description="真实环境唤醒测试")
    parser.add_argument("--duration", type=float, default=60.0, help="测试时长（秒）")
    parser.add_argument("--vad", choices=["silero", "energy"], default="silero", help="VAD 引擎")
    parser.add_argument("--save-audio", action="store_true", help="保存捕获的语音段")
    parser.add_argument("--device", type=str, default=None, help="麦克风设备索引（如 '1', '7', '19'）")
    parser.add_argument("--gain", type=float, default=1.0, help="软件增益倍数（如 50.0）")
    args = parser.parse_args()

    print("=" * 60)
    print("🎙️  AivyOS 真实环境唤醒测试")
    print("=" * 60)
    print(f"\n📋 测试协议:")
    print(f"  1. 安静近距 (30cm): 正常语速说唤醒词 5 次")
    print(f"  2. 安静中距 (1m): 正常语速说唤醒词 5 次")
    print(f"  3. 噪音环境: 播放背景音乐/键盘声时测试")
    print(f"  4. 远距 (2-3m): 远距离测试")
    print(f"\n🎯 唤醒词: {', '.join(WakeWordDetector().words)}")
    print(f"💡 提示: 说 \"你好艾薇\" 或 \"艾薇\" 或 \"Aivy\"")

    tester = RealWakeTest(
        duration=args.duration,
        vad_backend=args.vad,
        save_audio=args.save_audio,
        device=args.device,
        gain=args.gain,
    )

    metrics = await tester.run()

    return 0 if metrics.wake_events or metrics.asr_transcriptions else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))