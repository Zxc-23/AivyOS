"""诊断 FunASR API — 测试不同输入格式和参数。"""
import sys
import os
import wave
import struct
import math
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def generate_test_wav(path: str, duration: float = 2.0):
    """生成测试 WAV 文件。"""
    sr = 16000
    n = int(sr * duration)
    data = bytearray(n * 2)
    for i in range(n):
        t = i / sr
        env = 0.0
        if 0.2 < t < 1.8:
            env_t = (t - 0.2) / 1.6
            env = math.sin(math.pi * env_t) ** 0.5
        v = int(150 * env * (0.6 * math.sin(2 * math.pi * 300 * i / sr) + 
                             0.3 * math.sin(2 * math.pi * 800 * i / sr)))
        v = max(-32768, min(32767, v))
        struct.pack_into("<h", data, i * 2, v)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(data))

def main():
    print("=" * 60)
    print("🔍 FunASR API 诊断")
    print("=" * 60)

    from funasr import AutoModel

    print("\n  加载模型...")
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        device="cpu",
        disable_update=True,
    )
    print("  ✅ 模型加载完成")

    # 生成测试音频
    temp_dir = tempfile.gettempdir()
    wav_path = os.path.join(temp_dir, "funasr_test.wav")
    generate_test_wav(wav_path)
    print(f"  ✅ 测试音频: {wav_path}")

    # 方法 1: 文件路径
    print("\n  方法 1: 文件路径")
    result1 = model.generate(input=wav_path, language="zh", use_itn=True)
    if result1:
        text1 = result1[0].get("text", "")
        print(f"    结果: \"{text1}\"")

    # 方法 2: BytesIO (当前方法)
    print("\n  方法 2: BytesIO (WAV)")
    import io
    with open(wav_path, "rb") as f:
        wav_bytes = f.read()
    buf = io.BytesIO(wav_bytes)
    result2 = model.generate(input=buf, language="zh", use_itn=True)
    if result2:
        text2 = result2[0].get("text", "")
        print(f"    结果: \"{text2}\"")

    # 方法 3: 原始 PCM 字节
    print("\n  方法 3: 原始 PCM")
    with wave.open(wav_path, "rb") as wf:
        pcm_data = wf.readframes(wf.getnframes())
    result3 = model.generate(input=pcm_data, language="zh", use_itn=True)
    if result3:
        text3 = result3[0].get("text", "")
        print(f"    结果: \"{text3}\"")

    # 方法 4: numpy array
    print("\n  方法 4: numpy array")
    try:
        import numpy as np
        audio_array = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
        result4 = model.generate(input=audio_array, language="zh", use_itn=True)
        if result4:
            text4 = result4[0].get("text", "")
            print(f"    结果: \"{text4}\"")
    except Exception as e:
        print(f"    ❌ 错误: {e}")

    # 方法 5: 带 sample_rate 参数
    print("\n  方法 5: 指定 sample_rate")
    result5 = model.generate(input=wav_path, language="zh", use_itn=True, sample_rate=16000)
    if result5:
        text5 = result5[0].get("text", "")
        print(f"    结果: \"{text5}\"")

    # 方法 6: 不使用 use_itn
    print("\n  方法 6: 不使用 use_itn")
    result6 = model.generate(input=wav_path, language="zh")
    if result6:
        text6 = result6[0].get("text", "")
        print(f"    结果: \"{text6}\"")

    print(f"\n  所有方法结果汇总:")
    print(f"    方法1 (文件路径): {result1[0].get('text', '') if result1 else 'N/A'}")
    print(f"    方法2 (BytesIO): {result2[0].get('text', '') if result2 else 'N/A'}")
    print(f"    方法3 (PCM字节): {result3[0].get('text', '') if result3 else 'N/A'}")
    print(f"    方法4 (numpy): {result4[0].get('text', '') if result4 else 'N/A'}")
    print(f"    方法5 (采样率): {result5[0].get('text', '') if result5 else 'N/A'}")
    print(f"    方法6 (无ITN): {result6[0].get('text', '') if result6 else 'N/A'}")

    os.remove(wav_path)

if __name__ == "__main__":
    main()