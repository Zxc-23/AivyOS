"""自动录制 30 秒麦克风音频并保存 — 用于离线验证。

运行后自动录制 30 秒音频，处理并保存所有语音段。
用户可之后回放保存的 WAV 文件验证 ASR 识别质量。
"""
import asyncio
import sys
import os
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.manager import create_asr
from aivyos_core.wake import WakeWordDetector
from aivyos_core.asr.funasr_backend import _has_speech

SAMPLE_RATE = 16000
FRAME_MS = 32
WINDOW_SECONDS = 1.0
SILENCE_THRESHOLD = 20.0
DURATION = 30.0

SAVE_DIR = os.path.join(os.path.dirname(__file__), "captured_e2e")


def save_wav(path: str, pcm: bytes, sr: int = 16000):
    """保存 PCM 数据为 WAV 文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm)


async def main():
    print("=" * 60)
    print("🎙️ 自动录制模式 — 30 秒音频捕获")
    print("=" * 60)
    print(f"\n  请准备在倒计时结束后说话!")
    print(f"  唤醒词: {', '.join(WakeWordDetector().words)}")

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device="7", gain=100.0)

    print("  ⏳ 加载 ASR 模型...", flush=True)
    asr = create_asr({"silence_threshold": SILENCE_THRESHOLD, "silence_min_ratio": 0.05})
    wake_detector = WakeWordDetector()
    print("  ✅ ASR 就绪\n")

    print("  📻 校准 2 秒...", flush=True)
    cal_rms = []
    cal_end = asyncio.get_event_loop().time() + 2.0
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > cal_end:
            break
        cal_rms.append(_rms(frame))
    noise_avg = sum(cal_rms) / max(1, len(cal_rms))
    print(f"  ✅ 噪声基线: {noise_avg:.1f}RMS\n")

    for i in range(3, 0, -1):
        print(f"  {i}...", flush=True)
        await asyncio.sleep(1)

    print(f"\n  🎤 录制中... 请说话! (30 秒)")
    print(f"  提示: 说 '你好艾薇' 或 'Aivy' 等\n")

    test_start = time.monotonic()
    end_time = test_start + DURATION
    window_frames = []
    window_start = test_start
    saved_count = 0
    filtered = 0
    wakes = 0
    max_rms_overall = 0

    async for frame in source.stream():
        if time.monotonic() > end_time:
            break

        window_frames.append(frame)
        now = time.monotonic()
        frame_rms = _rms(frame)
        max_rms_overall = max(max_rms_overall, frame_rms)
        elapsed = now - test_start

        if int(elapsed) % 5 == 0 and int(elapsed) > 0:
            sys.stdout.write(f"\r  ⏱️  {elapsed:5.1f}s/{DURATION:.0f}s  当前RMS={frame_rms:3.0f}  | 已保存语音段: {saved_count}  ")
            sys.stdout.flush()

        if (now - window_start) >= WINDOW_SECONDS:
            if len(window_frames) < 10:
                window_frames = []
                window_start = now
                continue

            pcm = b"".join(window_frames)
            max_rms = max(_rms(f) for f in window_frames)

            has_speech = _has_speech(pcm, SILENCE_THRESHOLD)

            if not has_speech:
                filtered += 1
                window_frames = []
                window_start = now
                continue

            result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
            text = result.text if result else ""

            if text and text.strip():
                segment_path = os.path.join(SAVE_DIR, f"speech_{saved_count:02d}_{max_rms:.0f}rms.wav")
                save_wav(segment_path, pcm)
                saved_count += 1

                is_wake = wake_detector.detect(text)
                if is_wake:
                    wakes += 1
                    print(f"\n  🎯 唤醒触发! #{wakes} | \"{text.strip()}\" | RMS={max_rms:.0f}")
                else:
                    print(f"\n  📝 \"{text.strip()}\" (RMS={max_rms:.0f})")
                    if saved_count <= 5:
                        print(f"     💡 唤醒词不匹配，请尝试: '艾薇' 或 'Aivy'")
            else:
                filtered += 1

            window_frames = []
            window_start = now

    source.close()

    print(f"\n\n{'='*60}")
    print("📊 录制结果")
    print(f"{'='*60}")
    print(f"  时长: {DURATION:.1f}s")
    print(f"  保存语音段: {saved_count}")
    print(f"  过滤噪音段: {filtered}")
    print(f"  唤醒触发: {wakes}")
    print(f"  峰值RMS: {max_rms_overall:.0f}")
    print(f"  噪声RMS: {noise_avg:.1f}")

    if saved_count > 0:
        print(f"\n  📁 保存的音频: {SAVE_DIR}/")
        for f in sorted(os.listdir(SAVE_DIR)):
            filepath = os.path.join(SAVE_DIR, f)
            file_rms = _rms_energy(open(filepath, "rb").read())
            print(f"     {f}  (文件RMS={file_rms:.0f})")

    if wakes > 0:
        print(f"\n  🎉 唤醒功能验证通过!")
    elif saved_count > 0:
        print(f"\n  ⚠️  有 {saved_count} 段有效语音被识别，但未检测到唤醒词")
        print(f"     请听保存的音频，确认:")
        print(f"     1. 是否是你说的话")
        print(f"     2. ASR 识别是否准确")
    else:
        print(f"\n  ❌ 未检测到有效语音")
        print(f"     建议: 检查麦克风设置，确保能正常采集音频")

if __name__ == "__main__":
    asyncio.run(main())