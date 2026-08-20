"""直接测试 FunASR 模型原始输出 — 绕过后端后处理。"""
import asyncio, sys, os, wave, struct, io, re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource
from aivyos_core.audio.vad import _rms
from aivyos_core.asr.funasr_backend import _rms_energy

SAMPLE_RATE = 16000
FRAME_MS = 32

async def main():
    print("=" * 60)
    print("🔍 FunASR 原始输出诊断")
    print("=" * 60)

    source = MicSource(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS, device="7", gain=100.0)
    print("  ✅ 麦克风已打开")

    print("  🔄 加载 FunASR 模型...")
    from funasr import AutoModel
    model = AutoModel(model="iic/SenseVoiceSmall", device="cpu", disable_update=True)
    print("  ✅ 模型已加载")

    print("\n  录制 3 个 1 秒窗口 (请说话!)...")
    pcms = []
    for i in range(3):
        print(f"  窗口 {i+1}/3...", flush=True)
        import time
        frames = []
        win_start = time.monotonic()
        async for frame in source.stream():
            if time.monotonic() - win_start >= 1.0:
                break
            frames.append(frame)
        pcm = b"".join(frames)
        pcms.append(pcm)
        print(f"    RMS={_rms_energy(pcm):.1f}")

    source.close()

    for i, pcm in enumerate(pcms):
        print(f"\n  ─── 窗口 {i+1} ───")
        
        # 方法 1: BytesIO WAV (后端方法)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        buf.seek(0)
        
        result = model.generate(input=buf, language="zh", use_itn=True)
        
        if result:
            raw = result[0]
            print(f"    完整结果: {raw}")
            text = raw.get("text", "")
            print(f"    原始text: '{text}'")
            
            # 模拟后端的清理
            cleaned = re.sub(r"<\|[^>]+\|>", "", text).strip()
            print(f"    清理后: '{cleaned}'")
            
            # 模拟后端的幻觉过滤
            hallucination_list = ("。", ".", "嗯", "啊", "哦", "嗯。")
            filtered_text = cleaned
            if cleaned in hallucination_list:
                filtered_text = ""
                print(f"    ❌ 被幻觉过滤器捕获: '{cleaned}' → ''")
            else:
                print(f"    ✅ 通过幻觉过滤: '{filtered_text}'")
        else:
            print(f"    ❌ model.generate() 返回 None/空")

    print("\n  ✅ 诊断完成")

if __name__ == "__main__":
    asyncio.run(main())