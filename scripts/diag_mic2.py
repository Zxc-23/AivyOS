# -*- coding: utf-8 -*-
"""深入诊断：不同 hostapi（MME/WASAPI）+ 原生采样率 测试麦克风采集。"""
import math
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")


def try_capture(sd, device, hostapi, samplerate, channels=1, seconds=2, label=""):
    try:
        rec = sd.rec(
            int(seconds * samplerate), samplerate=samplerate, channels=channels,
            dtype="int16", device=device, blocking=True,
            extra_settings=sd.WasapiSettings(exclusive=False) if hostapi == "wasapi" else None,
        )
        pcm = rec.flatten()
        n = len(pcm)
        acc = sum(int(s) * int(s) for s in pcm[: n // 4 * 4])
        rms = math.sqrt(acc / n)
        peak = max(abs(int(s)) for s in pcm)
        print(f"  {label:<34} sr={samplerate:<6} ch={channels} → RMS={rms:>8.1f} peak={peak:>6}")
        return rms
    except Exception as e:
        msg = str(e).encode("utf-8", "replace").decode("utf-8", "replace")
        print(f"  {label:<34} sr={samplerate:<6} ch={channels} → 失败: {msg[:80]}")
        return 0.0


def main() -> None:
    try:
        import sounddevice as sd
    except ImportError:
        print("sounddevice 未安装")
        return

    print("hostapis:")
    for i, ha in enumerate(sd.query_hostapis()):
        print(f"  [{i}] {ha['name']}  默认设备={ha['default_input_device']}")

    print("\n默认输入设备:", sd.default.device)

    # 设备 1 (CL100) 用不同 hostapi 测
    print("\n=== CL100 设备 = 1 ===")
    for ha_idx, ha_name in [(sd.default.hostapi, "MME/默认"), (1, "WASAPI"), (0, "MME显式")]:
        try:
            ha = sd.query_hostapis(ha_idx)
            dev = ha["default_input_device"]
            if dev < 0:
                continue
            d = sd.query_devices(dev)
            print(f"\nhostapi={ha['name']} → 设备[{dev}] {d['name']}")
            if d.get("default_samplerate"):
                try_capture(sd, dev, "wasapi" if "WASAPI" in ha["name"] else "mme",
                            int(d["default_samplerate"]), 1, label="原生采样率")
            try_capture(sd, dev, "wasapi" if "WASAPI" in ha["name"] else "mme",
                        16000, 1, label="16k")
            if d.get("max_input_channels", 0) >= 2:
                try_capture(sd, dev, "wasapi" if "WASAPI" in ha["name"] else "mme",
                            16000, 2, label="16k 双声道")
        except Exception as e:
            print(f"  hostapi[{ha_idx}] 失败: {e}")


if __name__ == "__main__":
    main()
