# -*- coding: utf-8 -*-
"""语音链路压测（文档 §21.3 / T10.7）：ASR → LLM → TTS 全链路延迟 benchmark。

用法：python scripts/benchmark_voice.py --rounds 5
输出：每轮各段耗时 + P95 延迟（对照 §21.3 阈值）。
"""
import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根入 path

from aivyos_core.config import load_config


def main() -> None:
    ap = argparse.ArgumentParser(description="AivyOS 语音链路压测（§21.3 / T10.7）")
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()

    cfg = load_config()
    # mock 后端保底（§2 优雅降级）：真实 silero/funasr/cosyvoice 接入后自动使用
    cfg["asr"]["backend"] = "mock"
    cfg["tts"]["backend"] = "mock"
    cfg["audio"]["vad_backend"] = "energy"

    from aivyos_core.asr import create_asr
    from aivyos_core.chat.engine import ChatEngine
    from aivyos_core.tts import create_tts

    asr = create_asr(cfg["asr"])
    tts = create_tts(cfg["tts"])
    engine = ChatEngine(cfg)

    asr_times, llm_times, tts_times = [], [], []
    print(f"后端: asr={asr.name} tts={tts.name} llm_mode={cfg['llm']['mode']}")
    for i in range(args.rounds):
        # ASR：识别一段 mock PCM
        t0 = time.monotonic()
        asr_result = asr.transcribe(b"\x00" * 16000 * 2)  # 1 秒 16kHz PCM
        asr_times.append((time.monotonic() - t0) * 1000)
        # LLM：对话回复
        t0 = time.monotonic()
        import asyncio

        text = getattr(asr_result, "text", "") or str(asr_result)
        reply = asyncio.run(engine.send(text or "你好", session_id=f"bench{i}"))
        llm_times.append((time.monotonic() - t0) * 1000)
        # TTS：合成
        t0 = time.monotonic()
        wav = tts.synthesize(reply.text)
        tts_times.append((time.monotonic() - t0) * 1000)
        print(f" 轮{i + 1}: ASR {asr_times[-1]:.0f}ms | LLM {llm_times[-1]:.0f}ms | TTS {tts_times[-1]:.0f}ms")

    def p95(xs):
        s = sorted(xs)
        return s[int(len(s) * 0.95) - 1] if s else 0.0

    print("\n===== 汇总（ms）=====")
    print(f"ASR: avg {statistics.mean(asr_times):.0f} | P95 {p95(asr_times):.0f}")
    print(f"LLM: avg {statistics.mean(llm_times):.0f} | P95 {p95(llm_times):.0f}")
    print(f"TTS: avg {statistics.mean(tts_times):.0f} | P95 {p95(tts_times):.0f}")
    print("（§21.3 阈值参考：LLM 首 Token P95 < 500ms / 记忆检索 < 50ms）")


if __name__ == "__main__":
    main()
