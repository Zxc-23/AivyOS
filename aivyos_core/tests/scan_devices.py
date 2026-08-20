"""快速音频设备扫描 — 测试每个设备的输入电平。"""
import asyncio
import struct
import time
import sounddevice as sd

SAMPLE_RATE = 16000
FRAME_MS = 32
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000

def frame_rms(frame):
    n = len(frame) // 2
    if n == 0:
        return 0.0
    acc = 0
    for i in range(n):
        (s,) = struct.unpack_from("<h", frame, i * 2)
        acc += s * s
    return (acc / n) ** 0.5

async def test_device(dev_idx, duration=2.0):
    try:
        info = sd.query_devices(dev_idx)
        if info["max_input_channels"] < 1:
            return None

        q = asyncio.Queue(maxsize=100)
        loop = asyncio.get_event_loop()

        def cb(indata, frames, t, status):
            try:
                loop.call_soon_threadsafe(q.put_nowait, bytes(indata))
            except Exception:
                pass

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=SAMPLE_RATE * FRAME_MS // 1000,
            device=dev_idx, callback=cb,
        )
        stream.start()

        rms_list = []
        start = time.monotonic()
        while time.monotonic() - start < duration:
            try:
                frame = await asyncio.wait_for(q.get(), timeout=0.5)
                rms_list.append(frame_rms(frame))
            except asyncio.TimeoutError:
                break

        stream.stop()
        stream.close()

        if rms_list:
            return {
                "device": dev_idx,
                "name": info["name"],
                "hostapi": info["hostapi"],
                "avg_rms": sum(rms_list) / len(rms_list),
                "max_rms": max(rms_list),
                "min_rms": min(rms_list),
                "frames": len(rms_list),
            }
    except Exception as e:
        return {"device": dev_idx, "error": str(e)}
    return None

async def main():
    print("🎤 音频设备扫描 (测试每个设备2秒，请对着麦克风说话)\n")

    devices = sd.query_devices()
    input_devices = [i for i, d in enumerate(devices) if d["max_input_channels"] > 0]

    print(f"发现 {len(input_devices)} 个输入设备: {input_devices}\n")

    results = []
    for dev in input_devices:
        result = await test_device(dev, duration=2.0)
        if result:
            results.append(result)
            if "error" in result:
                print(f"  [{dev}] {result.get('name', '')} - 错误: {result['error']}")
            else:
                print(f"  [{dev}] {result['name']} (hostapi={result['hostapi']})")
                print(f"      RMS: avg={result['avg_rms']:.1f} max={result['max_rms']:.1f} min={result['min_rms']:.1f} ({result['frames']}帧)")

    if results:
        best = max([r for r in results if "avg_rms" in r], key=lambda r: r["avg_rms"], default=None)
        if best:
            print(f"\n✅ 推荐设备: [{best['device']}] avg_rms={best['avg_rms']:.1f} max_rms={best['max_rms']:.1f}")

            if best["max_rms"] < 10:
                print("\n⚠️  所有设备信号极弱！建议：")
                print("   1. 打开 Windows 设置 > 系统 > 声音 > 麦克风")
                print("   2. 将麦克风增益调到 +20dB 或更高")
                print("   3. 检查麦克风是否被静音")
                print("   4. 对着麦克风更近、更大声说话")

if __name__ == "__main__":
    asyncio.run(main())