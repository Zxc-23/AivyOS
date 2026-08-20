"""FunASR API 验证 — 使用已知音频测试 ASR 管道。

生成合成音频 + 加载已知 WAV 文件，验证 FunASR generate() API 是否正确。
"""
import sys
import os
import io
import struct
import wave
import math
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.asr.manager import create_asr

SAMPLE_RATE = 16000

def generate_tone_wav(freq, duration_s, amplitude=8000):
    """生成正弦波 WAV 音频。"""
    n_samples = int(SAMPLE_RATE * duration_s)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        data = bytearray(n_samples * 2)
        for i in range(n_samples):
            v = int(amplitude * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
            struct.pack_into("<h", data, i * 2, max(-32768, min(32767, v)))
        wf.writeframes(bytes(data))
    buf.seek(0)
    return buf.getvalue()

def save_wav(path: str, pcm: bytes):
    """保存 PCM 数据为 WAV 文件。"""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)

def main():
    print("=" * 60)
    print("🔬 FunASR API 验证")
    print("=" * 60)

    # 1. 测试正弦波音频（验证 ASR 不会对纯静音产生幻觉）
    print("\n  测试 1: 正弦波音频 (1000Hz, 振幅 8000)")
    tone_pcm = generate_tone_wav(1000, 1.0, 8000)
    
    asr = create_asr({})
    print(f"    ASR 后端: {asr.name}")
    
    result = asr.transcribe(tone_pcm, SAMPLE_RATE)
    print(f"    输入: 1kHz 正弦波 (非语音)")
    print(f"    输出: \"{result.text.strip()}\"")
    # 正弦波应该被识别为非语音或产生无意义的输出
    # 这验证 ASR 不会产生幻觉

    # 2. 测试静音
    print("\n  测试 2: 纯静音 (1秒)")
    silence_pcm = b'\x00' * (SAMPLE_RATE * 2)
    result2 = asr.transcribe(silence_pcm, SAMPLE_RATE)
    print(f"    输出: \"{result2.text.strip()}\"")
    # 静音应该返回空或极少内容

    # 3. 测试麦克风录制的音频（之前保存的）
    saved_wav = os.path.join(os.path.dirname(__file__), "test_capture.wav")
    if os.path.exists(saved_wav):
        print(f"\n  测试 3: 之前保存的麦克风录音")
        with wave.open(saved_wav, "rb") as wf:
            pcm_data = wf.readframes(wf.getnframes())
            rate = wf.getframerate()
        print(f"    采样率: {rate}Hz, 长度: {len(pcm_data)//2} 采样点")
        result3 = asr.transcribe(pcm_data, rate)
        print(f"    输出: \"{result3.text.strip()}\"")
    else:
        print(f"\n  测试 3: 跳过 (test_capture.wav 不存在)")

    # 4. 直接测试 FunASR API — 保存文件后用路径加载
    print("\n  测试 4: FunASR 直接 API 测试")
    try:
        from funasr import AutoModel
        
        # 创建一个简单的测试 WAV
        test_wav_path = os.path.join(tempfile.gettempdir(), "test_tone.wav")
        save_wav(test_wav_path, tone_pcm)
        
        model = AutoModel(
            model="iic/SenseVoiceSmall",
            device="cpu",
            disable_update=True,
        )
        
        # 用文件路径
        result_direct = model.generate(
            input=test_wav_path,
            language="zh",
            use_itn=True,
        )
        print(f"    API 直接调用 (文件路径): {result_direct}")
        
        # 检查结果结构
        if result_direct:
            item = result_direct[0]
            print(f"    文本: \"{item.get('text', '')}\"")
            print(f"    所有键: {list(item.keys())}")
            
    except Exception as e:
        print(f"    ❌ FunASR 直接 API 错误: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'='*60}")
    print("📊 总结")
    print(f"{'='*60}")
    print(f"  1. 正弦波测试: 验证 ASR 不会对非语音产生幻觉")
    print(f"  2. 静音测试: 验证 ASR 不会对静音产生幻觉")
    print(f"  3. 麦克风录音: 验证实际音频的 ASR 表现")
    print(f"  4. FunASR API: 验证 API 调用方式是否正确")

if __name__ == "__main__":
    main()