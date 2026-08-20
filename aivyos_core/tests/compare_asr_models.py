"""测试不同 FunASR 模型 — SenseVoice vs Paraformer。"""
import sys, os, wave, struct, math, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def generate_test_wav(path: str, duration: float = 2.0):
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
    print("🔬 FunASR 模型对比: SenseVoice vs Paraformer")
    print("=" * 60)

    from funasr import AutoModel

    temp_dir = tempfile.gettempdir()
    wav_path = os.path.join(temp_dir, "asr_compare.wav")
    generate_test_wav(wav_path)

    models = [
        ("SenseVoiceSmall", "iic/SenseVoiceSmall"),
        ("Paraformer-zh", "paraformer-zh"),
    ]

    for name, model_id in models:
        print(f"\n  测试 {name}...")
        try:
            model = AutoModel(
                model=model_id,
                device="cpu",
                disable_update=True,
            )
            result = model.generate(input=wav_path, language="zh", use_itn=True)
            if result:
                raw_text = result[0].get("text", "")
                print(f"    原始输出: {raw_text}")
                
                import re
                clean = re.sub(r"<\|[^>]+\|>", "", raw_text).strip()
                print(f"    清理后: \"{clean}\"")
        except Exception as e:
            print(f"    ❌ 错误: {e}")

    # 也测试保存的用户语音
    user_wav = os.path.join(os.path.dirname(__file__), "captured_audio", "speech_1.wav")
    if os.path.exists(user_wav):
        print(f"\n  测试用户真实语音 (speech_1.wav)...")
        for name, model_id in models:
            print(f"\n    {name}:")
            try:
                model = AutoModel(
                    model=model_id,
                    device="cpu",
                    disable_update=True,
                )
                result = model.generate(input=user_wav, language="zh", use_itn=True)
                if result:
                    raw_text = result[0].get("text", "")
                    import re
                    clean = re.sub(r"<\|[^>]+\|>", "", raw_text).strip()
                    print(f"      原始: {raw_text}")
                    print(f"      清理: \"{clean}\"")
            except Exception as e:
                print(f"      ❌ 错误: {e}")

    os.remove(wav_path)
    print(f"\n  ✅ 模型对比完成")

if __name__ == "__main__":
    main()