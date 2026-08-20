# -*- coding: utf-8 -*-
"""端到端测试 VoiceSession 真实采集路径（不带互斥，观察 VAD 判定）。"""
import asyncio
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")

from aivyos_core.config import load_config
from aivyos_core.voice.session import VoiceSession


async def main() -> None:
    cfg = load_config()
    # 不强制 mock，走真实 funasr/tts（用户配置）
    session = VoiceSession(cfg)
    print("状态:", session.status())
    print("VAD:", type(session.vad).__name__, "| source:", type(session.source).__name__)
    print("\n开始 8 秒真实采集（请说话）...")
    result = await session.run_turn()
    if result is None:
        print("结果: None")
    else:
        print("结果:", {k: v for k, v in result.items() if k not in ("wav_b64",)})


if __name__ == "__main__":
    asyncio.run(main())
