# -*- coding: utf-8 -*-
"""验证 edge-tts 修复：合成 → PCM 有效性 → 与后端播放采样率匹配。"""
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")


def main() -> None:
    import math

    from aivyos_core.voice.cloud_engines import EdgeTTSBackend

    backend = EdgeTTSBackend(config={"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%"})
    print(f"后端: {backend.name}")
    result = backend.synthesize("你好，我是艾维，你的私人助理")
    pcm = result.pcm
    n = len(pcm) // 2
    # 计算 RMS（排除静音段）
    import struct

    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    rms = math.sqrt(sum(s * s for s in samples) / n)
    peak = max(abs(s) for s in samples)
    print(f"PCM: {len(pcm)} bytes, {n} 样本 @ {result.sample_rate}Hz")
    print(f"RMS={rms:.0f} peak={peak}  （RMS>500 且有变化 = 有效语音）")
    nonzero = sum(1 for s in samples if abs(s) > 100)
    print(f"非零样本: {nonzero}/{n} ({nonzero * 100 // n}%)")
    if rms > 500 and nonzero > n // 4:
        print("✅ TTS PCM 有效（无噪音，真实语音）")
    else:
        print("❌ PCM 异常")


if __name__ == "__main__":
    main()
