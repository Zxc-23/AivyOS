# -*- coding: utf-8 -*-
"""确定性验证 v2：edge-tts 合成真实中文语音 → FunASR 识别（真实人声特征）。"""
import asyncio
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")


async def main() -> None:
    import edge_tts

    from aivyos_core.asr.manager import create_asr
    from aivyos_core.audio.wav import read_wav
    from aivyos_core.config import load_config

    # 1) edge-tts 合成中文语音（输出 mp3；FunASR 直接读文件，无需 wav 解码）
    print("edge-tts 合成语音（zh-CN-XiaoxiaoNeural）...")
    text = "你好，我是艾维，你的私人助理"
    out_path = sys.argv[1] if len(sys.argv) > 1 else r".aivyos_test\tts_test.mp3"
    communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
    await communicate.save(out_path)
    print(f"合成完成: {out_path}")

    # 2) FunASR 识别（模型直接读 mp3 文件，验证识别能力本身）
    cfg = load_config()
    from aivyos_core.asr.funasr_backend import FunASRBackend

    asr = FunASRBackend(silence_threshold=0)  # 0 = 跳过预过滤，只验证模型
    print(f"ASR 后端: {asr.name}")
    result = asr.model.generate(input=str(out_path), language="zh", use_itn=True, batch_size_s=60)
    text = ""
    if result:
        text = result[0].get("text", "")
    print(f"模型输出: {text!r}")
    import re

    cleaned = re.sub(r"<\|[^>]+\|>", "", text).strip()
    print(f"清理后: {cleaned!r}")
    if cleaned:
        print("✅ FunASR 链路正常（能识别合成中文语音）")
    else:
        print("❌ FunASR 空结果")


if __name__ == "__main__":
    asyncio.run(main())
