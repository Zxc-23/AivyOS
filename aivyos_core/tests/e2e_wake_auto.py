"""端到端唤醒验证 — 自动模式（无需手动按回车）。

自动开始测试，用户直接对着麦克风说唤醒词即可。
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.manager import create_asr
from aivyos_core.wake import WakeWordDetector

SAMPLE_RATE = 16000
FRAME_MS = 32
WINDOW_SECONDS = 1.5
GAIN = 100.0
DEVICE = "7"
DURATION = 20.0

async def main():
    print("=" * 60)
    print("🎯 AivyOS 端到端唤醒验证 (自动模式)")
    print("=" * 60)
    print(f"\n  唤醒词: {', '.join(WakeWordDetector().words)}")
    print(f"  增益: {GAIN}x | 设备: {DEVICE} | 时长: {DURATION}s")
    print(f"  窗口: {WINDOW_SECONDS}s/次")
    print(f"\n  ⚠️  请在倒计时结束后对着麦克风说唤醒词!")
    print(f"     推荐说: '艾薇' 或 'Aivy'")
    sys.stdout.flush()

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS,
                       device=DEVICE, gain=GAIN)

    print("\n  ⏳ 加载 ASR 模型...", flush=True)
    asr = create_asr({})
    print("  ✅ ASR 就绪", flush=True)

    wake_detector = WakeWordDetector()

    print("  📻 校准中 (2秒)...", flush=True)
    cal_rms = []
    cal_end = asyncio.get_event_loop().time() + 2.0
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > cal_end:
            break
        cal_rms.append(_rms(frame))
    noise_avg = sum(cal_rms) / max(1, len(cal_rms))
    print(f"  ✅ 噪声: {noise_avg:.1f}RMS", flush=True)

    for i in range(3, 0, -1):
        print(f"  {i}...", flush=True)
        await asyncio.sleep(1)
    print("  🎤 开始!\n", flush=True)

    print("  📢 请说: '艾薇' 或 'Aivy'\n", flush=True)

    end_time = time.monotonic() + DURATION
    window_frames = []
    window_start = time.monotonic()
    wakes = 0
    utterances = 0
    max_rms_overall = 0

    async for frame in source.stream():
        if time.monotonic() > end_time:
            break

        window_frames.append(frame)
        now = time.monotonic()

        if (now - window_start) >= WINDOW_SECONDS:
            if len(window_frames) < 10:
                window_frames = []
                window_start = now
                continue

            pcm = b"".join(window_frames)
            max_rms = max(_rms(f) for f in window_frames)
            max_rms_overall = max(max_rms_overall, max_rms)

            result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
            text = result.text if result else ""

            if text and text.strip():
                is_wake = wake_detector.detect(text)
                utterances += 1

                if is_wake:
                    wakes += 1
                    print(f"\n  🎯🎯🎯 唤醒触发! #{wakes}")
                    print(f"     识别结果: \"{text.strip()}\"")
                    print(f"     峰值RMS: {max_rms:.0f}")
                    elapsed = DURATION - (end_time - time.monotonic())
                    print(f"     时间: {elapsed:.1f}s")
                else:
                    print(f"\n  📝 \"{text.strip()}\" (RMS={max_rms:.0f})")
            else:
                elapsed = DURATION - (end_time - time.monotonic())
                bar_len = 20
                filled = int(bar_len * (elapsed / DURATION))
                bar = "█" * filled + "░" * (bar_len - filled)
                sys.stdout.write(f"\r  [{bar}] {elapsed:5.1f}s | RMS={max_rms:.0f} | 等待语音...")
                sys.stdout.flush()

            window_frames = []
            window_start = now

    source.close()

    print(f"\n\n{'='*60}")
    print("📊 测试结果")
    print(f"{'='*60}")
    print(f"  总时长: {DURATION}s")
    print(f"  有效语音段: {utterances}")
    print(f"  唤醒触发: {wakes}")
    print(f"  峰值RMS: {max_rms_overall:.0f}")
    print(f"  噪声RMS: {noise_avg:.1f}")

    if wakes > 0:
        print(f"\n  🎉 唤醒功能验证通过! ({wakes} 次触发)")
    elif utterances > 0:
        print(f"\n  ⚠️  语音捕获正常 ({utterances} 段)，但未检测到唤醒词")
        print(f"     建议: 更大声、更清晰地说 '艾薇'")
        print(f"     当前 ASR 识别的内容中没有匹配唤醒词")
    else:
        print(f"\n  ❌ 未检测到有效语音")
        print(f"     建议: 检查麦克风距离 (30-50cm) 和音量")

if __name__ == "__main__":
    asyncio.run(main())