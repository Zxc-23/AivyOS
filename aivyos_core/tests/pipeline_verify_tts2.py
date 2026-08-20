"""验证完整管道 — 用 TTS 音频测试 1 秒窗口和唤醒检测。"""
import sys, os, wave, io, re, struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.asr.manager import create_asr
from aivyos_core.asr.funasr_backend import _has_speech, _rms_energy
from aivyos_core.wake import WakeWordDetector

SAMPLE_RATE = 16000

def resample_to_16k(input_path: str, output_path: str):
    """将 WAV 文件重采样到 16kHz。"""
    import numpy as np
    from scipy.io import wavfile
    
    sr, data = wavfile.read(input_path)
    if len(data.shape) > 1:
        data = data.mean(axis=1)
    
    # 重采样
    duration = len(data) / sr
    target_length = int(duration * SAMPLE_RATE)
    indices = np.linspace(0, len(data) - 1, target_length)
    resampled = np.interp(indices, np.arange(len(data)), data).astype(np.int16)
    
    wavfile.write(output_path, SAMPLE_RATE, resampled)
    return target_length / SAMPLE_RATE

def load_wav_16k(path: str) -> bytes:
    """加载 WAV 文件并确保是 16kHz。"""
    import numpy as np
    from scipy.io import wavfile
    
    sr, data = wavfile.read(path)
    if len(data.shape) > 1:
        data = data.mean(axis=1)
    
    if sr != SAMPLE_RATE:
        duration = len(data) / sr
        target_length = int(duration * SAMPLE_RATE)
        indices = np.linspace(0, len(data) - 1, target_length)
        data = np.interp(indices, np.arange(len(data)), data).astype(np.int16)
        sr = SAMPLE_RATE
    
    if data.dtype != np.int16:
        data = (data * 32767).astype(np.int16)
    
    return data.tobytes()

def main():
    print("=" * 60)
    print("🔬 完整管道验证 — TTS 音频")
    print("=" * 60)

    tts_path = os.path.join(os.path.dirname(__file__), "tts_test.wav")
    if not os.path.exists(tts_path):
        print("  ❌ tts_test.wav 不存在，请先运行 generate_tts_audio.py")
        return

    # 重采样到 16kHz
    print("\n  📥 加载 TTS 音频...")
    pcm_full = load_wav_16k(tts_path)
    duration = len(pcm_full) / 2 / SAMPLE_RATE
    print(f"    时长: {duration:.2f}s, 数据: {len(pcm_full)} bytes")
    print(f"    RMS: {_rms_energy(pcm_full):.1f}")

    # 测试 1: 完整音频
    print("\n  ─── 测试 1: 完整音频 (2.44s) ───")
    asr = create_asr({"silence_threshold": 20.0})
    result = asr.transcribe(pcm_full, SAMPLE_RATE)
    print(f"    ASR 结果: '{result.text}'")
    
    wake = WakeWordDetector()
    if result.text:
        is_wake = wake.detect(result.text)
        print(f"    唤醒检测: {is_wake}")
        if is_wake:
            print(f"    🎉 完整管道验证通过!")

    # 测试 2: 1 秒窗口
    print("\n  ─── 测试 2: 1 秒窗口 (模拟实时处理) ───")
    window_size = SAMPLE_RATE * 2  # 1 秒 = 32000 bytes
    n_windows = len(pcm_full) // window_size
    print(f"    共 {n_windows} 个窗口")
    
    for i in range(n_windows):
        start = i * window_size
        end = start + window_size
        pcm_window = pcm_full[start:end]
        rms = _rms_energy(pcm_window)
        has_sp = _has_speech(pcm_window, 20.0)
        
        if not has_sp:
            print(f"    窗口{i}: RMS={rms:.1f} → 被过滤")
            continue
        
        result = asr.transcribe(pcm_window, SAMPLE_RATE)
        text = result.text if result else ""
        is_wake = wake.detect(text) if text else False
        print(f"    窗口{i}: RMS={rms:.1f} → '{text}' → 唤醒={is_wake}")

    # 测试 3: 无预过滤
    print("\n  ─── 测试 3: 无预过滤 (silence_threshold=0) ───")
    asr_no_filter = create_asr({"silence_threshold": 0})
    for i in range(n_windows):
        start = i * window_size
        end = start + window_size
        pcm_window = pcm_full[start:end]
        result = asr_no_filter.transcribe(pcm_window, SAMPLE_RATE)
        text = result.text if result else ""
        print(f"    窗口{i}: '{text}'")

    print("\n  ✅ 验证完成")

if __name__ == "__main__":
    main()