"""使用 Windows SAPI 通过 PowerShell 生成 TTS 测试音频。"""
import subprocess
import sys
import os
import wave

SAVE_PATH = os.path.join(os.path.dirname(__file__), "tts_test.wav")

def generate_tts_powershell(text: str, output_path: str) -> bool:
    """通过 PowerShell 调用 Windows SAPI 生成语音。"""
    ps_script = f"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToWaveFile('{output_path}')
$synth.Speak('{text}')
$synth.Dispose()
Write-Host "OK"
"""
    try:
        result = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30
        )
        return "OK" in result.stdout and os.path.exists(output_path)
    except Exception as e:
        print(f"  PowerShell TTS 错误: {e}")
        return False

def generate_sine_wav(path: str, duration: float = 2.0):
    """生成测试正弦波 WAV 文件作为回退。"""
    import struct
    import math
    sr = 16000
    n = int(sr * duration)
    data = bytearray(n * 2)
    for i in range(n):
        t = i / sr
        env = 0.0
        if 0.2 < t < duration - 0.2:
            env_t = (t - 0.2) / (duration - 0.4)
            env = math.sin(math.pi * env_t) ** 0.5
        v = int(200 * env * math.sin(2 * math.pi * 300 * i / sr))
        v = max(-32768, min(32767, v))
        struct.pack_into("<h", data, i * 2, v)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(data))

def main():
    print("=" * 60)
    print("🎙️ 生成测试语音")
    print("=" * 60)

    print("\n  尝试 Windows SAPI TTS...")
    tts_ok = generate_tts_powershell("你好艾薇", SAVE_PATH)
    
    if not tts_ok:
        print("  ❌ SAPI 不可用，使用正弦波回退")
        generate_sine_wav(SAVE_PATH)
    
    if os.path.exists(SAVE_PATH):
        size = os.path.getsize(SAVE_PATH)
        print(f"  ✅ 音频已生成: {SAVE_PATH} ({size} bytes)")
        
        # 分析生成的音频
        with wave.open(SAVE_PATH, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            duration = len(frames) / 2 / 16000
            print(f"     时长: {duration:.2f}s")
            print(f"     采样率: {wf.getframerate()}Hz")
            print(f"     通道: {wf.getnchannels()}")
    else:
        print("  ❌ 生成失败")
        return

    # 用 FunASR 测试这个音频
    print("\n  🔍 用 FunASR 处理...")
    from funasr import AutoModel
    model = AutoModel(model="iic/SenseVoiceSmall", device="cpu", disable_update=True)
    
    result = model.generate(input=SAVE_PATH, language="zh", use_itn=True)
    if result:
        raw = result[0]
        import re
        text = re.sub(r"<\|[^>]+\|>", "", raw.get("text", "")).strip()
        print(f"     原始: {raw.get('text', '')}")
        print(f"     清理: '{text}'")
        
        hallucination_list = ("。", ".", "嗯", "啊", "哦", "嗯。", "我。")
        is_hallucination = text in hallucination_list
        print(f"     是幻觉: {is_hallucination}")
    else:
        print("     ❌ 无结果")

if __name__ == "__main__":
    main()