# -*- coding: utf-8 -*-
"""知识卡片系统冒烟：真实 LLM 提取 + 沉淀 + 相似调用 + 备份。"""
import asyncio
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.config import load_config
from aivyos_core.knowledge.extract import KnowledgeExtractor
from aivyos_core.knowledge.service import KnowledgeService
from aivyos_core.knowledge.store import KnowledgeStore
from pathlib import Path


async def main() -> None:
    cfg = load_config()
    engine = ChatEngine(cfg)
    home = Path(".aivyos_test") / "knowledge_smoke"
    home.mkdir(parents=True, exist_ok=True)
    (home / "knowledge.jsonl").unlink(missing_ok=True)

    svc = KnowledgeService(
        KnowledgeStore(home / "knowledge.jsonl"),
        KnowledgeExtractor(router=engine.router),
    )
    print(f"LLM 可用: {engine.router._local_available()}")

    # 1) 真实 LLM 提取知识
    r1 = await svc.ingest("我喜欢喝美式咖啡，每天早上都要来一杯")
    print(f"[沉淀1] {r1['action'] if r1 else 'skip'} → {r1['card']['title'] if r1 else '-'}")
    r2 = await svc.ingest("敏捷开发的意思是快速迭代、持续交付")
    print(f"[沉淀2] {r2['action'] if r2 else 'skip'} → {r2['card']['title'] if r2 else '-'}")

    # 2) 相似内容更新（去重）
    r3 = await svc.ingest("我喜欢美式咖啡，不加糖")
    print(f"[沉淀3-相似更新] {r3['action'] if r3 else 'skip'} → v{r3['card']['version'] if r3 else '-'}")

    # 3) 对话中自动调用
    hits = svc.recall("给我来一杯咖啡，记得我不喜欢甜的", limit=2)
    print(f"[调用] {len(hits)} 张相似卡片: " + "; ".join(f"{h['card']['title']}({h['score']:.0%})" for h in hits))

    # 4) 统计 + 备份
    print(f"[统计] {svc.stats()}")
    bk = svc.export_backup(home / "backup.json")
    print(f"[备份] {bk}")
    print("SMOKE_KNOWLEDGE_OK")


if __name__ == "__main__":
    asyncio.run(main())
