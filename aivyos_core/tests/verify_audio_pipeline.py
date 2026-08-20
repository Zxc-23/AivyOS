"""综合音频验证 — 保存麦克风音频到 WAV，并验证 ASR 管道。

此脚本:
1. 录制 5 秒麦克风音频 (增益 50x)
2. 保存到 WAV 文件供回放
3. 同时用 ASR 转写
4. 计算音频统计数据

用户可以回放 WAV 文件确认麦克风是否正常工作。
"""
import asyncio
import sys
import os
import struct
import wave
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.manager import create_asr

SAMPLE_RATE = 16000
FRAME_MS = 32
GAIN = 50.0
DEVICE = "7"
RECORD_SECONDS = 5
OUTPUT_WAV = os.path.join(os.path.dirname(__file__), "test_capture.wav")

async def main():
    print("=" * 60)
    print("🎙️  综合音频验证")
    print("=" * 60)

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS,
                       device=DEVICE, gain=GAIN)

    print(f"\n  增益: {GAIN}x | 设备: {DEVICE}")
    print(f"  录制: {RECORD_SECONDS}s")
    print(f"\n  ⚠️  请在录制期间对着麦克风说话!")
    print(f"     建议说: '你好艾薇，今天天气怎么样'")
    print()

    for i in range(3, 0, -1):
        print(f"  {i}...", flush=True)
        await asyncio.sleep(1)
    print("  🎤 录制中...\n")

    # 录制音频
    frames = []
    max_rms = 0
    min_rms = 999999
    sum_rms = 0
    rms_values = []

    end_time = time.monotonic() + RECORD_SECONDS
    async for frame in source.stream():
        if time.monotonic() > end_time:
            break
        frames.append(frame)
        rms = _rms(frame)
        rms_values.append(rms)
        max_rms = max(max_rms, rms)
        min_rms = min(min_rms, rms)
        sum_rms += rms

    source.close()

    avg_rms = sum_rms / max(1, len(rms_values))
    total_pcm = b"".join(frames)
    total_samples = len(total_pcm) // 2
    duration = total_samples / SAMPLE_RATE

    print(f"  ✅ 录制完成: {duration:.1f}s, {total_samples} 采样点")
    print(f"     RMS: min={min_rms:.0f} avg={avg_rms:.0f} max={max_rms:.0f}")

    # 统计削波
    clip_count = 0
    for i in range(total_samples):
        (v,) = struct.unpack_from("<h", total_pcm, i * 2)
        if abs(v) > 32000:
            clip_count += 1
    clip_pct = clip_count / max(1, total_samples) * 100
    print(f"     削波: {clip_pct:.2f}% ({clip_count}/{total_samples})")

    # 统计静音/语音帧
    silent_frames = sum(1 for r in rms_values if r < 10)
    quiet_frames = sum(1 for r in rms_values if 10 <= r < 50)
    loud_frames = sum(1 for r in rms_values if r >= 50)
    print(f"     帧分布: 静音(<10)={silent_frames} 安静(10-50)={quiet_frames} 响亮(>=50)={loud_frames}")

    # 保存 WAV
    print(f"\n  💾 保存到 {OUTPUT_WAV}...")
    with wave.open(OUTPUT_WAV, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(total_pcm)
    print(f"     ✅ 已保存 ({len(total_pcm)} bytes)")

    # ASR 转写
    print(f"\n  ⏳ ASR 转写中...")
    asr = create_asr({})
    result = await asyncio.to_thread(asr.transcribe, total_pcm, SAMPLE_RATE)
    text = result.text if result else ""
    print(f"     📝 ASR 结果: \"{text.strip()}\"")
    print(f"     📊 置信度: {result.confidence if result else 'N/A'}")

    # 诊断
    print(f"\n{'='*60}")
    print("🔍 诊断")
    print(f"{'='*60}")

    issues = []
    if max_rms < 50:
        issues.append("❌ 峰值信号太弱 (< 50 RMS)，增益可能不足")
    elif clip_pct > 5:
        issues.append("❌ 削波严重 (> 5%)，增益过高或声音太大")
    else:
        print("  ✅ 信号电平正常")

    if not text or text.strip() in ("", "。", ".", "嗯", "啊"):
        issues.append("❌ ASR 未识别到有效语音内容")
        if max_rms < 100:
            issues.append("   → 可能原因: 说话声音太小或距离太远")
        if clip_pct > 10:
            issues.append("   → 可能原因: 音频削波导致 ASR 无法识别")
    else:
        print(f"  ✅ ASR 识别成功: \"{text.strip()}\"")

    if issues:
        print("\n  🚨 发现问题:")
        for issue in issues:
            print(f"    {issue}")
        print(f"\n  💡 建议:")
        print(f"    1. 距离麦克风 30-50cm")
        print(f"    2. 以正常音量说话")
        print(f"    3. 清楚地说出完整句子，如 '你好艾薇'")
        print(f"    4. 确认麦克风已正确连接")
    else:
        print("\n  🎉 音频管道完全正常!")

    print(f"\n  📁 音频已保存: {OUTPUT_WAV}")
    print(f"     请用播放器回放确认麦克风录制是否清晰")

if __name__ == "__main__":
    asyncio.run(main())