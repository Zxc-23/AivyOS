"""验证 FunASR 预过滤逻辑 — 静音/噪音应返回空结果。"""
import sys
import os
import io
import struct
import wave
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.asr.funasr_backend import FunASRBackend, _rms_energy, _has_speech

SAMPLE_RATE = 16000

def test_helpers():
    """测试辅助函数。"""
    print("=" * 60)
    print("🧪 FunASR 预过滤逻辑验证")
    print("=" * 60)

    # 测试 _rms_energy
    silence = b'\x00' * 3200
    rms = _rms_energy(silence)
    print(f"\n  _rms_energy 测试:")
    print(f"    静音 RMS: {rms:.1f} (期望: 0.0)")

    # 测试正弦波
    sine = bytearray(3200)
    for i in range(1600):
        v = int(100 * math.sin(2 * math.pi * 1000 * i / SAMPLE_RATE))
        struct.pack_into('<h', sine, i * 2, max(-32768, min(32767, v)))
    rms_sine = _rms_energy(bytes(sine))
    print(f"    正弦波 RMS: {rms_sine:.1f} (期望: ~70)")

    # 测试 _has_speech
    has_speech_silence = _has_speech(silence, threshold=15.0)
    has_speech_sine = _has_speech(bytes(sine), threshold=15.0)
    print(f"\n  _has_speech 测试:")
    print(f"    静音 has_speech(15): {has_speech_silence} (期望: False)")
    print(f"    正弦波 has_speech(15): {has_speech_sine} (期望: True)")

    # 测试更长的音频
    long_sine = bytearray(SAMPLE_RATE * 2)
    for i in range(SAMPLE_RATE):
        v = int(100 * math.sin(2 * math.pi * 1000 * i / SAMPLE_RATE))
        struct.pack_into('<h', long_sine, i * 2, max(-32768, min(32767, v)))
    has_speech_long = _has_speech(bytes(long_sine), threshold=15.0)
    print(f"    1秒正弦波 has_speech(15): {has_speech_long} (期望: True)")

    # 测试长静音
    long_silence = b'\x00' * SAMPLE_RATE * 2
    has_speech_long_sil = _has_speech(long_silence, threshold=15.0)
    print(f"    1秒静音 has_speech(15): {has_speech_long_sil} (期望: False)")

    # 测试 FunASR 后端
    print(f"\n  FunASR 后端测试:")
    asr = FunASRBackend(silence_threshold=15.0)

    # 静音应返回空
    result_silence = asr.transcribe(silence, SAMPLE_RATE)
    print(f"    静音转写: \"{result_silence.text}\" (期望: \"\")")
    ok1 = result_silence.text == ""

    # 正弦波也应返回空 (非语音)
    result_sine = asr.transcribe(bytes(sine), SAMPLE_RATE)
    print(f"    正弦波转写: \"{result_sine.text}\" (期望: \"\")")
    ok2 = result_sine.text == ""

    # 长正弦波
    result_long = asr.transcribe(bytes(long_sine), SAMPLE_RATE)
    print(f"    1秒正弦波转写: \"{result_long.text}\" (期望: \"\")")
    ok3 = result_long.text == ""

    print(f"\n  {'='*60}")
    if ok1 and ok2 and ok3:
        print("  ✅ 所有预过滤测试通过!")
    else:
        print(f"  ❌ 测试失败: 静音={ok1}, 正弦波短={ok2}, 正弦波长={ok3}")

if __name__ == "__main__":
    test_helpers()