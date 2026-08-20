"""端到端唤醒验证 — 交互模式 v2。

用户按回车开始测试，然后对着麦克风说唤醒词。
集成了多级语音预过滤、实时音量显示和音频保存功能。

用法: python e2e_wake_test.py
"""
import asyncio
import sys
import os
import struct
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.manager import create_asr
from aivyos_core.wake import WakeWordDetector
from aivyos_core.asr.funasr_backend import _has_speech, _rms_energy

SAMPLE_RATE = 16000
FRAME_MS = 32
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000
WINDOW_SECONDS = 1.5
WINDOW_OVERLAP = 0.5  # 50% 重叠，避免截断语音
SILENCE_THRESHOLD = 20.0

SAVE_DIR = os.path.join(os.path.dirname(__file__), "captured_e2e")


def volume_bar(rms: float, width: int = 20, max_rms: float = 500.0) -> str:
    """生成实时音量条字符串。"""
    ratio = min(rms / max_rms, 1.0)
    filled = int(ratio * width)
    if ratio > 0.7:
        color = "\033[91m"
    elif ratio > 0.4:
        color = "\033[93m"
    else:
        color = "\033[92m"
    reset = "\033[0m"
    return f"{color}[{'█' * filled}{'░' * (width - filled)}]{reset}"


def save_wav(path: str, pcm: bytes, sample_rate: int = 16000):
    """保存 PCM 数据为 WAV 文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


async def main():
    print("=" * 60)
    print("🎯 AivyOS 端到端唤醒验证 (v2)")
    print("=" * 60)
    wake = WakeWordDetector()
    print(f"\n  唤醒词: {', '.join(wake.words)}")
    print(f"  窗口: {WINDOW_SECONDS}s | 静音阈值: {SILENCE_THRESHOLD}RMS")
    print(f"  提示: 说话时看着音量条，确保进入黄色/红色区域")

    input("\n  准备好后按回车开始...")

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device="7", gain=1.0)

    print("  ⏳ 加载 ASR 模型...", flush=True)
    asr = create_asr({"silence_threshold": SILENCE_THRESHOLD, "silence_min_ratio": 0.05})
    print("  ✅ ASR 就绪\n")

    wake_detector = WakeWordDetector()

    print("  📻 校准中 (请保持安静 2 秒)...", flush=True)
    cal_rms = []
    cal_end = asyncio.get_event_loop().time() + 2.0
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > cal_end:
            break
        cal_rms.append(_rms(frame))
    noise_avg = sum(cal_rms) / max(1, len(cal_rms))
    noise_max = max(cal_rms) if cal_rms else 0
    
    # 自适应增益: 如果噪声 RMS < 30，自动放大到合理范围
    if noise_avg < 30:
        auto_gain = max(1.0, min(5.0, 30.0 / max(noise_avg, 1.0)))
        print(f"  📈 检测到低噪声 RMS={noise_avg:.1f}，自动调整增益 {auto_gain:.1f}x")
        source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device="7", gain=auto_gain)
        # 重新校准
        cal_rms = []
        cal_end = asyncio.get_event_loop().time() + 1.0
        async for frame in source.stream():
            if asyncio.get_event_loop().time() > cal_end:
                break
            cal_rms.append(_rms(frame))
        noise_avg = sum(cal_rms) / max(1, len(cal_rms))
        noise_max = max(cal_rms) if cal_rms else 0
    
    print(f"  ✅ 噪声基线: {noise_avg:.1f}RMS (峰值 {noise_max:.0f})")

    print("  3... 2... 1... 🎤 开始!\n")
    print("  === 请清晰地说: '你好艾薇' 或 '艾薇' 或 'Aivy' ===\n")

    duration = 30.0
    test_start = time.monotonic()
    end_time = test_start + duration
    window_frames = []
    window_start = test_start
    wakes = 0
    utterances = 0
    filtered = 0
    max_rms_overall = 0
    saved_count = 0
    overlap_frames = int(WINDOW_OVERLAP * 1000 / FRAME_MS)
    last_wake_text = ""  # 用于去重
    last_wake_time = 0.0  # 用于去重（冷却期）
    WAKE_DEDUP_SECONDS = 1.0  # 同一唤醒词的冷却时间

    async for frame in source.stream():
        if time.monotonic() > end_time:
            break

        window_frames.append(frame)
        now = time.monotonic()

        frame_rms = _rms(frame)
        max_rms_overall = max(max_rms_overall, frame_rms)

        bar = volume_bar(frame_rms)
        elapsed = now - test_start
        sys.stdout.write(f"\r  {bar} {elapsed:5.1f}s/{duration:.0f}s RMS={frame_rms:3.0f}   ")
        sys.stdout.flush()

        if (now - window_start) >= WINDOW_SECONDS:
            if len(window_frames) < 10:
                window_frames = window_frames[-overlap_frames:] if overlap_frames > 0 else []
                window_start = now - WINDOW_OVERLAP
                continue

            pcm = b"".join(window_frames)
            max_rms = max(_rms(f) for f in window_frames)

            has_speech = _has_speech(pcm, SILENCE_THRESHOLD)

            if not has_speech:
                filtered += 1
                window_frames = window_frames[-overlap_frames:] if overlap_frames > 0 else []
                window_start = now - WINDOW_OVERLAP
                continue

            result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
            text = result.text if result else ""

            if text and text.strip():
                is_wake = wake_detector.detect(text)
                utterances += 1

                segment_path = os.path.join(SAVE_DIR, f"speech_{saved_count:02d}_{max_rms:.0f}rms.wav")
                save_wav(segment_path, pcm)
                saved_count += 1

                if is_wake:
                    now_mono = time.monotonic()
                    # 去重：相同文本在冷却期内只触发一次
                    is_duplicate = (text.strip() == last_wake_text and 
                                   (now_mono - last_wake_time) < WAKE_DEDUP_SECONDS)
                    if not is_duplicate:
                        wakes += 1
                        last_wake_text = text.strip()
                        last_wake_time = now_mono
                        print(f"\n  🎯🎯🎯 唤醒触发! #{wakes}")
                        print(f"     识别结果: \"{text.strip()}\"")
                        print(f"     峰值RMS: {max_rms:.0f}")
                        print(f"     时间: {elapsed:.1f}s")
                        print(f"     音频已保存: {segment_path}")
                    else:
                        print(f"\n  🔁 重复唤醒已去重: \"{text.strip()}\" ({elapsed:.1f}s)")
                else:
                    print(f"\n  📝 \"{text.strip()}\" (RMS={max_rms:.0f}) → 唤醒词不匹配")
                    print(f"     音频已保存: {segment_path}")
            else:
                filtered += 1

            # 保留重叠帧用于下一窗口
            window_frames = window_frames[-overlap_frames:] if overlap_frames > 0 else []
            window_start = now - WINDOW_OVERLAP

    source.close()

    print(f"\n\n{'='*60}")
    print("📊 测试结果")
    print(f"{'='*60}")
    print(f"  时长: {duration:.1f}s")
    print(f"  有效语音段: {utterances}")
    print(f"  过滤段(静音/噪音): {filtered}")
    print(f"  唤醒触发: {wakes}")
    print(f"  峰值RMS: {max_rms_overall:.0f}")
    print(f"  噪声RMS: {noise_avg:.1f}")

    if wakes > 0:
        print(f"\n  🎉 唤醒功能验证通过! ({wakes} 次触发)")
    elif utterances > 0:
        print(f"\n  ⚠️  语音捕获正常 ({utterances} 段)，但未检测到唤醒词")
        print(f"     保存的音频在: {SAVE_DIR}/")
        print(f"     建议: 检查保存的音频，确认 ASR 是否正确识别")
    else:
        print(f"\n  ❌ 未检测到有效语音 (过滤了 {filtered} 段)")
        print(f"     峰值RMS={max_rms_overall:.0f} 噪声={noise_avg:.1f}")
        print(f"     可能原因:")
        print(f"     1. 麦克风距离太远 (>50cm)")
        print(f"     2. 说话音量太小 (RMS<30)")
        print(f"     3. 环境噪音太大")
        print(f"     💡 提示: 看着音量条，确保它经常进入黄色区域 (>40%)")

    if saved_count > 0:
        print(f"\n  📁 保存的音频文件: {SAVE_DIR}/")
        for f in sorted(os.listdir(SAVE_DIR)):
            print(f"     {f}")


if __name__ == "__main__":
    asyncio.run(main())