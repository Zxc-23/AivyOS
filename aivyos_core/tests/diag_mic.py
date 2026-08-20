"""麦克风电平诊断 — 检查麦克风输入电平是否正常。

用法: python diag_mic.py
"""
import asyncio
import os
import sys
import struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource

SAMPLE_RATE = 16000
FRAME_MS = 32
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000

def frame_rms(frame: bytes) -> float:
    """计算帧的 RMS 值。"""
    n = len(frame) // 2
    if n == 0:
        return 0.0
    acc = 0
    for i in range(n):
        (s,) = struct.unpack_from("<h", frame, i * 2)
        acc += s * s
    return (acc / n) ** 0.5

async def main():
    print("🎤 麦克风电平诊断 (5秒采样)")

    import sounddevice as sd
    print(f"   默认输入设备: {sd.default.device[0]}")
    try:
        default_info = sd.query_devices(sd.default.device[0])
        print(f"   设备信息: {default_info['name']}")
        print(f"   输入通道: {default_info['max_input_channels']}")
        print(f"   默认采样率: {default_info['default_samplerate']:.0f}Hz")
    except Exception:
        pass

    print(f"\n   请对着麦克风说话...\n")

    # 尝试多个设备
    devices_to_test = [
        sd.default.device[0],  # 默认
        1,   # 麦克风 (CL100) 1ch 44100
        7,   # 麦克风 (CL100) 1ch 44100 (另一个驱动)
        19,  # 麦克风 (CL100) 1ch 48000
    ]

    best_device = None
    best_rms = 0

    for dev_idx in set(devices_to_test):
        try:
            dev_info = sd.query_devices(dev_idx)
            if dev_info["max_input_channels"] < 1:
                continue

            print(f"\n  测试设备 [{dev_idx}]: {dev_info['name']} ...")

            source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device=dev_idx)

            test_start = asyncio.get_event_loop().time()
            test_end = test_start + 3.0
            rms_values = []

            async for frame in source.stream():
                if asyncio.get_event_loop().time() > test_end:
                    break
                rms = frame_rms(frame)
                rms_values.append(rms)

            source.close()

            if rms_values:
                avg_rms = sum(rms_values) / len(rms_values)
                max_rms = max(rms_values)
                print(f"    平均 RMS={avg_rms:.1f}, 最大 RMS={max_rms:.1f}")

                if max_rms > best_rms:
                    best_rms = max_rms
                    best_device = dev_idx

        except Exception as e:
            print(f"    错误: {e}")

    # 用最佳设备做正式测试
    if best_device is not None and best_rms > 5:
        print(f"\n  ✅ 使用最佳设备 [{best_device}] 进行正式测试 (RMS={best_rms:.0f})")
        source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device=best_device)
    else:
        print(f"\n  ⚠️ 所有设备信号都很弱，使用默认设备继续...")
        source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS)

    duration_s = 5.0
    end_time = asyncio.get_event_loop().time() + duration_s
    start_time = asyncio.get_event_loop().time()

    stats = {
        "min_rms": float("inf"),
        "max_rms": 0,
        "avg_rms": 0,
        "total_frames": 0,
        "frames_above_100": 0,
        "frames_above_500": 0,
        "peak_samples": [],
    }

    async for frame in source.stream():
        now = asyncio.get_event_loop().time()
        if now > end_time:
            break

        rms = frame_rms(frame)
        stats["total_frames"] += 1
        stats["min_rms"] = min(stats["min_rms"], rms)
        stats["max_rms"] = max(stats["max_rms"], rms)
        stats["avg_rms"] += rms
        if rms > 100:
            stats["frames_above_100"] += 1
        if rms > 500:
            stats["frames_above_500"] += 1

        if stats["total_frames"] <= 5:
            samples = struct.unpack_from(f"<{len(frame)//2}h", frame)[:10]
            stats["peak_samples"].append(samples)

        elapsed = now - start_time
        bar_len = 30
        ratio = min(1.0, elapsed / duration_s)
        filled = int(bar_len * ratio)
        bar = "█" * filled + "░" * (bar_len - filled)
        level = "🔴" if rms > 500 else "🟡" if rms > 100 else "🟢" if rms > 10 else "⚪"
        sys.stdout.write(
            f"\r  [{bar}] {elapsed:.1f}s | RMS={rms:.0f} {level} | "
            f"峰值={max(struct.unpack_from(f'<{len(frame)//2}h', frame))}"
        )
        sys.stdout.flush()

    source.close()

    avg = stats["avg_rms"] / max(1, stats["total_frames"])
    print(f"\n\n{'='*50}")
    print("📊 诊断结果")
    print(f"{'='*50}")
    print(f"  总帧数: {stats['total_frames']}")
    print(f"  RMS 最小: {stats['min_rms']:.1f}")
    print(f"  RMS 最大: {stats['max_rms']:.1f}")
    print(f"  RMS 平均: {avg:.1f}")
    print(f"  RMS > 100: {stats['frames_above_100']} 帧 ({stats['frames_above_100']/max(1,stats['total_frames'])*100:.1f}%)")
    print(f"  RMS > 500: {stats['frames_above_500']} 帧 ({stats['frames_above_500']/max(1,stats['total_frames'])*100:.1f}%)")

    print(f"\n  前 5 帧采样值 (前10个样本):")
    for i, samples in enumerate(stats["peak_samples"]):
        print(f"    帧{i}: {list(samples[:10])}")

    if stats["max_rms"] < 10:
        print(f"\n  ⚠️ 麦克风电平极低！请检查：")
        print(f"     1. 麦克风是否已连接")
        print(f"     2. 系统麦克风增益是否设置正确")
        print(f"     3. 是否使用了正确的输入设备")
    elif stats["max_rms"] < 100:
        print(f"\n  ⚠️ 麦克风电平偏低，建议：")
        print(f"     - 提高系统麦克风增益（+20dB 或更高）")
        print(f"     - 靠近麦克风说话")
    else:
        print(f"\n  ✅ 麦克风电平正常")

    # 检查可用设备
    print(f"\n  🔍 可用音频设备:")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                print(f"    [{i}] {dev['name']} (输入: {dev['max_input_channels']}ch, "
                      f"默认SR: {dev['default_samplerate']:.0f}Hz)")
    except Exception as e:
        print(f"    查询失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())