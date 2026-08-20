# -*- coding: utf-8 -*-
"""确定性验证：合成类人声信号 → 完整 ASR 链路（不依赖麦克风/说话时机）。

若此脚本能识别出非空文本 → 链路 OK，真实使用时需清晰说话。
"""
import math
import struct
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")


def make_speech_like(duration_s=2.0, sr=16000):
    """合成带音节调制与共振峰的类人声信号（模拟说话）。"""
    out = bytearray()
    n = int(duration_s * sr)
    # 模拟两个"音节"：低频基频 + 共振峰 + 8Hz 包络
    for i in range(n):
        t = i / sr
        syllable = 0.5 + 0.5 * math.sin(2 * math.pi * 3.5 * t)  # 3.5Hz 音节节奏
        amp = 8000 * (0.4 + 0.6 * syllable)
        v = int(amp * (
            0.55 * math.sin(2 * math.pi * 160 * t) +
            0.30 * math.sin(2 * math.pi * 320 * t) +
            0.12 * math.sin(2 * math.pi * 700 * t) +
            0.03 * math.sin(2 * math.pi * 1800 * t)
        ))
        out += struct.pack("<h", max(-32768, min(32767, v)))
    return bytes(out)


def main() -> None:
    from aivyos_core.asr.manager import create_asr
    from aivyos_core.config import load_config

    cfg = load_config()
    asr = create_asr(cfg.get("asr", {}))
    print(f"ASR 后端: {asr.name}")

    pcm = make_speech_like()
    print(f"合成信号: {len(pcm)} bytes, RMS={sum(int(s)**2 for s in pcm[:8000])/4000:.0f}")

    print("FunASR 转写中...")
    result = asr.transcribe(pcm, 16000)
    print(f"转写结果: {result.text!r}")
    if result.text:
        print("✅ 链路正常：ASR 能识别合成人声")
    else:
        print("❌ 空结果（合成信号可能不像真实人声，或模型参数问题）")


if __name__ == "__main__":
    main()
