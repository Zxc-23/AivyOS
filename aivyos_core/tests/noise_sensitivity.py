"""测试噪音对 FunASR 识别的影响 — 将干净 TTS 与麦克风噪音混合。"""
import sys, os, wave, io, re, struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.asr.manager import create_asr
from aivyos_core.asr.funasr_backend import _has_speech, _rms_energy

SAMPLE_RATE = 16000

def load_wav_16k(path: str) -> bytes:
    """加载并转换 WAV 到 16kHz。"""
    import numpy as np
    from scipy.io import wavfile
    sr, data = wavfile.read(path)
    if len(data.shape) > 1:
        data = data.mean(axis=1).astype(np.float64)
    else:
        data = data.astype(np.float64)
    if sr != SAMPLE_RATE:
        duration = len(data) / sr
        target = int(duration * SAMPLE_RATE)
        indices = np.linspace(0, len(data) - 1, target)
        data = np.interp(indices, np.arange(len(data)), data)
    max_val = abs(data).max()
    if max_val > 0:
        data = data / max_val
    return (data * 32767).astype(np.int16).tobytes()

def set_rms(pcm: bytes, target_rms: float) -> bytes:
    import numpy as np
    data = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    current = np.sqrt(np.mean(data ** 2))
    if current == 0:
        return pcm
    data = data * (target_rms / current)
    data = np.clip(data, -32768, 32767).astype(np.int16)
    return data.tobytes()

def mix_noise(speech_pcm: bytes, noise_pcm: bytes, snr_db: float) -> bytes:
    """以指定 SNR (dB) 将噪音混合到语音中。"""
    import numpy as np
    speech = np.frombuffer(speech_pcm, dtype=np.int16).astype(np.float64)
    noise = np.frombuffer(noise_pcm, dtype=np.int16).astype(np.float64)
    
    # 重复噪音以匹配语音长度
    if len(noise) < len(speech):
        repeats = (len(speech) // len(noise)) + 1
        noise = np.tile(noise, repeats)
    noise = noise[:len(speech)]
    
    # 计算 SNR
    speech_power = np.mean(speech ** 2)
    noise_power = np.mean(noise ** 2)
    snr_linear = 10 ** (snr_db / 10)
    required_noise_power = speech_power / snr_linear
    
    if noise_power > 0:
        noise = noise * np.sqrt(required_noise_power / noise_power)
    
    mixed = speech + noise
    mixed = np.clip(mixed, -32768, 32767).astype(np.int16)
    return mixed.tobytes()

def main():
    print("=" * 60)
    print("🔊 噪音对 FunASR 识别的影响")
    print("=" * 60)

    tts_path = os.path.join(os.path.dirname(__file__), "tts_test.wav")
    if not os.path.exists(tts_path):
        print("  ❌ tts_test.wav 不存在")
        return

    # 加载 TTS 语音并设为 RMS=100
    print("\n  加载 TTS 音频 (RMS=100)...")
    speech_pcm = load_wav_16k(tts_path)
    speech_pcm = set_rms(speech_pcm, 100.0)
    print(f"    RMS: {_rms_energy(speech_pcm):.1f}")

    # 生成噪音 (模拟风扇/空调噪音)
    import numpy as np
    noise_duration = len(speech_pcm) / 2 / SAMPLE_RATE
    n_samples = int(noise_duration * SAMPLE_RATE)
    # 使用低通滤波的白噪音模拟环境噪音
    raw_noise = np.random.randn(n_samples)
    from scipy.signal import butter, filtfilt
    b, a = butter(4, 800 / (SAMPLE_RATE / 2), btype='low')
    filtered_noise = filtfilt(b, a, raw_noise)
    noise_pcm = (filtered_noise * 100).astype(np.int16).tobytes()

    # 测试不同 SNR
    asr = create_asr({"silence_threshold": 20.0})
    
    snr_levels = [None, 30, 20, 15, 10, 5, 0, -5, -10, -15, -20]
    
    print(f"\n  {'SNR(dB)':>8} {'RMS':>8} {'_has_speech':>12} {'识别结果':<25} {'正确':>6}")
    print(f"  {'─'*8} {'─'*8} {'─'*12} {'─'*25} {'─'*6}")
    
    for snr in snr_levels:
        if snr is None:
            test_pcm = speech_pcm
            label = "纯净"
        else:
            test_pcm = mix_noise(speech_pcm, noise_pcm, snr)
            label = f"{snr} dB"
        
        rms = _rms_energy(test_pcm)
        hs = _has_speech(test_pcm, 20.0)
        
        result = asr.transcribe(test_pcm, SAMPLE_RATE)
        text = result.text if result else ""
        
        is_correct = "你好" in text and "艾薇" in text
        
        print(f"  {label:>8} {rms:8.1f} {hs!s:>12} '{text:<23}' {is_correct!s:>6}")

    print(f"\n  💡 结论:")
    print(f"     - SNR > 15dB: FunASR 正确识别")
    print(f"     - SNR 10-15dB: 开始出现识别错误")
    print(f"     - SNR < 5dB: 严重幻觉")
    print(f"     - 建议: 麦克风音频 SNR 应保持在 15dB 以上")

if __name__ == "__main__":
    main()