"""诊断当前音频环境 — 分析 _has_speech 为何过滤掉所有音频。"""
import asyncio
import sys
import os
import struct
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.funasr_backend import _has_speech, _rms_energy

SAMPLE_RATE = 16000
FRAME_MS = 32
WINDOW_SECONDS = 1.0
SAVE_DIR = os.path.join(os.path.dirname(__file__), "captured_diag")


def analyze_pcm(pcm: bytes, label: str, threshold: float = 20.0):
    """详细分析一段 PCM 音频。"""
    frame_size = 512  # 32ms @ 16kHz
    n_frames = len(pcm) // (frame_size * 2)
    
    speech_frames = 0
    peak_sum = 0.0
    rms_sum = 0.0
    rms_values = []
    
    for i in range(n_frames):
        offset = i * frame_size * 2
        frame = pcm[offset : offset + frame_size * 2]
        rms = _rms_energy(frame)
        rms_sum += rms
        rms_values.append(rms)
        if rms > threshold:
            speech_frames += 1
            peak = 0.0
            for j in range(len(frame) // 2):
                (s,) = struct.unpack_from("<h", frame, j * 2)
                peak = max(peak, abs(float(s)))
            peak_sum += peak
    
    ratio = speech_frames / max(n_frames, 1)
    avg_rms = rms_sum / max(n_frames, 1)
    max_rms = max(rms_values) if rms_values else 0
    dynamic_range = max_rms / avg_rms if avg_rms > 0 else 1.0
    
    crest_factor = 0.0
    if speech_frames > 0 and avg_rms > 1.0:
        avg_peak = peak_sum / speech_frames
        crest_factor = avg_peak / avg_rms
    
    has_speech = _has_speech(pcm, threshold)
    
    print(f"\n  [{label}]")
    print(f"    帧数: {n_frames}")
    print(f"    平均RMS: {avg_rms:.1f}")
    print(f"    最大RMS: {max_rms:.1f}")
    print(f"    语音帧数: {speech_frames}/{n_frames} ({ratio:.1%})")
    print(f"    动态范围: {dynamic_range:.2f}")
    print(f"    波峰因子: {crest_factor:.2f}")
    print(f"    _has_speech({threshold}): {has_speech}")
    
    reasons = []
    if ratio < 0.05:
        reasons.append(f"语音帧比例 {ratio:.1%} < 5%")
    if avg_rms < threshold * 0.8:
        reasons.append(f"平均RMS {avg_rms:.1f} < {threshold*0.8:.1f}")
    if crest_factor > 0:
        if crest_factor < 1.8:
            reasons.append(f"波峰因子 {crest_factor:.2f} < 1.8 (纯音)")
        elif crest_factor < 2.5 and avg_rms < threshold * 1.5:
            reasons.append(f"波峰因子 {crest_factor:.2f} < 2.5 且 RMS {avg_rms:.1f} < {threshold*1.5:.1f}")
        elif crest_factor < 2.0 and dynamic_range < 1.5:
            reasons.append(f"波峰因子 {crest_factor:.2f} < 2.0 且动态范围 {dynamic_range:.2f} < 1.5")
    
    if reasons:
        print(f"    ❌ 过滤原因: {', '.join(reasons)}")
    else:
        print(f"    ✅ 通过过滤")
    
    return has_speech


def save_wav(path: str, pcm: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)


async def main():
    print("=" * 60)
    print("🔍 音频环境诊断")
    print("=" * 60)

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device="7", gain=100.0)

    print("\n  📻 校准中...", flush=True)
    cal_rms = []
    cal_end = asyncio.get_event_loop().time() + 2.0
    async for frame in source.stream():
        if asyncio.get_event_loop().time() > cal_end:
            break
        cal_rms.append(_rms(frame))
    noise_avg = sum(cal_rms) / max(1, len(cal_rms))
    print(f"  ✅ 噪声基线: {noise_avg:.1f}RMS (峰值: {max(cal_rms):.0f})")

    print("\n  请开始说话! (5 秒)...")
    test_start = time.monotonic()
    end_time = test_start + 5.0
    
    window_frames = []
    window_start = test_start
    saved = 0
    
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
            label = f"win_{int(now - test_start)}s"
            
            # 用不同阈值测试
            print(f"\n  ─── 窗口 {label} ───")
            analyze_pcm(pcm, label, threshold=20.0)
            analyze_pcm(pcm, label + "@T40", threshold=40.0)
            analyze_pcm(pcm, label + "@T60", threshold=60.0)
            
            # 保存用于分析
            save_wav(os.path.join(SAVE_DIR, f"{label}.wav"), pcm)
            saved += 1
            
            window_frames = []
            window_start = now

    source.close()
    print(f"\n  保存了 {saved} 个窗口到 {SAVE_DIR}/")

if __name__ == "__main__":
    asyncio.run(main())