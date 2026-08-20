"""快速VAD验证 — 使用改进的阈值参数。"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import SileroVAD, EnergyVAD, _rms

async def main():
    source = MicSource(sample_rate=16000, frame_ms=32, device=7, gain=50)
    energy = EnergyVAD(threshold=50, frame_ms=32)
    silero = SileroVAD(sample_rate=16000, threshold=0.2)

    print("测试 VAD (10秒，请说话)...\n")
    end = asyncio.get_event_loop().time() + 10
    cnt = 0
    e_hits = 0
    s_hits = 0

    async for frame in source.stream():
        if asyncio.get_event_loop().time() > end:
            break
        cnt += 1
        rms = _rms(frame)
        e = energy.is_speech(frame)
        s = silero.is_speech(frame)
        if e:
            e_hits += 1
        if s:
            s_hits += 1

        if cnt % 10 == 0 or e or s:
            print(f"  帧{cnt}: RMS={rms:.0f} | Energy={'✅' if e else '❌'}({energy.threshold}) | Silero={'✅' if s else '❌'}")

    source.close()
    print(f"\n结果: Energy命中={e_hits}/{cnt}, Silero命中={s_hits}/{cnt}")

if __name__ == "__main__":
    asyncio.run(main())