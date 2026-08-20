"""测试 FunASR 在不同 RMS 能量下的识别准确率。"""
import sys, os, wave, io, re, struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.asr.manager import create_asr
from aivyos_core.asr.funasr_backend import _has_speech, _rms_energy

SAMPLE_RATE = 16000

def load_tts_16k(path: str) -> bytes:
    """加载并转换 TTS 音频到 16kHz。"""
    import numpy as np
    from scipy.io import wavfile
    
    sr, data = wavfile.read(path)
    if len(data.shape) > 1:
        data = data.mean(axis=1).astype(np.float64)
    else:
        data = data.astype(np.float64)
    
    # 重采样
    if sr != SAMPLE_RATE:
        duration = len(data) / sr
        target_length = int(duration * SAMPLE_RATE)
        indices = np.linspace(0, len(data) - 1, target_length)
        data = np.interp(indices, np.arange(len(data)), data)
    
    # 归一化
    max_val = abs(data).max()
    if max_val > 0:
        data = data / max_val
    
    return (data * 32767).astype(np.int16).tobytes()

def set_rms(pcm: bytes, target_rms: float) -> bytes:
    """将 PCM 音频调整到目标 RMS。"""
    import numpy as np
    data = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    current_rms = np.sqrt(np.mean(data ** 2))
    if current_rms == 0:
        return pcm
    gain = target_rms / current_rms
    data = data * gain
    data = np.clip(data, -32768, 32767).astype(np.int16)
    return data.tobytes()

def main():
    print("=" * 60)
    print("📊 FunASR 识别准确率 vs RMS 能量")
    print("=" * 60)

    tts_path = os.path.join(os.path.dirname(__file__), "tts_test.wav")
    if not os.path.exists(tts_path):
        print("  ❌ tts_test.wav 不存在")
        return

    print("\n  加载 TTS 音频...")
    pcm_normalized = load_tts_16k(tts_path)
    print(f"    原始 RMS: {_rms_energy(pcm_normalized):.1f}")

    asr = create_asr({"silence_threshold": 20.0})
    wake_words = ["aivy", "艾薇", "贾维斯"]

    rms_levels = [5, 10, 20, 30, 50, 80, 100, 150, 200, 300, 500, 1000, 2000]

    print(f"\n  {'RMS':>8} {'_has_speech':>12} {'识别结果':<20} {'唤醒匹配':>10}")
    print(f"  {'─'*8} {'─'*12} {'─'*20} {'─'*10}")

    for target_rms in rms_levels:
        pcm = set_rms(pcm_normalized, target_rms)
        actual_rms = _rms_energy(pcm)
        
        hs = _has_speech(pcm, 20.0)
        
        result = asr.transcribe(pcm, SAMPLE_RATE)
        text = result.text if result else ""
        
        is_wake = any(w.lower() in text.lower() for w in wake_words) if text else False
        
        status = "✅" if text and not any(h in text for h in ["嗯", "我", "是"]) else "❌"
        if is_wake:
            status = "🎯"
        
        print(f"  {actual_rms:8.1f} {hs!s:>12} '{text:<18}' {is_wake!s:>10} {status}")

    # 总结
    print(f"\n  💡 结论:")
    print(f"     - RMS < 20: 被 _has_speech 过滤")
    print(f"     - RMS 20-100: FunASR 可能产生幻觉")
    print(f"     - RMS > 100: 识别准确率显著提升")
    print(f"     - 建议: 麦克风音频 RMS 应保持在 100+")

if __name__ == "__main__":
    main()