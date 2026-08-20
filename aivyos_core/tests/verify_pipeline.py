"""快速验证增益+VAD+ASR管道是否工作。"""
import asyncio
import struct
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import SileroVAD, EnergyVAD, _rms

SAMPLE_RATE = 16000
FRAME_MS = 32
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000

async def main():
    print("🔍 验证增益+VAD 管道\n")

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device=7, gain=50)
    silero = SileroVAD(sample_rate=SAMPLE_RATE, threshold=0.3)
    energy = EnergyVAD(threshold=100, frame_ms=FRAME_MS)

    print("   请对着麦克风说话...(10秒)\n")

    end_time = asyncio.get_event_loop().time() + 10
    frame_count = 0
    silero_hits = 0
    energy_hits = 0
    rms_values = []

    async for frame in source.stream():
        if asyncio.get_event_loop().time() > end_time:
            break

        frame_count += 1
        rms = _rms(frame)
        rms_values.append(rms)

        silero_hit = silero.is_speech(frame)
        energy_hit = energy.is_speech(frame)

        if silero_hit:
            silero_hits += 1
        if energy_hit:
            energy_hits += 1

        if frame_count % 10 == 0 or silero_hit or energy_hit:
            print(f"  帧{frame_count}: RMS={rms:.0f} | Silero={'✅' if silero_hit else '❌'} | Energy={'✅' if energy_hit else '❌'}")

    source.close()

    print(f"\n📊 统计:")
    print(f"  总帧数: {frame_count}")
    print(f"  RMS 范围: {min(rms_values):.0f} - {max(rms_values):.0f}")
    print(f"  RMS 平均: {sum(rms_values)/len(rms_values):.0f}")
    print(f"  Silero VAD 命中: {silero_hits}/{frame_count}")
    print(f"  Energy VAD 命中: {energy_hits}/{frame_count} (阈值=100)")

    if max(rms_values) > 50:
        print(f"\n  ✅ 音频信号充足 (max={max(rms_values):.0f})")
        if silero_hits == 0 and energy_hits == 0:
            print(f"  ⚠️ VAD 未检测到语音，可能需要调整阈值")
    else:
        print(f"\n  ❌ 音频信号不足 (max={max(rms_values):.0f})")
        print(f"  建议: 增大增益或靠近麦克风")

if __name__ == "__main__":
    asyncio.run(main())