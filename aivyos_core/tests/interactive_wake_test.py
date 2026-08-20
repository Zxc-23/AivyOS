"""交互式唤醒测试 — 用户确认后开始，带倒计时和预校准。

用法: python interactive_wake_test.py
     python interactive_wake_test.py --gain 100 --duration 60
"""
import asyncio
import sys
import os
import struct
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource, _apply_gain
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

def frame_rms(frame):
    n = len(frame) // 2
    if n == 0: return 0.0
    acc = 0
    for i in range(n):
        (s,) = struct.unpack_from("<h", frame, i * 2)
        acc += s * s
    return (acc / n) ** 0.5

async def calibrate_noise(source, duration_s=2.0):
    """预校准：采集环境噪声电平。"""
    print(f"  📻 正在校准环境噪声 ({duration_s:.0f}s)...", end="", flush=True)
    end = asyncio.get_event_loop().time() + duration_s
    rms_values = []
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > end:
            break
        rms_values.append(_rms(frame))
    avg = sum(rms_values) / max(1, len(rms_values))
    peak = max(rms_values) if rms_values else 0
    threshold = max(30, min(500, int(avg * 2)))
    print(f" 噪声均值={avg:.1f}RMS 峰值={peak:.1f}RMS VAD阈值={threshold}")
    return threshold, avg

async def capture_utterance(source, vad):
    """捕获完整语音段。"""
    frames = []
    silence_count = 0
    start_time = time.monotonic()

    async for frame in source.stream():
        elapsed = time.monotonic() - start_time
        if elapsed > UTTERANCE_TIMEOUT:
            break

        frames.append(frame)

        if vad.is_speech(frame):
            silence_count = 0
        else:
            silence_count += 1
            if silence_count >= SILENCE_HOLD_FRAMES:
                break

    if len(frames) < MIN_UTTERANCE_FRAMES:
        return None

    return b"".join(frames)

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--gain", type=float, default=50.0, help="软件增益")
    parser.add_argument("--duration", type=float, default=60.0, help="测试时长")
    parser.add_argument("--device", type=str, default="7", help="设备索引")
    parser.add_argument("--vad", choices=["silero", "energy"], default="energy", help="VAD类型")
    args = parser.parse_args()

    print("=" * 60)
    print("🎙️  AivyOS 交互式唤醒测试")
    print("=" * 60)
    print(f"\n  配置: gain={args.gain}x, duration={args.duration:.0f}s, device={args.device}, vad={args.vad}")
    print(f"  唤醒词: {', '.join(WakeWordDetector().words)}")
    print(f"\n  请准备好，测试开始后请对着麦克风说唤醒词...")

    input("\n  按回车键开始测试...")

    # 倒计时
    for i in range(3, 0, -1):
        print(f"  {i}...")
        await asyncio.sleep(1)

    print("  开始！\n")

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device=args.device, gain=args.gain)

    # 预校准
    threshold, noise_avg = await calibrate_noise(source, 2.0)

    if args.vad == "silero":
        vad = SileroVAD(sample_rate=SAMPLE_RATE, threshold=0.2)
    else:
        vad = EnergyVAD(threshold=threshold, frame_ms=FRAME_MS, auto_calibrate=False)

    wake_detector = WakeWordDetector()
    asr = create_asr({})

    print(f"\n  ⏳ 加载 ASR 模型...", end="", flush=True)
    asr = create_asr({})
    print(f" 就绪\n")

    print(f"  🎤 请说唤醒词（{args.duration:.0f}s 内）:\n")

    end_time = time.monotonic() + args.duration
    stats = {"frames": 0, "speech": 0, "utterances": 0, "wakes": 0, "asr_calls": 0}
    last_wake_time = 0.0
    wake_count = 0

    while time.monotonic() < end_time:
        remaining = end_time - time.monotonic()

        async for frame in source.stream():
            if time.monotonic() > end_time:
                break

            stats["frames"] += 1
            rms = _rms(frame)

            if vad.is_speech(frame):
                stats["speech"] += 1
                print(f"  🔊 检测到语音 (RMS={rms:.0f})", end="", flush=True)

                pcm = await capture_utterance(source, vad)
                if pcm is None:
                    print(" - 过短，忽略")
                    continue

                stats["utterances"] += 1
                stats["asr_calls"] += 1

                t0 = time.monotonic()
                result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
                asr_time = (time.monotonic() - t0) * 1000
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
                            print(f"\n  🎯 **唤醒触发!** \"{text}\" (ASR:{asr_time:.0f}ms) {'🔥' * wake_count}")
                        elif elapsed < WAKE_COOLDOWN:
                            print(f"\n  🗣️  \"{text}\" (冷却中)")
                        else:
                            last_wake_time = now
                            print(f"\n  🗣️  \"{text}\" (首次命中，等待确认...)")
                    else:
                        print(f"\n  🗣️  \"{text}\" (ASR:{asr_time:.0f}ms)")
                else:
                    print(f" (ASR返回空)")

                break  # 回到外层循环检查时间

            elif stats["frames"] % 50 == 0:
                bar_len = 20
                ratio = min(1.0, (args.duration - remaining) / args.duration)
                filled = int(bar_len * ratio)
                bar = "█" * filled + "░" * (bar_len - filled)
                print(f"\r  [{bar}] {remaining:.0f}s | 噪音~{noise_avg:.0f}RMS | 等待语音...", end="", flush=True)

    source.close()

    print(f"\n\n{'='*60}")
    print("📊 测试结果")
    print(f"{'='*60}")
    print(f"  总帧数: {stats['frames']}")
    print(f"  语音帧: {stats['speech']} ({stats['speech']/max(1,stats['frames'])*100:.1f}%)")
    print(f"  捕获语音段: {stats['utterances']}")
    print(f"  ASR 调用: {stats['asr_calls']}")
    print(f"  唤醒触发: {stats['wakes']}")

    if stats["wakes"] > 0:
        print(f"\n  ✅ 唤醒功能验证通过！共触发 {stats['wakes']} 次")
    elif stats["utterances"] > 0:
        print(f"\n  ⚠️ 语音捕获正常 ({stats['utterances']} 段)，但未检测到唤醒词")
        print(f"     建议: 增大音量、靠近麦克风、或检查发音")
    else:
        print(f"\n  ❌ 未检测到语音")
        print(f"     建议: 检查麦克风连接、提高增益、或对着麦克风更近说话")

if __name__ == "__main__":
    asyncio.run(main())