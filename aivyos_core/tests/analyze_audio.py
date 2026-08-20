"""分析保存的音频文件 — 诊断信噪比和频谱特征。"""
import wave
import struct
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

SAVE_DIR = os.path.join(os.path.dirname(__file__), "captured_audio")

def analyze_wav(path: str):
    """分析 WAV 文件特征。"""
    with wave.open(path, "rb") as wf:
        n_frames = wf.getnframes()
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        duration = n_frames / rate

        data = wf.readframes(n_frames)
        n_samples = len(data) // (width * channels)

        rms = 0.0
        peak = 0.0
        zero_crossings = 0
        prev_sample = 0

        for i in range(n_samples):
            offset = i * width * channels
            if width == 2:
                (s,) = struct.unpack_from("<h", data, offset)
            elif width == 1:
                s = struct.unpack_from("<b", data, offset)[0] * 256
            else:
                continue

            rms += float(s) * float(s)
            peak = max(peak, abs(float(s)))

            if i > 0:
                if (prev_sample >= 0) != (s >= 0):
                    zero_crossings += 1
            prev_sample = s

        rms = math.sqrt(rms / max(1, n_samples))
        zcr = zero_crossings / max(1, n_samples)

        return {
            "duration": duration,
            "samples": n_samples,
            "rms": rms,
            "peak": peak,
            "crest_factor": peak / rms if rms > 0 else 0,
            "zcr": zcr,
            "max_val": 32767,
            "peak_pct": peak / 32767 * 100,
        }

def main():
    print("=" * 60)
    print("🔍 音频文件分析")
    print("=" * 60)

    if not os.path.isdir(SAVE_DIR):
        print(f"  ❌ 目录不存在: {SAVE_DIR}")
        return

    files = sorted([f for f in os.listdir(SAVE_DIR) if f.endswith(".wav")])
    print(f"\n  找到 {len(files)} 个音频文件\n")

    results = []
    for f in files:
        path = os.path.join(SAVE_DIR, f)
        info = analyze_wav(path)
        info["file"] = f
        results.append(info)
        print(f"  {f}:")
        print(f"    时长={info['duration']:.2f}s RMS={info['rms']:.0f} Peak={info['peak']:.0f} Crest={info['crest_factor']:.1f} ZCR={info['zcr']:.2f}")
        print(f"    峰值百分比={info['peak_pct']:.1f}%")

    # 汇总统计
    if results:
        avg_rms = sum(r["rms"] for r in results) / len(results)
        max_rms = max(r["rms"] for r in results)
        min_rms = min(r["rms"] for r in results)
        avg_crest = sum(r["crest_factor"] for r in results) / len(results)

        print(f"\n{'='*60}")
        print(f"📊 汇总统计")
        print(f"{'='*60}")
        print(f"  平均 RMS: {avg_rms:.0f}")
        print(f"  最大 RMS: {max_rms:.0f}")
        print(f"  最小 RMS: {min_rms:.0f}")
        print(f"  平均波峰因子: {avg_crest:.1f}")
        print(f"  (语音典型值: 3-5, 纯音: 1.4, 噪音: 3-6)")

        # 诊断
        print(f"\n  🔍 诊断:")
        if avg_rms < 30:
            print(f"    ⚠️  平均 RMS 过低 ({avg_rms:.0f}), 信号微弱")
        elif avg_rms < 50:
            print(f"    ⚠️  平均 RMS 偏低 ({avg_rms:.0f}), 信噪比可能不足")
        else:
            print(f"    ✅ 信号电平正常")

        if avg_crest < 1.8:
            print(f"    ⚠️  波峰因子过低 ({avg_crest:.1f}), 可能是纯音/机械信号")
        elif avg_crest > 6:
            print(f"    ⚠️  波峰因子过高 ({avg_crest:.1f}), 可能是脉冲/削波")
        else:
            print(f"    ✅ 波峰因子正常 ({avg_crest:.1f}), 符合语音特征")

        # 建议
        print(f"\n  💡 建议:")
        print(f"    1. 检查麦克风距离 (30-50cm 为佳)")
        print(f"    2. 以正常音量说话 (60-70dB)")
        print(f"    3. 减少环境噪音 (关闭窗户/门)")
        print(f"    4. 考虑使用更好的麦克风 (如耳机麦)")

if __name__ == "__main__":
    main()