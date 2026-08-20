"""Silero VAD vs Energy VAD 对比测试。

使用与 test_wake_word.py 相同的合成音频场景，
对比两种 VAD 后端在噪音环境、距离衰减下的表现。
"""

from __future__ import annotations

import math
import os
import random
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aivyos_core.audio.vad import EnergyVAD, SileroVAD, _rms

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000

NOISE_PRE_SECONDS = 2.0
SPEECH_SECONDS = 1.0
NOISE_POST_SECONDS = 2.0


def generate_noise(duration_s, amplitude=500):
    n = int(duration_s * SAMPLE_RATE)
    out = bytearray()
    for _ in range(n):
        out += struct.pack("<h", random.randint(-amplitude, amplitude))
    return bytes(out)


def generate_speech_like(duration_s, amplitude=8000, pitch_hz=200.0):
    n = int(duration_s * SAMPLE_RATE)
    out = bytearray()
    for i in range(n):
        t = i / SAMPLE_RATE
        envelope = 0.5 + 0.5 * math.sin(2 * math.pi * 3.0 * t)
        v = amplitude * envelope * (
            0.6 * math.sin(2 * math.pi * pitch_hz * t) +
            0.3 * math.sin(2 * math.pi * pitch_hz * 2 * t) +
            0.1 * math.sin(2 * math.pi * pitch_hz * 3 * t)
        )
        out += struct.pack("<h", int(max(-32768, min(32767, v))))
    return bytes(out)


def split_frames(audio):
    frames = []
    for i in range(0, len(audio), FRAME_BYTES):
        chunk = audio[i:i + FRAME_BYTES]
        if len(chunk) == FRAME_BYTES:
            frames.append(chunk)
    return frames


def analyze_vad(frames, vad_fn, speech_start_frames, speech_frame_count):
    tp = fp = fn = tn = 0
    in_speech = False
    silence_count = 0
    consecutive_speech = 0
    speech_start = -1
    speech_end = -1

    for i, frame in enumerate(frames):
        is_speech = vad_fn(frame)
        in_seg = speech_start_frames <= i < speech_start_frames + speech_frame_count

        if is_speech and in_seg:
            tp += 1
        elif is_speech and not in_seg:
            fp += 1
        elif not is_speech and in_seg:
            fn += 1
        else:
            tn += 1

        if is_speech:
            consecutive_speech += 1
            silence_count = 0
            if not in_speech and consecutive_speech >= 2:
                in_speech = True
                speech_start = i
            if in_speech:
                speech_end = i
        else:
            consecutive_speech = 0
            if in_speech:
                silence_count += 1
                if silence_count >= 10:
                    in_speech = False

    total_speech = max(1, speech_frame_count)
    total_silence = max(1, len(frames) - speech_frame_count)
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "det_rate": tp / total_speech * 100,
        "fa_rate": fp / total_silence * 100,
        "utterance_ok": speech_start >= speech_start_frames,
        "start_frame": speech_start,
        "captured": max(0, speech_end - speech_start + 1) if speech_start >= 0 else 0,
    }


def run_comparison():
    print("=" * 70)
    print("Silero VAD vs Energy VAD 对比测试")
    print("=" * 70)

    silero = SileroVAD(sample_rate=16000, threshold=0.5)
    energy = EnergyVAD(threshold=200, auto_calibrate=True)

    def silero_fn(frame):
        return silero.is_speech(frame)

    energy_cal = EnergyVAD(threshold=200, auto_calibrate=True)
    def energy_fn(frame):
        return energy_cal.is_speech(frame)

    scenarios = [
        ("安静环境 (30)", 30, 8000),
        ("低噪音 (150)", 150, 8000),
        ("中噪音 (400)", 400, 8000),
        ("高噪音 (800)", 800, 8000),
        ("极高噪音 (1500)", 1500, 8000),
    ]

    distances = [
        ("0.5 米 (1.0x)", 200, 8000),
        ("1.0 米 (0.5x)", 200, 4000),
        ("2.0 米 (0.25x)", 200, 2000),
        ("3.0 米 (0.125x)", 200, 1000),
        ("5.0 米 (0.05x)", 200, 400),
    ]

    print("\n" + "-" * 70)
    print("场景 1: 噪音环境对比")
    print("-" * 70)
    print(f"  {'场景':<22} {'Silero检测':>10} {'Silero误报':>10} {'能量检测':>10} {'能量误报':>10}")
    print(f"  {'-'*62}")

    for name, noise_amp, speech_amp in scenarios:
        pre = generate_noise(NOISE_PRE_SECONDS, amplitude=noise_amp)
        sp = generate_speech_like(SPEECH_SECONDS, amplitude=speech_amp)
        post = generate_noise(NOISE_POST_SECONDS, amplitude=noise_amp)
        audio = pre + sp + post
        frames = split_frames(audio)
        pre_f = int(NOISE_PRE_SECONDS * 1000 / FRAME_MS)
        sp_f = int(SPEECH_SECONDS * 1000 / FRAME_MS)

        s = analyze_vad(frames, silero_fn, pre_f, sp_f)
        energy_cal2 = EnergyVAD(threshold=200, auto_calibrate=True)
        e = analyze_vad(frames, energy_cal2.is_speech, pre_f, sp_f)

        print(f"  {name:<22} {s['det_rate']:>8.1f}% {s['fa_rate']:>8.1f}% {e['det_rate']:>8.1f}% {e['fa_rate']:>8.1f}%")

    print("\n" + "-" * 70)
    print("场景 2: 距离衰减对比")
    print("-" * 70)
    print(f"  {'距离':<22} {'Silero检测':>10} {'Silero误报':>10} {'能量检测':>10} {'能量误报':>10}")
    print(f"  {'-'*62}")

    for name, noise_amp, speech_amp in distances:
        noise_dur = NOISE_PRE_SECONDS + NOISE_POST_SECONDS
        full_noise = generate_noise(noise_dur, amplitude=noise_amp)
        sp = generate_speech_like(SPEECH_SECONDS, amplitude=speech_amp)
        pre_bytes = int(NOISE_PRE_SECONDS * SAMPLE_RATE * 2)
        audio = full_noise[:pre_bytes] + sp + full_noise[pre_bytes:]
        frames = split_frames(audio)
        pre_f = int(NOISE_PRE_SECONDS * 1000 / FRAME_MS)
        sp_f = int(SPEECH_SECONDS * 1000 / FRAME_MS)

        s = analyze_vad(frames, silero_fn, pre_f, sp_f)
        energy_cal3 = EnergyVAD(threshold=200, auto_calibrate=True)
        e = analyze_vad(frames, energy_cal3.is_speech, pre_f, sp_f)

        print(f"  {name:<22} {s['det_rate']:>8.1f}% {s['fa_rate']:>8.1f}% {e['det_rate']:>8.1f}% {e['fa_rate']:>8.1f}%")

    print("\n" + "-" * 70)
    print("场景 3: 响应时间对比")
    print("-" * 70)

    test_frame = generate_speech_like(0.032, amplitude=5000)
    silero_times = []
    energy_times = []
    for _ in range(1000):
        t0 = time.perf_counter()
        silero.is_speech(test_frame)
        silero_times.append((time.perf_counter() - t0) * 1000)

    energy_t = EnergyVAD(threshold=200, auto_calibrate=False)
    for _ in range(1000):
        t0 = time.perf_counter()
        energy_t.is_speech(test_frame)
        energy_times.append((time.perf_counter() - t0) * 1000)

    print(f"  Silero VAD: 平均={sum(silero_times)/len(silero_times):.3f}ms, P95={sorted(silero_times)[950]:.3f}ms")
    print(f"  Energy VAD: 平均={sum(energy_times)/len(energy_times):.3f}ms, P95={sorted(energy_times)[950]:.3f}ms")

    print("\n" + "=" * 70)
    print("结论")
    print("=" * 70)
    print("  Silero VAD: 神经网络模型，准确率高，延迟 ~0.4ms")
    print("  Energy VAD: 规则阈值，轻量快速，延迟 ~0.01ms")
    print("  建议: 默认使用 Silero VAD，降级使用 Energy VAD")


if __name__ == "__main__":
    run_comparison()