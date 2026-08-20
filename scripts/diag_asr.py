# -*- coding: utf-8 -*-
"""验证：采集真实声音 → FunASR 转写，看是空还是文本。"""
import math
import sys
import time

sys.path.insert(0, r"F:\AivyOS\aivyos")


def main() -> None:
    import sounddevice as sd

    from aivyos_core.asr.manager import create_asr
    from aivyos_core.config import load_config

    cfg = load_config()
    asr_cfg = dict(cfg.get("asr", {}))
    asr = create_asr(asr_cfg)
    print(f"ASR 后端: {asr.name}")

    sr = 16000
    print("\n采集 3 秒（请说一句清晰的话，如：Aivy 你好）...")
    rec = sd.rec(int(3 * sr), samplerate=sr, channels=1, dtype="int16", blocking=True)
    pcm = rec.flatten()
    n = len(pcm)
    acc = sum(int(s) * int(s) for s in pcm[: n // 4 * 4])
    rms = math.sqrt(acc / n)
    print(f"RMS={rms:.1f}")

    print("FunASR 转写中...")
    t0 = time.time()
    result = asr.transcribe(bytes(pcm), sr)
    print(f"耗时 {time.time()-t0:.2f}s")
    print(f"转写结果: {result.text!r}")
    print(f"backend: {result.backend}")


if __name__ == "__main__":
    main()
