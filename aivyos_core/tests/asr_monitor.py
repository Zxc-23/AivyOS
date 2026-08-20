"""ASR 实时监控 — 直接转写麦克风输入，验证音频捕获和 ASR 是否工作。

这是最简单的测试：直接将麦克风音频送给 ASR 转写，不使用 VAD 或唤醒词检测。
用法: python asr_monitor.py [--gain 100] [--duration 30] [--device 7]
"""
import asyncio
import sys
import os
import struct
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.manager import create_asr

SAMPLE_RATE = 16000
FRAME_MS = 32
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000

async def main():
    gain = float(sys.argv[sys.argv.index("--gain") + 1]) if "--gain" in sys.argv else 100.0
    duration = float(sys.argv[sys.argv.index("--duration") + 1]) if "--duration" in sys.argv else 30.0
    device = sys.argv[sys.argv.index("--device") + 1] if "--device" in sys.argv else "7"

    print("=" * 60)
    print("🎤  ASR 实时监控 — 直接转写麦克风")
    print("=" * 60)
    print(f"\n  参数: gain={gain}x, duration={duration:.0f}s, device={device}")
    print(f"\n  ⚠️  此脚本直接将所有音频送给 ASR，可能产生较高 CPU 占用")
    print(f"  💡  请对着麦克风说话，ASR 会实时转写\n")

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device=device, gain=gain)

    print("  ⏳ 加载 ASR 模型...", flush=True)
    asr = create_asr({})
    print("  ✅ ASR 就绪\n")

    # 预校准 2 秒
    print("  📻 校准中 (2秒，请保持安静)...", flush=True)
    cal_rms = []
    cal_end = asyncio.get_event_loop().time() + 2.0
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > cal_end:
            break
        cal_rms.append(_rms(frame))
    noise_avg = sum(cal_rms) / max(1, len(cal_rms))
    noise_peak = max(cal_rms) if cal_rms else 0
    print(f"  ✅ 噪声: 均值={noise_avg:.1f}RMS, 峰值={noise_peak:.1f}RMS\n")

    # 倒计时
    for i in [3, 2, 1]:
        print(f"    {i}...")
        await asyncio.sleep(0.5)

    print(f"\n  🎤 开始说话! (ASR 实时转写)\n")

    end_time = time.monotonic() + duration
    chunk_frames = []
    chunk_start = time.monotonic()
    chunk_max_rms = 0

    while time.monotonic() < end_time:
        async for frame in source.stream():
            if time.monotonic() > end_time:
                break

            rms = _rms(frame)
            chunk_frames.append(frame)
            chunk_max_rms = max(chunk_max_rms, rms)

            # 每 1.5 秒处理一次音频
            elapsed = time.monotonic() - chunk_start
            if elapsed >= 1.5 and len(chunk_frames) >= 10:
                pcm = b"".join(chunk_frames)
                print(f"  🔄 处理 {len(chunk_frames)} 帧 ({elapsed:.1f}s), max_RMS={chunk_max_rms:.0f}...", end="", flush=True)

                t0 = time.monotonic()
                result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
                asr_ms = (time.monotonic() - t0) * 1000
                text = result.text if result else ""

                if text and text.strip():
                    print(f"\n  📝 \"{text.strip()}\" (ASR={asr_ms:.0f}ms)")
                else:
                    print(f" (无语音)")

                chunk_frames = []
                chunk_start = time.monotonic()
                chunk_max_rms = 0

    # 处理剩余帧
    if chunk_frames:
        pcm = b"".join(chunk_frames)
        result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
        text = result.text if result else ""
        if text and text.strip():
            print(f"\n  📝 \"{text.strip()}\" (尾部)")

    source.close()
    print(f"\n  ✅ 测试完成")

if __name__ == "__main__":
    asyncio.run(main())