# -*- coding: utf-8 -*-
"""深挖：采集音频 → _has_speech 判定 + 模型原始输出对比。"""
import io
import math
import sys
import wave

sys.path.insert(0, r"F:\AivyOS\aivyos")


def main() -> None:
    import sounddevice as sd

    from aivyos_core.asr.funasr_backend import FunASRBackend, _has_speech, _rms_energy

    sr = 16000
    print("采集 3 秒（请说话）...")
    rec = sd.rec(int(3 * sr), samplerate=sr, channels=1, dtype="int16", blocking=True)
    pcm = bytes(rec.flatten())
    print(f"RMS={_rms_energy(pcm):.1f}")

    # 预过滤判定（默认参数）
    ok = _has_speech(pcm, 15.0, 0.05)
    print(f"_has_speech(threshold=15): {ok}")

    # 低阈值再测
    ok2 = _has_speech(pcm, 5.0, 0.03)
    print(f"_has_speech(threshold=5):  {ok2}")

    # 直接调模型（跳过预过滤）
    backend = FunASRBackend(silence_threshold=0)  # 0 = 禁用预过滤
    print("直接模型转写（跳过预过滤）...")
    result = backend.transcribe(pcm, sr)
    print(f"转写结果: {result.text!r}")

    # 模型原始输出（不过滤标签）
    import re

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    buf.seek(0)
    raw = backend.model.generate(input=buf, language="zh", use_itn=True, batch_size_s=60)
    print(f"模型原始输出: {raw}")
    if raw:
        print(f"原始 text 字段: {raw[0].get('text', '')!r}")


if __name__ == "__main__":
    main()
