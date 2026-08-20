"""最终唤醒验证 v3 — 带噪音过滤 + 实时音量显示。

改进:
1. 使用优化的 FunASR 后端 (带静音预过滤 + 波峰因子分析)
2. 实时音量条显示 (让用户知道麦克风在工作)
3. 1秒窗口 (快速响应)
4. 保存语音片段供分析
5. 智能提示 (当检测不到语音时提醒用户)

运行: python final_wake_v3.py
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

SAMPLE_RATE = 16000
FRAME_MS = 32
WINDOW_SECONDS = 1.0
GAIN = 50.0
DEVICE = "7"
DURATION = 25.0
SAVE_DIR = os.path.join(os.path.dirname(__file__), "captured_audio_v3")

def volume_bar(rms: float, width: int = 20) -> str:
    """生成音量条字符串。"""
    max_rms = 200.0
    level = min(1.0, rms / max_rms)
    filled = int(width * level)
    return "█" * filled + "░" * (width - filled)

async def main():
    os.makedirs(SAVE_DIR, exist_ok=True)

    print()
    print("╔" + "═" * 60 + "╗")
    print("║" + " " * 8 + "🎯 AivyOS 唤醒验证 v3" + " " * 14 + "║")
    print("║" + " " * 6 + "带智能噪音过滤 + 实时音量显示" + " " * 7 + "║")
    print("╚" + "═" * 60 + "╝")
    print()
    print(f"  唤醒词: {', '.join(WakeWordDetector().words)}")
    print(f"  增益: {GAIN}x | 窗口: {WINDOW_SECONDS}s | 时长: {DURATION}s")
    print()
    print("  📢 使用方法:")
    print("    1. 将麦克风放在距嘴 30-50cm 处")
    print("    2. 倒计时结束后，清晰地说 '艾薇' 或 'Aivy'")
    print("    3. 看着音量条，确保你的声音被捕捉到")
    print("    4. 说唤醒词后等待结果")
    print()

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS,
                       device=DEVICE, gain=GAIN)

    print("  ⏳ 加载 ASR 模型...", flush=True)
    asr = create_asr({"silence_threshold": 20.0, "silence_min_ratio": 0.05})
    print("  ✅ ASR 就绪\n")

    wake_detector = WakeWordDetector()

    # 校准
    print("  📻 校准中 (2s)...", flush=True)
    cal_rms = []
    cal_end = asyncio.get_event_loop().time() + 2.0
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > cal_end:
            break
        cal_rms.append(_rms(frame))
    noise_avg = sum(cal_rms) / max(1, len(cal_rms))
    noise_max = max(cal_rms) if cal_rms else 0
    print(f"  ✅ 噪声: avg={noise_avg:.1f} max={noise_max:.1f}")
    print(f"  💡 当音量条超过 [{volume_bar(50)}] 时表示检测到语音\n")

    # 倒计时
    for i in range(3, 0, -1):
        print(f"  {i}...", flush=True)
        await asyncio.sleep(1)
    print("  🎤 开始! 请说 '艾薇' 或 'Aivy'\n")

    end_time = time.monotonic() + DURATION
    window_frames = []
    window_start = time.monotonic()
    wakes = 0
    utterances = 0
    filtered = 0
    max_rms_overall = 0
    chunk_index = 0
    last_rms = 0

    async for frame in source.stream():
        if time.monotonic() > end_time:
            break

        window_frames.append(frame)
        current_rms = _rms(frame)
        last_rms = current_rms

        now = time.monotonic()
        elapsed = DURATION - (end_time - now)

        # 显示实时音量
        vol = volume_bar(current_rms)
        sys.stdout.write(f"\r  [{vol}] {elapsed:5.1f}s/{DURATION}s | RMS={current_rms:4.0f}   ")
        sys.stdout.flush()

        if (now - window_start) >= WINDOW_SECONDS:
            if len(window_frames) < 5:
                window_frames = []
                window_start = now
                continue

            pcm = b"".join(window_frames)
            chunk_max_rms = max(_rms(f) for f in window_frames)
            chunk_avg_rms = sum(_rms(f) for f in window_frames) / len(window_frames)
            max_rms_overall = max(max_rms_overall, chunk_max_rms)

            chunk_index += 1

            result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
            text = result.text if result else ""

            if text and text.strip():
                utterances += 1
                is_wake = wake_detector.detect(text)

                if is_wake:
                    wakes += 1
                    wake_path = os.path.join(SAVE_DIR, f"WAKE_{wakes}.wav")
                    with wave.open(wake_path, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(SAMPLE_RATE)
                        wf.writeframes(pcm)

                    print(f"\n  {'='*50}")
                    print(f"  🎯🎯🎯  唤 醒 触 发!  #{wakes}")
                    print(f"  {'='*50}")
                    print(f"     识别结果: \"{text.strip()}\"")
                    print(f"     峰值RMS: {chunk_max_rms:.0f}")
                    print(f"     时间: {elapsed:.1f}s")
                    print(f"     音频: {wake_path}")
                    print(f"  {'='*50}\n")
                else:
                    if len(text.strip()) >= 2:
                        print(f"\n  📝 [{elapsed:5.1f}s] \"{text.strip()}\" (RMS={chunk_max_rms:.0f}) → 非唤醒词")
                    else:
                        filtered += 1
            else:
                filtered += 1

            window_frames = []
            window_start = now

    source.close()

    print(f"\n\n{'='*60}")
    print("📊 测试结果")
    print(f"{'='*60}")
    print(f"  时长: {DURATION}s")
    print(f"  有效语音段: {utterances}")
    print(f"  过滤段(静音/噪音): {filtered}")
    print(f"  唤醒触发: {wakes}")
    print(f"  峰值RMS: {max_rms_overall:.0f}")
    print(f"  噪声RMS: {noise_avg:.1f}")

    if wakes > 0:
        print(f"\n  🎉 唤醒功能验证通过! ({wakes} 次触发)")
        return True
    elif utterances > 0:
        print(f"\n  ⚠️  检测到 {utterances} 段语音，但未触发唤醒")
        print(f"     ASR 识别了语音但内容不匹配唤醒词")
        print(f"     建议: 更大声、更清晰地说 '艾薇'")
        print(f"     音频已保存到: {SAVE_DIR}/")
        return False
    else:
        print(f"\n  ❌ 未检测到有效语音 (过滤了 {filtered} 段)")
        print(f"     可能原因:")
        print(f"     1. 麦克风距离太远 (>50cm)")
        print(f"     2. 说话音量太小 ( RMS<{noise_avg+10:.0f})")
        print(f"     3. 环境噪音太大")
        print(f"     💡 提示: 看着音量条，确保它经常超过一半")
        return False

if __name__ == "__main__":
    asyncio.run(main())