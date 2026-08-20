"""音频诊断 — 检查不同增益下的音频质量和 ASR 表现。

逐步测试不同增益值，找到最佳参数。
"""
import asyncio
import sys
import os
import struct
import math
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource, _apply_gain
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.manager import create_asr

SAMPLE_RATE = 16000
FRAME_MS = 32
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000

async def test_gain(gain: float, duration: float = 5.0):
    """测试指定增益下的音频质量和 ASR 识别。"""
    print(f"\n  ── 增益 {gain}x ──")
    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS,
                       device="7", gain=gain)

    # 收集音频
    frames = []
    max_rms = 0
    min_rms = 999999
    sum_rms = 0
    count = 0

    end_time = time.monotonic() + duration
    async for frame in source.stream():
        if time.monotonic() > end_time:
            break
        frames.append(frame)
        rms = _rms(frame)
        max_rms = max(max_rms, rms)
        min_rms = min(min_rms, rms)
        sum_rms += rms
        count += 1

    source.close()

    avg_rms = sum_rms / max(1, count)
    total_pcm = b"".join(frames)

    # 检查削波比例
    n_samples = len(total_pcm) // 2
    clip_count = 0
    for i in range(n_samples):
        (v,) = struct.unpack_from("<h", total_pcm, i * 2)
        if abs(v) > 32000:
            clip_count += 1
    clip_pct = clip_count / max(1, n_samples) * 100

    print(f"    帧数: {count} | 时长: {count * FRAME_MS / 1000:.1f}s")
    print(f"    RMS: min={min_rms:.0f} avg={avg_rms:.0f} max={max_rms:.0f}")
    print(f"    削波: {clip_pct:.1f}% ({clip_count}/{n_samples})")

    # 如果有语音，用 ASR 转写
    if max_rms > 20:
        asr = create_asr({})
        result = await asyncio.to_thread(asr.transcribe, total_pcm, SAMPLE_RATE)
        text = result.text if result else ""
        print(f"    ASR: \"{text.strip()}\"")
    else:
        print(f"    ASR: (无语音)")

    return {"gain": gain, "max_rms": max_rms, "avg_rms": avg_rms,
            "clip_pct": clip_pct, "frames": count}


async def main():
    print("=" * 60)
    print("🔍 音频诊断 — 增益扫描")
    print("=" * 60)
    print("\n  将依次测试增益: 10x, 20x, 30x, 50x, 70x")
    print("  请对着麦克风正常说话...")
    print()

    gains = [10, 20, 30, 50, 70]
    results = []

    for gain in gains:
        r = await test_gain(float(gain), duration=4.0)
        results.append(r)
        await asyncio.sleep(0.5)

    print(f"\n{'='*60}")
    print("📊 汇总对比")
    print(f"{'='*60}")
    print(f"  {'增益':<8} {'avgRMS':<8} {'maxRMS':<8} {'削波%':<8} {'评价'}")
    print(f"  {'─'*48}")
    for r in results:
        score = ""
        if r['clip_pct'] > 10:
            score = "❌ 严重削波"
        elif r['max_rms'] > 5000:
            score = "⚠️  削波风险"
        elif r['avg_rms'] > 50:
            score = "✅ 良好"
        elif r['avg_rms'] > 20:
            score = "👌 可用"
        else:
            score = "🔇 太弱"
        print(f"  {r['gain']:<8.0f} {r['avg_rms']:<8.0f} {r['max_rms']:<8.0f} {r['clip_pct']:<8.1f} {score}")

    # 推荐最佳增益
    best = max([r for r in results if r['clip_pct'] < 5],
               key=lambda r: r['avg_rms'], default=None)
    if best:
        print(f"\n  ⭐ 推荐增益: {best['gain']:.0f}x (avgRMS={best['avg_rms']:.0f}, maxRMS={best['max_rms']:.0f}, 削波={best['clip_pct']:.1f}%)")
    else:
        print(f"\n  ⚠️  所有增益都有削波，建议降低说话音量或远离麦克风")

if __name__ == "__main__":
    asyncio.run(main())