# -*- coding: utf-8 -*-
"""知识沉淀机制验证：真实 LLM 提取 —— 有效知识 vs 寒暄/一次性请求。"""
import asyncio
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.config import load_config
from aivyos_core.knowledge.extract import KnowledgeExtractor


async def main() -> None:
    cfg = load_config()
    engine = ChatEngine(cfg)
    ex = KnowledgeExtractor(router=engine.router)
    print(f"LLM 可用: {engine.router._local_available()}\n")

    cases = [
        "我喜欢喝美式咖啡，每天早上都要来一杯",      # 有效：偏好
        "敏捷开发的意思是快速迭代、持续交付",          # 有效：概念
        "我叫小明，是产品经理，负责 AI 项目",          # 有效：个人信息
        "今天天气不错，出去走走",                      # 寒暄 → 应 skip
        "帮我订一下明天下午的机票",                    # 一次性请求 → 应 skip
        "记得每周五下午三点开项目周会",                # 有效：习惯/日程
        "嗯嗯好的，谢谢",                              # 寒暄 → 应 skip
        "我讨厌吃香菜",                                # 有效：偏好
    ]

    for text in cases:
        r = await ex.extract(text)
        if r is None:
            print(f"[skip] {text[:24]}")
        else:
            print(f"[卡]   {text[:24]} → {r['category']} | {r['title'][:18]} | tags={r['tags'][:2]}")


if __name__ == "__main__":
    asyncio.run(main())
