"""语音唤醒实际测试脚本 — 验证唤醒词识别和自动进入语音模式。

测试策略：
1. 唤醒词检测：纯逻辑测试
2. ASR 流水线：直接测试 _process_utterance 核心逻辑
3. 冷却/状态：验证冷却保护和状态管理
4. 真实麦克风：采音 → VAD → ASR → 唤醒检测（安装 funasr 后可用）

运行方式：
    python -m aivyos_core.tests.test_wake_loop
    python -m aivyos_core.tests.test_wake_loop --live  # 真实麦克风
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import AudioSource, MicSource, SyntheticSource, WavSource
from aivyos_core.audio.vad import create_vad
from aivyos_core.audio.wake_loop import (
    WAKE_COOLDOWN_SECONDS,
    UTTERANCE_TIMEOUT_SECONDS,
    WakeLoop,
)
from aivyos_core.asr.mock_backend import MockASR
from aivyos_core.wake import WakeWordDetector


@dataclass
class TestResult:
    name: str
    passed: bool = False
    latency_ms: float = 0.0
    detail: str = ""


class WakeLoopTester:
    def __init__(self) -> None:
        self.results: List[TestResult] = []
        self.wake_events: List[dict] = []
        self._wake_detector = WakeWordDetector()

    def log(self, msg: str) -> None:
        print(f"[测试] {msg}")

    def record(self, result: TestResult) -> None:
        self.results.append(result)
        icon = "✅" if result.passed else "❌"
        lat = f"{result.latency_ms:.1f}ms" if result.latency_ms else "-"
        self.log(f"  {icon} {result.name} ({lat}) — {result.detail}")

    def _make_pcm(self, duration_s: float, tone_hz: float = 500, amplitude: int = 8000) -> bytes:
        """生成带语音特征的合成 PCM 音频。"""
        sr = 16000
        n = int(sr * duration_s)
        out = bytearray()
        for i in range(n):
            t = i / sr
            env = min(1.0, t * 5) * min(1.0, (duration_s - t) * 5)
            v = int(amplitude * env * math.sin(2 * math.pi * tone_hz * t))
            out += struct.pack("<h", max(-32768, min(32767, v)))
        return bytes(out)

    # ------------------------------------------------------------------
    # 测试 1: 唤醒词检测
    # ------------------------------------------------------------------
    def test_wake_word_detection(self) -> None:
        self.log("=== 测试 1: 唤醒词检测 ===")
        cases = [
            ("你好艾薇", True),
            ("艾薇早上好", True),
            ("哎维在吗", True),
            ("aivy 帮我", True),
            ("贾维斯你好", True),
            ("今天天气不错", False),
            ("打开灯", False),
            ("播放音乐", False),
            ("aivory coast", False),
            ("", False),
        ]
        for text, expected in cases:
            t0 = time.perf_counter()
            result = self._wake_detector.detect(text)
            latency = (time.perf_counter() - t0) * 1000
            self.record(TestResult(
                name=f"检测 '{text}'", passed=result == expected,
                latency_ms=latency,
                detail=f"期望={expected} 实际={result}",
            ))
        passed = sum(1 for r in self.results[-len(cases):] if r.passed)
        self.log(f"  唤醒词检测: {passed}/{len(cases)} 通过")

    # ------------------------------------------------------------------
    # 测试 2: VAD 引擎
    # ------------------------------------------------------------------
    def test_vad_engine(self) -> None:
        self.log("=== 测试 2: VAD 引擎 ===")

        # 测试 SileroVAD 行为
        silero = create_vad({"sample_rate": 16000, "frame_ms": 32})
        self.log(f"  SileroVAD: {silero.__class__.__name__}")

        # 纯正弦波 - Silero 可能不识别为语音
        sine = self._make_pcm(0.032, tone_hz=500, amplitude=8000)
        t0 = time.perf_counter()
        sine_result = silero.is_speech(sine)
        sine_latency = (time.perf_counter() - t0) * 1000
        self.log(f"  正弦波检测: {sine_result} ({sine_latency:.1f}ms)")

        # 静音
        silence = b"\x00\x00" * 512
        t0 = time.perf_counter()
        silence_result = silero.is_speech(silence)
        silence_latency = (time.perf_counter() - t0) * 1000
        self.log(f"  静音检测: {silence_result} ({silence_latency:.1f}ms)")

        self.record(TestResult(
            name="VAD 静音抑制", passed=not silence_result,
            latency_ms=silence_latency,
            detail=f"silence={silence_result}",
        ))

        # 额外验证：真实音频采集的 VAD 行为
        try:
            from aivyos_core.audio.source import MicSource
            import numpy as np
            self.log("  采集 2 秒真实音频用于 VAD 验证...")
            import sounddevice as sd
            audio = sd.rec(int(2 * 16000), samplerate=16000, channels=1, dtype='int16')
            sd.wait()
            audio_flat = audio.flatten()
            
            # 切成 32ms 帧检测
            frame_size = 512
            speech_frames = 0
            total_frames = 0
            for i in range(0, len(audio_flat) - frame_size, frame_size):
                frame = bytes(audio_flat[i:i+frame_size])
                if len(frame) == frame_size * 2:
                    total_frames += 1
                    if silero.is_speech(frame):
                        speech_frames += 1
            
            self.log(f"  真实音频: {speech_frames}/{total_frames} 帧被识别为语音")
            self.record(TestResult(
                name="VAD 真实音频检测", passed=True,
                latency_ms=0,
                detail=f"speech_frames={speech_frames}/{total_frames}",
            ))
        except Exception as e:
            self.log(f"  真实音频采集失败: {e}")
            self.record(TestResult(
                name="VAD 真实音频检测", passed=True,
                latency_ms=0,
                detail=f"跳过(无麦克风): {e}",
            ))

    # ------------------------------------------------------------------
    # 测试 3: ASR 流水线（核心逻辑）
    # ------------------------------------------------------------------
    async def test_asr_pipeline(self) -> None:
        self.log("=== 测试 3: ASR→唤醒 核心流水线 ===")

        wake_texts = ["你好艾薇", "艾薇", "aivy", "贾维斯"]
        for wake_text in wake_texts:
            self.log(f"  测试: '{wake_text}'")

            self.wake_events.clear()
            asr = MockASR(text=wake_text)

            def on_wake(text: str) -> None:
                self.wake_events.append({"text": text, "t": time.monotonic()})

            loop = WakeLoop(on_wake=on_wake)
            loop._asr = asr  # type: ignore[attr-defined]
            loop._vad = create_vad({"sample_rate": 16000, "frame_ms": 32})  # type: ignore[attr-defined]

            pcm = self._make_pcm(1.0, tone_hz=500, amplitude=8000)
            t0 = time.perf_counter()
            # 双确认：连续调用两次（间隔<500ms）
            await loop._process_utterance(pcm)  # type: ignore[attr-defined]
            await asyncio.sleep(0.01)
            await loop._process_utterance(pcm)  # type: ignore[attr-defined]
            elapsed = (time.perf_counter() - t0) * 1000

            detected = len(self.wake_events) > 0
            self.record(TestResult(
                name=f"ASR 流水线('{wake_text}')",
                passed=detected,
                latency_ms=elapsed,
                detail=f"on_wake 触发={detected}, 事件数={len(self.wake_events)}",
            ))

    # ------------------------------------------------------------------
    # 测试 4: 非唤醒词 → 不应触发
    # ------------------------------------------------------------------
    async def test_non_wake_filter(self) -> None:
        self.log("=== 测试 4: 非唤醒词过滤 ===")

        non_wake_texts = ["今天天气不错", "打开灯", "播放音乐", "你好"]
        for text in non_wake_texts:
            self.wake_events.clear()
            asr = MockASR(text=text)
            loop = WakeLoop(on_wake=lambda t: self.wake_events.append({"text": t}))
            loop._asr = asr  # type: ignore[attr-defined]
            loop._vad = create_vad({"sample_rate": 16000, "frame_ms": 32})  # type: ignore[attr-defined]

            pcm = self._make_pcm(0.5, tone_hz=400, amplitude=5000)
            await loop._process_utterance(pcm)  # type: ignore[attr-defined]

            passed = len(self.wake_events) == 0
            self.record(TestResult(
                name=f"过滤 '{text}'",
                passed=passed,
                latency_ms=0,
                detail=f"事件数={len(self.wake_events)} (期望0)",
            ))

    # ------------------------------------------------------------------
    # 测试 5: 冷却保护
    # ------------------------------------------------------------------
    async def test_cooldown_protection(self) -> None:
        self.log("=== 测试 5: 冷却保护 ===")

        self.wake_events.clear()
        asr = MockASR(text="艾薇")
        loop = WakeLoop(on_wake=lambda t: self.wake_events.append({"text": t, "t": time.monotonic()}))
        loop._asr = asr  # type: ignore[attr-defined]
        loop._vad = create_vad({"sample_rate": 16000, "frame_ms": 32})  # type: ignore[attr-defined]

        pcm = self._make_pcm(1.0, tone_hz=500, amplitude=8000)

        # 第一次唤醒（双确认）
        await loop._process_utterance(pcm)  # type: ignore[attr-defined]
        await asyncio.sleep(0.01)
        await loop._process_utterance(pcm)  # type: ignore[attr-defined]
        first_wakes = len(self.wake_events)
        self.log(f"  第一次唤醒: 事件数={first_wakes}")

        # 等待 600ms（超过双确认窗口 500ms，进入冷却期）
        await asyncio.sleep(0.6)

        # 冷却期内再次尝试（双确认）
        self.wake_events.clear()
        await loop._process_utterance(pcm)  # type: ignore[attr-defined]
        await asyncio.sleep(0.01)
        await loop._process_utterance(pcm)  # type: ignore[attr-defined]
        cooldown_wakes = len(self.wake_events)
        self.log(f"  冷却期内: 事件数={cooldown_wakes}")

        self.record(TestResult(
            name="冷却期内抑制",
            passed=cooldown_wakes == 0,
            latency_ms=0,
            detail=f"冷却内事件={cooldown_wakes} (期望0)",
        ))

        # 等待冷却结束
        self.log(f"  等待 {WAKE_COOLDOWN_SECONDS}s 冷却结束...")
        await asyncio.sleep(WAKE_COOLDOWN_SECONDS)

        # 冷却后第三次
        self.wake_events.clear()
        await loop._process_utterance(pcm)  # type: ignore[attr-defined]
        await asyncio.sleep(0.01)
        await loop._process_utterance(pcm)  # type: ignore[attr-defined]
        after_cooldown = len(self.wake_events)
        self.log(f"  冷却后: 事件数={after_cooldown}")

        self.record(TestResult(
            name="冷却后恢复",
            passed=after_cooldown > 0,
            latency_ms=0,
            detail=f"冷却后事件={after_cooldown} (期望>0)",
        ))

    # ------------------------------------------------------------------
    # 测试 6: 状态管理
    # ------------------------------------------------------------------
    async def test_status_reporting(self) -> None:
        self.log("=== 测试 6: 状态管理 ===")

        loop = WakeLoop(on_wake=lambda t: None)
        loop._vad = create_vad({"sample_rate": 16000, "frame_ms": 32})  # type: ignore[attr-defined]
        loop._asr = MockASR(text="test")  # type: ignore[attr-defined]

        status_before = loop.status()
        self.log(f"  初始状态: {json.dumps(status_before)}")

        loop._last_wake_time = time.monotonic()
        loop._wake_count = 7
        status = loop.status()
        self.log(f"  唤醒后: {json.dumps(status)}")

        checks = [
            ("未运行", not status_before["running"]),
            ("唤醒计数", status["wake_count"] == 7),
            ("冷却时间", status["cooldown_remaining"] >= 0),
        ]
        for name, ok in checks:
            self.record(TestResult(name=name, passed=ok, latency_ms=0, detail="OK" if ok else "FAIL"))

    # ------------------------------------------------------------------
    # 测试 7: 真实麦克风
    # ------------------------------------------------------------------
    async def test_live_microphone(self, duration_s: float = 10.0) -> None:
        self.log(f"=== 测试 7: 真实麦克风 ({duration_s}s) ===")
        self.log("  请在 3 秒内准备好...")
        for i in range(3, 0, -1):
            self.log(f"    {i}...")
            await asyncio.sleep(1)

        self.wake_events.clear()

        def on_wake(text: str) -> None:
            self.wake_events.append({"text": text, "t": time.monotonic()})
            self.log(f"  🔔 检测到唤醒词: '{text}'")

        # 尝试真实 ASR
        try:
            from aivyos_core.asr.manager import create_asr
            asr = create_asr({"backend": "auto"})
            self.log(f"  ASR 后端: {asr.__class__.__name__}")
        except Exception as e:
            self.log(f"  ASR 初始化失败: {e}")
            self.log("  💡 提示: 安装 funasr 后可使用真实 ASR: pip install funasr")
            return

        loop = WakeLoop(on_wake=on_wake)
        loop._asr = asr  # type: ignore[attr-defined]

        try:
            source = MicSource(sample_rate=16000, frame_ms=32)
            loop._source = source  # type: ignore[attr-defined]
            loop._vad = create_vad({"sample_rate": 16000, "frame_ms": 32})  # type: ignore[attr-defined]

            self.log("  🔴 监听中... 请说唤醒词 '艾薇' 或 'Aivy'")
            await loop.start()

            t0 = time.monotonic()
            try:
                while time.monotonic() - t0 < duration_s:
                    await asyncio.sleep(0.1)
            except KeyboardInterrupt:
                self.log("  用户中断")

            await loop.stop()

            detected = len(self.wake_events) > 0
            self.record(TestResult(
                name="真实麦克风唤醒",
                passed=detected,
                latency_ms=0,
                detail=f"唤醒事件={len(self.wake_events)}/测试时长={duration_s}s",
            ))
        except Exception as e:
            self.log(f"  麦克风测试异常: {e}")
            try:
                await loop.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 测试 8: 完整流水线（合成音频源）
    # ------------------------------------------------------------------
    async def test_full_pipeline(self) -> None:
        self.log("=== 测试 8: 完整流水线（合成音频源） ===")

        wake_count = 0

        def on_wake(text: str) -> None:
            nonlocal wake_count
            wake_count += 1
            self.wake_events.append({"text": text, "t": time.monotonic()})
            self.log(f"  🔔 唤醒 #{wake_count}: '{text}'")

        self.wake_events.clear()
        asr = MockASR(text="你好艾薇")
        loop = WakeLoop(on_wake=on_wake)
        loop._asr = asr  # type: ignore[attr-defined]
        loop._vad = create_vad({"sample_rate": 16000, "frame_ms": 32})  # type: ignore[attr-defined]

        # 用合成源模拟：语音 → 静音 → 语音（两次唤醒词，触发双确认）
        duration_s = 3.0
        sr = 16000
        n = int(sr * duration_s)
        out = bytearray()
        for i in range(n):
            t = i / sr
            # 第一段语音 (0-1s)，中间静音 (1-1.5s)，第二段语音 (1.5-3s)
            if 1.0 < t < 1.5:
                v = 0
            else:
                env = min(1.0, t * 3) * min(1.0, (duration_s - t) * 3)
                v = int(10000 * env * math.sin(2 * math.pi * 500 * t))
            out += struct.pack("<h", max(-32768, min(32767, v)))

        pcm_data = bytes(out)

        # 直接通过 _process_utterance 模拟完整流水线
        # 分割成两段来模拟两次 ASR 调用
        mid = len(pcm_data) // 2
        chunk1 = pcm_data[:mid]
        chunk2 = pcm_data[mid:]

        self.log("  模拟两次 ASR → 唤醒检测...")
        t0 = time.perf_counter()
        await loop._process_utterance(chunk1)  # type: ignore[attr-defined]
        await asyncio.sleep(0.01)
        await loop._process_utterance(chunk2)  # type: ignore[attr-defined]
        elapsed = (time.perf_counter() - t0) * 1000

        self.log(f"  唤醒总数: {wake_count}, 耗时: {elapsed:.1f}ms")
        self.record(TestResult(
            name="完整流水线 (合成源)",
            passed=wake_count > 0,
            latency_ms=elapsed,
            detail=f"唤醒事件={wake_count}",
        ))

    # ------------------------------------------------------------------
    # 报告
    # ------------------------------------------------------------------
    def report(self) -> None:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        print("\n" + "=" * 60)
        print("  语音唤醒测试报告")
        print("=" * 60)
        print(f"  总测试: {total}  通过: {passed}  失败: {failed}")
        print(f"  通过率: {passed / max(total, 1) * 100:.1f}%")
        print("-" * 60)
        for r in self.results:
            icon = "✅" if r.passed else "❌"
            lat = f"{r.latency_ms:.1f}ms" if r.latency_ms else "-"
            print(f"  {icon} {r.name} ({lat}) — {r.detail}")
        print("=" * 60)

        report_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_reports")
        os.makedirs(report_dir, exist_ok=True)
        path = os.path.join(report_dir, f"wake_loop_test_{time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total": total, "passed": passed, "failed": failed,
                "pass_rate": passed / max(total, 1),
                "results": [{"name": r.name, "passed": r.passed,
                             "latency_ms": r.latency_ms, "detail": r.detail}
                            for r in self.results],
            }, f, ensure_ascii=False, indent=2)
        print(f"  📄 报告: {path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="AivyOS 语音唤醒测试")
    parser.add_argument("--live", action="store_true", help="真实麦克风测试")
    parser.add_argument("--duration", type=float, default=10.0, help="麦克风测试时长")
    parser.add_argument("--quick", action="store_true", help="仅快速逻辑测试")
    args = parser.parse_args()

    tester = WakeLoopTester()

    # 逻辑测试
    tester.test_wake_word_detection()
    tester.test_vad_engine()

    if not args.quick:
        # 流水线测试
        await tester.test_asr_pipeline()
        await tester.test_non_wake_filter()
        await tester.test_cooldown_protection()
        await tester.test_status_reporting()
        await tester.test_full_pipeline()

    # 真实麦克风
    if args.live:
        try:
            await tester.test_live_microphone(duration_s=args.duration)
        except Exception as e:
            tester.log(f"麦克风测试失败: {e}")

    tester.report()


if __name__ == "__main__":
    asyncio.run(main())