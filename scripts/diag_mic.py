# -*- coding: utf-8 -*-
"""诊断：列出音频输入设备 + 采集 2 秒查看能量（验证麦克风工作）。"""
import math
import sys
import time

sys.path.insert(0, r"F:\AivyOS\aivyos")


def main() -> None:
    try:
        import sounddevice as sd
    except ImportError:
        print("sounddevice 未安装")
        return

    print("默认输入设备:", sd.default.device)
    print("输入设备列表:")
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            name = d["name"].encode("utf-8", "replace").decode("utf-8", "replace")
            print(f"  [{i}] {name}  in={d['max_input_channels']}")

    # 支持指定设备
    device = None
    if len(sys.argv) > 1:
        try:
            device = int(sys.argv[1])
        except ValueError:
            device = sys.argv[1]
        print(f"\n使用指定设备: {device}")

    # 采集 2 秒，统计 RMS 能量
    print("\n采集 2 秒测试（请说话或保持环境原样）...")
    sr = 16000
    try:
        rec = sd.rec(int(2 * sr), samplerate=sr, channels=1, dtype="int16", device=device)
        sd.wait()
        pcm = rec.flatten()
        n = len(pcm)
        acc = sum(int(s) * int(s) for s in pcm[: n // 4 * 4])
        rms = math.sqrt(acc / n)
        peak = max(abs(int(s)) for s in pcm)
        print(f"采样数: {n}, RMS: {rms:.1f}, 峰值: {peak}")
        if rms < 20:
            print("WARN: 能量极低 —— 麦克风可能静音/未选中正确设备/系统权限未授予")
        elif rms < 200:
            print("环境安静，能量正常（说话时应显著升高）")
        else:
            print("检测到较强信号（环境噪音或语音）")
    except Exception as e:
        print(f"采集失败: {e}")


if __name__ == "__main__":
    main()
