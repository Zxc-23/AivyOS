"""检测音频设备和依赖。"""
import sys
print("=== Python 版本 ===")
print(sys.version)

try:
    import sounddevice as sd
    print("\n=== sounddevice 版本 ===")
    print(sd.__version__)
    
    devices = sd.query_devices()
    print("\n=== 音频输入设备 ===")
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            print(f"  [{i}] {d['name']} (inputs={d['max_input_channels']}, sr={d['default_samplerate']})")
    
    print(f"\n默认输入: {sd.default.device}")
    print(f"默认采样率: {sd.default.samplerate}")
    
    # Try a 1-second test recording
    print("\n=== 1秒音频采集测试 ===")
    import numpy as np
    duration = 1.0
    sr = 16000
    try:
        recording = sd.rec(int(duration * sr), samplerate=sr, channels=1, dtype='int16')
        sd.wait()
        audio_data = recording.flatten()
        rms = np.sqrt(np.mean(audio_data.astype(np.float64) ** 2))
        peak = np.max(np.abs(audio_data))
        print(f"  采集成功: {len(audio_data)} 样本")
        print(f"  RMS={rms:.1f}, Peak={peak}")
        if rms > 50:
            print("  ✅ 检测到声音输入")
        else:
            print("  ⚠️ 输入较安静（可能需要说话测试）")
    except Exception as e:
        print(f"  采集失败: {e}")
        
except ImportError:
    print("❌ sounddevice 未安装")
except Exception as e:
    print(f"❌ sounddevice 错误: {e}")

# Check ASR
print("\n=== ASR 引擎 ===")
try:
    from aivyos_core.asr.manager import create_asr
    asr = create_asr({"backend": "auto"})
    print(f"ASR 后端: {asr.__class__.__name__}")
except Exception as e:
    print(f"ASR 错误: {e}")

# Check VAD
print("\n=== VAD 引擎 ===")
try:
    from aivyos_core.audio.vad import create_vad
    vad = create_vad({"sample_rate": 16000, "frame_ms": 32})
    print(f"VAD 后端: {vad.__class__.__name__}")
except Exception as e:
    print(f"VAD 错误: {e}")

# Check wake word detector
print("\n=== 唤醒词检测 ===")
try:
    from aivyos_core.wake import WakeWordDetector
    wd = WakeWordDetector()
    print(f"唤醒词: {wd.words}")
    print(f"测试 '你好艾薇': {wd.detect('你好艾薇')}")
    print(f"测试 '今天天气好': {wd.detect('今天天气好')}")
except Exception as e:
    print(f"错误: {e}")