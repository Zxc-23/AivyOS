"""最终唤醒测试 — 带交互确认、预校准、实时反馈。

用法: python final_wake_test.py [--gain 100] [--duration 30] [--device 7]
"""
import asyncio
import sys
import os
import struct
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import SileroVAD, EnergyVAD, _rms
from aivyos_core.asr.manager import create_asr
from aivyos_core.asr.base import ASRBackend
from aivyos_core.wake import WakeWordDetector

SAMPLE_RATE = 16000
FRAME_MS = 32
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000
UTTERANCE_TIMEOUT = 5.0
SILENCE_HOLD_FRAMES = 10
MIN_UTTERANCE_FRAMES = 3
WAKE_COOLDOWN = 3.0
DUAL_CONFIRM_WINDOW = 0.5

async def main():
    gain = float(sys.argv[sys.argv.index("--gain") + 1]) if "--gain" in sys.argv else 50.0
    duration = float(sys.argv[sys.argv.index("--duration") + 1]) if "--duration" in sys.argv else 30.0
    device = sys.argv[sys.argv.index("--device") + 1] if "--device" in sys.argv else "7"

    print("=" * 60)
    print("🎙️  AivyOS 最终唤醒测试")
    print("=" * 60)
    print(f"\n  参数: gain={gain}x, duration={duration:.0f}s, device={device}")
    print(f"  唤醒词: {', '.join(WakeWordDetector().words)}")

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device=device, gain=gain)

    # 预校准: 收集2秒环境噪声
    print(f"\n  📻 噪声校准中 (2秒)...", flush=True)
    cal_rms = []
    cal_end = asyncio.get_event_loop().time() + 2.0
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > cal_end:
            break
        cal_rms.append(_rms(frame))

    noise_avg = sum(cal_rms) / max(1, len(cal_rms))
    noise_peak = max(cal_rms) if cal_rms else 0
    threshold = max(30, min(500, int(noise_avg * 2)))
    print(f"  ✅ 噪声校准完成: 均值={noise_avg:.1f}RMS, 峰值={noise_peak:.1f}RMS, VAD阈值={threshold}")

    vad = EnergyVAD(threshold=threshold, frame_ms=FRAME_MS, auto_calibrate=False)
    wake_detector = WakeWordDetector()

    print(f"\n  ⏳ 加载 ASR 模型...", flush=True)
    asr = create_asr({})
    print(f"  ✅ ASR 就绪")

    # 倒计时
    print(f"\n  测试将在 3 秒后开始...请准备说唤醒词!")
    for i in [3, 2, 1]:
        print(f"    {i}...")
        await asyncio.sleep(1)

    print(f"\n  🎤 开始! 请对着麦克风说唤醒词 ({duration:.0f}s)\n")

    end_time = time.monotonic() + duration
    stats = {"frames": 0, "speech_frames": 0, "utterances": 0, "wakes": 0}
    last_wake_time = 0.0
    wake_count = 0

    async for frame in source.stream():
        if time.monotonic() > end_time:
            break

        stats["frames"] += 1
        rms = _rms(frame)

        if vad.is_speech(frame):
            stats["speech_frames"] += 1
            print(f"  🔊 语音帧 RMS={rms:.0f}", end="", flush=True)

            # 捕获完整语音段
            utterance_frames = [frame]
            silence_count = 0
            capture_start = time.monotonic()

            async for cap_frame in source.stream():
                if time.monotonic() > end_time:
                    break
                if time.monotonic() - capture_start > UTTERANCE_TIMEOUT:
                    break

                utterance_frames.append(cap_frame)

                if vad.is_speech(cap_frame):
                    silence_count = 0
                else:
                    silence_count += 1
                    if silence_count >= SILENCE_HOLD_FRAMES:
                        break

            if len(utterance_frames) < MIN_UTTERANCE_FRAMES:
                print(" - 过短")
                continue

            stats["utterances"] += 1
            pcm = b"".join(utterance_frames)

            # ASR 转写
            print(f" - ASR处理中...", end="", flush=True)
            t0 = time.monotonic()
            result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
            asr_ms = (time.monotonic() - t0) * 1000
            text = result.text if result else ""

            if text:
                is_wake = wake_detector.detect(text)
                now = time.monotonic()

                if is_wake:
                    elapsed = now - last_wake_time
                    if elapsed < DUAL_CONFIRM_WINDOW:
                        wake_count += 1
                        last_wake_time = now
                        stats["wakes"] += 1
                        print(f"\n  🎯🎯 唤醒触发 #{wake_count}! \"{text}\" ASR={asr_ms:.0f}ms")
                    elif elapsed < WAKE_COOLDOWN:
                        print(f"\n  🗣️  \"{text}\" (冷却中 {WAKE_COOLDOWN - elapsed:.1f}s)")
                    else:
                        last_wake_time = now
                        print(f"\n  🗣️  \"{text}\" (首次命中)")
                else:
                    print(f"\n  🗣️  \"{text}\" ASR={asr_ms:.0f}ms")
            else:
                print(f" (ASR返回空)")

        elif stats["frames"] % 30 == 0:
            remaining = max(0, end_time - time.monotonic())
            bar_len = 20
            ratio = min(1.0, 1.0 - remaining / duration)
            filled = int(bar_len * ratio)
            bar = "█" * filled + "░" * (bar_len - filled)
            sys.stdout.write(f"\r  [{bar}] {remaining:.0f}s | 噪音~{noise_avg:.0f}RMS 等待语音...")
            sys.stdout.flush()

    source.close()

    print(f"\n\n{'='*60}")
    print("📊 测试结果")
    print(f"{'='*60}")
    print(f"  总帧数: {stats['frames']}")
    print(f"  语音帧: {stats['speech_frames']} ({stats['speech_frames']/max(1,stats['frames'])*100:.1f}%)")
    print(f"  捕获语音段: {stats['utterances']}")
    print(f"  唤醒触发: {stats['wakes']}")

    if stats["wakes"] > 0:
        print(f"\n  ✅ 唤醒功能验证通过!")
    elif stats["utterances"] > 0:
        print(f"\n  ⚠️  语音捕获正常 ({stats['utterances']} 段)，但未检测到唤醒词")
        print(f"     - 检查发音是否清晰")
        print(f"     - 尝试增大增益: python final_wake_test.py --gain 100")
    else:
        print(f"\n  ❌ 未检测到语音")
        print(f"     - 检查麦克风连接")
        print(f"     - 尝试增大增益: python final_wake_test.py --gain 100")
        print(f"     - 靠近麦克风说话")

if __name__ == "__main__":
    asyncio.run(main())