"""最终唤醒验证 — 综合测试脚本。

功能:
1. 使用优化的 FunASR 后端 (带静音预过滤)
2. 增益 50x (CL100 最优值)
3. 2秒音频窗口 (ASR 最佳上下文)
4. 保存捕获的语音片段为 WAV
5. 清晰的用户提示和进度显示

用法: python final_wake_validation.py
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

SAMPLE_RATE = 16000
FRAME_MS = 32
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000
WINDOW_SECONDS = 2.0
GAIN = 50.0
DEVICE = "7"
DURATION = 30.0
SAVE_DIR = os.path.join(os.path.dirname(__file__), "captured_audio")

async def main():
    print()
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "🎯 AivyOS 唤醒功能最终验证" + " " * 11 + "║")
    print("╚" + "═" * 58 + "╝")
    print()
    print(f"  配置:")
    print(f"    设备: {DEVICE} (CL100)")
    print(f"    增益: {GAIN}x")
    print(f"    窗口: {WINDOW_SECONDS}s")
    print(f"    时长: {DURATION}s")
    print(f"    唤醒词: {', '.join(WakeWordDetector().words)}")
    print()
    print("  📢 测试说明:")
    print("    倒计时结束后，请对着麦克风清晰说话")
    print("    建议说: '你好艾薇' 或 '艾薇' 或 'Aivy'")
    print("    测试将持续约 30 秒")
    print()

    # 确保保存目录存在
    os.makedirs(SAVE_DIR, exist_ok=True)

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS,
                       device=DEVICE, gain=GAIN)

    print("  ⏳ 加载 ASR 模型 (首次加载约 10-20s)...", flush=True)
    asr = create_asr({"silence_threshold": 20.0})
    print("  ✅ ASR 就绪\n")

    wake_detector = WakeWordDetector()

    # 校准噪声
    print("  📻 校准环境噪声 (2s)...", flush=True)
    cal_rms = []
    cal_end = asyncio.get_event_loop().time() + 2.0
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > cal_end:
            break
        cal_rms.append(_rms(frame))
    noise_avg = sum(cal_rms) / max(1, len(cal_rms))
    noise_max = max(cal_rms) if cal_rms else 0
    print(f"  ✅ 噪声: avg={noise_avg:.1f}RMS, max={noise_max:.1f}RMS\n")

    # 倒计时
    for i in range(3, 0, -1):
        print(f"  {i}...", flush=True)
        await asyncio.sleep(1)
    print("  🎤 开始! 请说话...\n")

    # 主循环
    end_time = time.monotonic() + DURATION
    window_frames = []
    window_start = time.monotonic()
    wakes = 0
    utterances = 0
    empty_results = 0
    max_rms_overall = 0
    chunk_index = 0

    async for frame in source.stream():
        if time.monotonic() > end_time:
            break

        window_frames.append(frame)
        now = time.monotonic()

        if (now - window_start) >= WINDOW_SECONDS:
            if len(window_frames) < 10:
                window_frames = []
                window_start = now
                continue

            pcm = b"".join(window_frames)
            max_rms = max(_rms(f) for f in window_frames)
            avg_rms = sum(_rms(f) for f in window_frames) / len(window_frames)
            max_rms_overall = max(max_rms_overall, max_rms)

            chunk_index += 1
            time_offset = DURATION - (end_time - time.monotonic())

            # ASR 转写
            result = await asyncio.to_thread(asr.transcribe, pcm, SAMPLE_RATE)
            text = result.text if result else ""

            if text and text.strip():
                utterances += 1
                is_wake = wake_detector.detect(text)

                if is_wake:
                    wakes += 1
                    # 保存唤醒音频
                    wake_path = os.path.join(SAVE_DIR, f"wake_{wakes}_{chunk_index}.wav")
                    with wave.open(wake_path, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(SAMPLE_RATE)
                        wf.writeframes(pcm)

                    print(f"\n  {'='*50}")
                    print(f"  🎯🎯🎯  唤 醒 触 发!  #{wakes}")
                    print(f"  {'='*50}")
                    print(f"     识别: \"{text.strip()}\"")
                    print(f"     RMS:  avg={avg_rms:.0f} max={max_rms:.0f}")
                    print(f"     时间: {time_offset:.1f}s")
                    print(f"     音频: {wake_path}")
                    print()
                else:
                    # 保存有趣的非唤醒音频
                    if len(text.strip()) >= 2:
                        non_wake_path = os.path.join(SAVE_DIR, f"speech_{chunk_index}.wav")
                        with wave.open(non_wake_path, "wb") as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(SAMPLE_RATE)
                            wf.writeframes(pcm)
                        print(f"  📝 [{time_offset:5.1f}s] \"{text.strip()}\" (RMS={max_rms:.0f}) → 非唤醒词")
                    else:
                        empty_results += 1
                        print(f"  📝 [{time_offset:5.1f}s] \"{text.strip()}\" (RMS={max_rms:.0f})")
            else:
                empty_results += 1
                bar_len = 20
                elapsed = time_offset
                remaining = max(0, DURATION - elapsed)
                filled = int(bar_len * (elapsed / DURATION))
                bar = "█" * filled + "░" * (bar_len - filled)
                sys.stdout.write(f"\r  [{bar}] {elapsed:5.1f}s/{DURATION}s | RMS={max_rms:.0f} | 等待语音...  ")
                sys.stdout.flush()

            window_frames = []
            window_start = now

    source.close()

    # 结果汇总
    print(f"\n\n{'='*60}")
    print("📊 最终测试结果")
    print(f"{'='*60}")
    print(f"  测试时长: {DURATION}s")
    print(f"  有效语音段: {utterances}")
    print(f"  空结果/过滤: {empty_results}")
    print(f"  唤醒触发: {wakes}")
    print(f"  峰值RMS: {max_rms_overall:.0f}")
    print(f"  噪声RMS: {noise_avg:.1f}")
    print(f"  音频保存目录: {SAVE_DIR}")

    if wakes > 0:
        print(f"\n  🎉🎊 唤醒功能验证通过! ({wakes} 次触发)")
        return True
    elif utterances > 0:
        print(f"\n  ⚠️  语音捕获正常 ({utterances} 段)，但未检测到唤醒词")
        print(f"     ASR 识别到 {utterances} 段语音，检查上方输出内容")
        print(f"     建议: 更大声、更清晰地说 '艾薇'")
        print(f"     或检查 saved 音频文件确认麦克风质量")
        return False
    else:
        print(f"\n  ❌ 未检测到有效语音")
        print(f"     可能原因:")
        print(f"     1. 麦克风距离太远 (>1m)")
        print(f"     2. 说话音量太小")
        print(f"     3. 麦克风设备选择错误")
        print(f"     建议: 距离麦克风 30-50cm, 正常音量说话")
        return False

if __name__ == "__main__":
    asyncio.run(main())