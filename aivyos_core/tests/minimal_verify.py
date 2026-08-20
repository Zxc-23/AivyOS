"""最小化验证脚本 — 直接测试 _has_speech + ASR。"""
import asyncio, sys, os, wave, struct, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.manager import create_asr
from aivyos_core.asr.funasr_backend import _has_speech, _rms_energy

SAMPLE_RATE = 16000
FRAME_MS = 32

async def main():
    print("=" * 60)
    print("🔬 最小化验证")
    print("=" * 60)

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device="7", gain=100.0)
    print("  ✅ 麦克风已打开")

    print("  🔄 加载 ASR...")
    asr = create_asr({"silence_threshold": 20.0})
    print("  ✅ ASR 已加载")

    print("\n  ⏳ 校准 2 秒 (请保持安静)...")
    cal_rms = []
    cal_end = asyncio.get_event_loop().time() + 2.0
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > cal_end:
            break
        cal_rms.append(_rms(frame))
    noise_rms = sum(cal_rms) / max(1, len(cal_rms))
    print(f"  噪声 RMS: {noise_rms:.1f}")

    # 录制 3 个 1 秒窗口
    windows = []
    for i in range(3):
        print(f"\n  第 {i+1}/3 个窗口 — 请说话!")
        frames = []
        win_start = time.monotonic()
        async for frame in source.stream():
            if time.monotonic() - win_start >= 1.0:
                break
            frames.append(frame)
        pcm = b"".join(frames)
        windows.append(pcm)
        
        rms = _rms_energy(pcm)
        hs = _has_speech(pcm, 20.0)
        print(f"    RMS={rms:.1f}  _has_speech(20)={hs}")

    # 处理每个窗口
    for i, pcm in enumerate(windows):
        print(f"\n  ─── 处理窗口 {i+1} ───")
        rms = _rms_energy(pcm)
        
        if not _has_speech(pcm, 20.0):
            print(f"    ❌ _has_speech 过滤掉 (RMS={rms:.1f})")
            continue
        
        print(f"    ✅ 通过 _has_speech (RMS={rms:.1f})")
        
        print(f"    调用 ASR...")
        result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
        text = result.text if result else ""
        print(f"    ASR 返回 text='{text}'")
        print(f"    text truthy={bool(text and text.strip())}")

    source.close()
    print("\n  ✅ 完成")

if __name__ == "__main__":
    asyncio.run(main())