"""增益测试 — 验证软件增益是否能将微弱麦克风信号放大到可用电平。"""
import asyncio
import struct
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource, _apply_gain

SAMPLE_RATE = 16000
FRAME_MS = 32
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000

def frame_rms(frame):
    n = len(frame) // 2
    if n == 0: return 0.0
    acc = 0
    for i in range(n):
        (s,) = struct.unpack_from("<h", frame, i * 2)
        acc += s * s
    return (acc / n) ** 0.5

async def main():
    print("🎤 增益测试 — 验证软件增益效果\n")

    gains = [1, 5, 10, 20, 50]

    for gain in gains:
        print(f"\n  测试 gain={gain}x ...")
        source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device=7, gain=gain)

        duration_s = 3.0
        end_time = asyncio.get_event_loop().time() + duration_s
        rms_values = []

        try:
            async for frame in source.stream():
                if asyncio.get_event_loop().time() > end_time:
                    break
                rms = frame_rms(frame)
                rms_values.append(rms)
        except Exception as e:
            print(f"    错误: {e}")
            continue

        source.close()

        if rms_values:
            avg_rms = sum(rms_values) / len(rms_values)
            max_rms = max(rms_values)
            frames_speech = sum(1 for r in rms_values if r > 50)
            print(f"    RMS: avg={avg_rms:.1f} max={max_rms:.1f}")
            print(f"    语音帧(>50): {frames_speech}/{len(rms_values)} ({frames_speech/len(rms_values)*100:.1f}%)")

            if max_rms > 500:
                print(f"    ✅ 信号充足 (max={max_rms:.0f})")
            elif max_rms > 100:
                print(f"    ✅ 信号可用 (max={max_rms:.0f})")
            elif max_rms > 10:
                print(f"    ⚠️ 信号偏弱 (max={max_rms:.0f})")
            else:
                print(f"    ❌ 信号不足 (max={max_rms:.0f})")

    print(f"\n💡 建议: 选择 max_rms 在 100-1000 范围内的增益值")

if __name__ == "__main__":
    asyncio.run(main())