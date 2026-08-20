"""快速验证更新后的 ASR 管道 — 使用保存的音频文件。"""
import sys, os, wave
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.asr.manager import create_asr

def main():
    asr = create_asr({"silence_threshold": 20.0, "silence_min_ratio": 0.05})
    print(f"ASR 后端: {asr.name}")

    # 测试噪音 (应返回空)
    noise_path = os.path.join(os.path.dirname(__file__), "captured_audio", "speech_2.wav")
    with wave.open(noise_path, "rb") as wf:
        noise_data = wf.readframes(wf.getnframes())
    result = asr.transcribe(noise_data, 16000)
    print(f"噪音测试: RMS=24 -> text=\"{result.text}\" (应为空)")
    if result.text == "":
        print("  ✅ 噪音已正确过滤")
    else:
        print(f"  ❌ 噪音未过滤: \"{result.text}\"")

    # 测试语音
    speech_path = os.path.join(os.path.dirname(__file__), "captured_audio", "speech_1.wav")
    with wave.open(speech_path, "rb") as wf:
        speech_data = wf.readframes(wf.getnframes())
    result2 = asr.transcribe(speech_data, 16000)
    print(f"语音测试: RMS=54 -> text=\"{result2.text}\"")
    print(f"  置信度: {result2.confidence}")
    if result2.text:
        print("  ✅ 语音已正确转写")
    else:
        print("  ⚠️  语音被过滤 (可能 RMS 过低)")

    print("\n✅ ASR 预过滤验证完成!")

if __name__ == "__main__":
    main()