"""录制用户真实语音 — 保存并分析。

录制 5 秒音频，完整处理并保存原始数据供分析。
"""
import asyncio, sys, os, wave, struct, io, re, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.manager import create_asr
from aivyos_core.asr.funasr_backend import _has_speech, _rms_energy

SAMPLE_RATE = 16000
FRAME_MS = 32
RECORD_SECONDS = 5.0
GAIN = 50.0

SAVE_DIR = os.path.join(os.path.dirname(__file__), "captured_user")


async def main():
    print("=" * 60)
    print("🎙️ 真实语音录制与分析")
    print("=" * 60)

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device="7", gain=GAIN)
    print(f"  ✅ 麦克风已打开 (gain={GAIN}x)")

    # 校准
    print("\n  📻 校准 2 秒...")
    cal_rms = []
    cal_end = asyncio.get_event_loop().time() + 2.0
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > cal_end:
            break
        cal_rms.append(_rms(frame))
    noise_avg = sum(cal_rms) / max(1, len(cal_rms))
    noise_max = max(cal_rms) if cal_rms else 0
    print(f"    噪声: {noise_avg:.1f}RMS (峰值 {noise_max:.0f})")

    # 录制
    print(f"\n  ⏺️ 录制 {RECORD_SECONDS:.0f} 秒...")
    print(f"    请清晰地说: '你好艾薇' 或 'Aivy'")
    print(f"    音量适中，距离麦克风 20-30cm\n")

    frames = []
    rec_start = time.monotonic()
    last_rms = 0
    async for frame in source.stream():
        elapsed = time.monotonic() - rec_start
        if elapsed >= RECORD_SECONDS:
            break
        frames.append(frame)
        last_rms = _rms(frame)
        bar_len = 20
        ratio = min(last_rms / 200, 1.0)
        filled = int(ratio * bar_len)
        sys.stdout.write(f"\r    [{'█' * filled}{'░' * (bar_len - filled)}] {elapsed:4.1f}s RMS={last_rms:3.0f}  ")
        sys.stdout.flush()

    pcm = b"".join(frames)
    duration = len(pcm) / 2 / SAMPLE_RATE
    overall_rms = _rms_energy(pcm)
    print(f"\n\n  ✅ 录制完成: {duration:.2f}s, RMS={overall_rms:.1f}")

    # 保存完整录音
    os.makedirs(SAVE_DIR, exist_ok=True)
    full_path = os.path.join(SAVE_DIR, "user_speech_full.wav")
    with wave.open(full_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    print(f"  💾 完整录音: {full_path}")

    source.close()

    # 分析音频特征
    print(f"\n  🔍 音频分析:")
    print(f"    总RMS: {overall_rms:.1f}")
    print(f"    噪声RMS: {noise_avg:.1f}")
    print(f"    SNR估算: {20 * __import__('math').log10(overall_rms / max(noise_avg, 0.1)):.1f} dB")

    # _has_speech 检测
    hs = _has_speech(pcm, 20.0)
    print(f"    _has_speech(20): {hs}")

    # FunASR 处理
    print(f"\n  🔄 FunASR 处理中...")
    asr = create_asr({"silence_threshold": 0.0})

    # 方法 1: 完整音频
    result_full = asr.transcribe(pcm, SAMPLE_RATE)
    print(f"    完整音频识别: '{result_full.text}'")

    # 方法 2: 分段 (1秒)
    print(f"\n  分段识别 (1秒窗口):")
    window_size = SAMPLE_RATE * 2
    n_windows = len(pcm) // window_size
    for i in range(n_windows):
        start = i * window_size
        end = start + window_size
        window_pcm = pcm[start:end]
        w_rms = _rms_energy(window_pcm)
        w_hs = _has_speech(window_pcm, 20.0)
        w_result = asr.transcribe(window_pcm, SAMPLE_RATE)
        w_text = w_result.text if w_result else ""
        print(f"      窗口{i}: RMS={w_rms:6.1f}  _hs={w_hs}  '{w_text}'")

    print(f"\n  💡 建议:")
    print(f"    1. 检查保存的 WAV 文件，确认麦克风是否正常采集")
    print(f"    2. 如果 WAV 只有噪音，尝试提高麦克风音量或靠近麦克风")
    print(f"    3. 如果 WAV 有语音但识别错误，可能需要调整 ASR 参数")

if __name__ == "__main__":
    asyncio.run(main())