"""语音会话 CLI — 演示完整语音链路（采集→VAD→ASR→LLM→TTS→输出）。

用法：
  python -m aivyos_core.voice                  # 交互式（麦克风可用则真实录音，否则文本模拟）
  python -m aivyos_core.voice --once "你好"     # 单轮（文本模拟语音，走完整链路）
  python -m aivyos_core.voice --once "你好" --wav out.wav   # 保存合成音频
  python -m aivyos_core.voice --wake-required   # 开启唤醒词门控（Aivy/贾维斯）

无论后端如何降级（mock ASR/TTS），链路均可运行；状态栏会如实标注各组件。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Optional

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.config import load_config
from aivyos_core.voice.session import VoiceSession


async def run_once(session: VoiceSession, text: str, save_wav: Optional[str] = None) -> None:
    if save_wav:
        session.config["tts"]["wav_path"] = save_wav
        # 重建 sink 以落盘
        from aivyos_core.audio.sink import create_sink

        session.sink = create_sink({**session.config["tts"], "sample_rate": session.tts.sample_rate})
    result = await session.run_turn(text_override=text)
    if not result:
        print("（无有效输入）")
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if save_wav:
        print(f"\n合成音频已保存: {save_wav}")


async def interactive(session: VoiceSession, wake_required: bool) -> None:
    st = session.status()
    print("=" * 64)
    print("  AivyOS — 语音会话（Phase 1 Week 2）")
    print(f"  ASR: {st['asr']} | TTS: {st['tts']} | VAD: {st['vad']}")
    print(f"  音源: {st['source']} | 唤醒词: {st['wake_words']} (要求={st['wake_required']})")
    print("  /quit 退出；输入文本模拟语音（无麦克风时）")
    print("=" * 64)

    mic_ok = "synthetic" not in st["source"]
    while True:
        try:
            if mic_ok:
                line = input("\n[按回车开始录音] > ").strip()
            else:
                line = input("\n你说 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        if not line:
            if mic_ok:
                result = await session.run_turn()
                if result:
                    if result.get("reply") is None:
                        print(f"  (未命中唤醒词: {result['text']})")
                    else:
                        print(f"  你: {result['text']}")
                        print(f"  Aivy[{result['model']}]: {result['reply']}")
                        print(f"  (TTS={result['tts_backend']}, wav={result['wav_len']}B)")
                else:
                    print("  (未检测到语音)")
            continue
        if line == "/quit":
            print("再见。")
            break
        result = await session.run_turn(text_override=line)
        if result and result.get("reply"):
            print(f"  Aivy[{result['model']}]: {result['reply']}")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="AivyOS 语音会话")
    parser.add_argument("--config", default=None)
    parser.add_argument("--once", default=None, help="单轮文本模拟语音")
    parser.add_argument("--wav", default=None, help="保存合成音频到 WAV")
    parser.add_argument("--wake-required", action="store_true", help="启用唤醒词门控")
    parser.add_argument("--mode", choices=["auto", "local", "cloud", "mock"], default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.config)
    if args.mode:
        cfg["llm"]["mode"] = args.mode
    if args.wake_required:
        cfg["voice"]["wake_required"] = True

    session = VoiceSession(cfg)
    if args.once:
        asyncio.run(run_once(session, args.once, args.wav))
    else:
        asyncio.run(interactive(session, args.wake_required))


if __name__ == "__main__":
    main()
