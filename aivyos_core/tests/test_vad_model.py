"""测试 FunASR + VAD 模型组合 — 生产环境标准用法。"""
import asyncio, sys, os, wave, struct, io, re, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.funasr_backend import _rms_energy

SAMPLE_RATE = 16000
FRAME_MS = 32

async def main():
    print("=" * 60)
    print("🔬 FunASR + VAD 模型组合测试")
    print("=" * 60)

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device="7", gain=50.0)
    print("  ✅ 麦克风已打开 (gain=50x)")

    print("  🔄 加载 FunASR + VAD 模型...")
    from funasr import AutoModel
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
        device="cpu",
        disable_update=True,
    )
    print("  ✅ 模型已加载")

    # 录制 5 秒音频
    print("\n  录制 5 秒 (请清晰说话!)...")
    frames = []
    rec_start = time.monotonic()
    async for frame in source.stream():
        if time.monotonic() - rec_start >= 5.0:
            break
        frames.append(frame)
        rms = _rms_energy(b"".join(frames[-10:]))
        sys.stdout.write(f"\r    RMS={rms:.0f}  已录制 {len(frames)*FRAME_MS/1000:.1f}s  ")
        sys.stdout.flush()
    
    pcm = b"".join(frames)
    total_rms = _rms_energy(pcm)
    print(f"\n  ✅ 录制完成 (总RMS={total_rms:.1f})")

    source.close()

    # 保存录制的音频
    save_dir = os.path.join(os.path.dirname(__file__), "captured_diag")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "vad_test_5s.wav")
    with wave.open(save_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    print(f"  💾 已保存: {save_path}")

    # 测试 1: 直接用 BytesIO (无 VAD)
    print("\n  ─── 测试 1: 直接 BytesIO (无 VAD) ───")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    buf.seek(0)
    result1 = model.generate(input=buf, language="zh", use_itn=True, batch_size_s=60)
    if result1:
        raw = result1[0]
        text = re.sub(r"<\|[^>]+\|>", "", raw.get("text", "")).strip()
        print(f"    原始: {raw.get('text', '')}")
        print(f"    清理: '{text}'")

    # 测试 2: 用文件路径 (有 VAD)
    print("\n  ─── 测试 2: 文件路径 (有 VAD) ───")
    result2 = model.generate(input=save_path, language="zh", use_itn=True, batch_size_s=60)
    if result2:
        for i, seg in enumerate(result2):
            text = re.sub(r"<\|[^>]+\|>", "", seg.get("text", "")).strip()
            print(f"    段{i+1}: '{text}' (原始: {seg.get('text', '')[:50]})")

    # 测试 3: 用更长的音频窗口
    print("\n  ─── 测试 3: 直接 PCM (无 VAD) ───")
    result3 = model.generate(input=pcm, language="zh", use_itn=True, batch_size_s=60)
    if result3:
        for i, seg in enumerate(result3):
            text = re.sub(r"<\|[^>]+\|>", "", seg.get("text", "")).strip()
            print(f"    段{i+1}: '{text}'")

    print("\n  ✅ 测试完成")

if __name__ == "__main__":
    asyncio.run(main())