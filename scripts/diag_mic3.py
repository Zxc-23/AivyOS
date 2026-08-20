# -*- coding: utf-8 -*-
"""对比 sd.rec + sd.wait() 与 blocking=True 的差异。"""
import math
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")


def rms_of(rec):
    pcm = rec.flatten()
    n = len(pcm)
    acc = sum(int(s) * int(s) for s in pcm[: n // 4 * 4])
    return math.sqrt(acc / n), max(abs(int(s)) for s in pcm)


def main() -> None:
    import sounddevice as sd

    sr = 16000
    print("方式A: sd.rec() + sd.wait()")
    try:
        rec = sd.rec(int(2 * sr), samplerate=sr, channels=1, dtype="int16")
        sd.wait()
        rms, peak = rms_of(rec)
        print(f"  RMS={rms:.1f} peak={peak}")
    except Exception as e:
        print(f"  失败: {e}")

    print("方式B: sd.rec(blocking=True)")
    try:
        rec = sd.rec(int(2 * sr), samplerate=sr, channels=1, dtype="int16", blocking=True)
        rms, peak = rms_of(rec)
        print(f"  RMS={rms:.1f} peak={peak}")
    except Exception as e:
        print(f"  失败: {e}")

    print("方式C: InputStream 回调（MicSource 同款）")
    try:
        frames = []
        import queue

        q = queue.Queue()

        def cb(indata, frames, time_info, status):
            q.put(bytes(indata))

        stream = sd.InputStream(samplerate=sr, channels=1, dtype="int16",
                                blocksize=sr * 30 // 1000, callback=cb)
        stream.start()
        import time

        time.sleep(2.0)
        stream.stop()
        stream.close()
        nframes = q.qsize()
        data = b"".join([q.get() for _ in range(nframes)])
        pcm = list(data)
        acc = sum(int(s) * int(s) for s in data[0 : len(data) // 4 * 4])
        n = len(data) // 2
        rms = math.sqrt(acc / max(1, n)) if n else 0.0
        print(f"  帧数={nframes} 字节={len(data)} RMS={rms:.1f}")
    except Exception as e:
        print(f"  失败: {e}")


if __name__ == "__main__":
    main()
