# -*- coding: utf-8 -*-
"""自检模块审计：验证 boot.check 各项的真实性（是否假阳性/假阴性）。"""
import asyncio
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.config import load_config


async def main() -> None:
    cfg = load_config()
    engine = ChatEngine(cfg)

    print("=== 1. LLM 路由 backends_status（不探测可用性）===")
    routes = engine.router.backends_status()
    for r in routes:
        print(f"  {r.get('mode')}: available={r.get('available')}")
    # 对比真实探测
    try:
        local_ok = engine.router._local_available()
        print(f"  真实 Ollama 探测: {local_ok}")
    except Exception as e:
        print(f"  探测异常: {e}")

    print("\n=== 2. 记忆系统 backend_name（不验证读写）===")
    print(f"  backend_name = {engine.memory.backend_name}")
    try:
        hits = await engine.memory.search("测试", top_k=1)
        print(f"  真实检索: {len(hits)} 条（可读写）")
    except Exception as e:
        print(f"  真实检索异常: {e}")

    print("\n=== 3. 语音模块 vs.status（不验证模型就绪）===")
    from aivyos_core.voice.session import VoiceSession
    vs = VoiceSession(cfg, engine)
    st = vs.status()
    print(f"  status = asr={st.get('asr')}, tts={st.get('tts')}")
    print(f"  asr_ready = {getattr(vs.asr, '_warmed_up', 'N/A')}（FunASR 是否已预热）")


if __name__ == "__main__":
    asyncio.run(main())
