# -*- coding: utf-8 -*-
"""验证：图谱数据 + 单卡导出 + '记得'LLM 沉淀。"""
import asyncio
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")

from pathlib import Path

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.config import load_config
from aivyos_core.knowledge.extract import KnowledgeExtractor
from aivyos_core.knowledge.service import KnowledgeService
from aivyos_core.knowledge.store import KnowledgeStore


async def main() -> None:
    cfg = load_config()
    engine = ChatEngine(cfg)
    home = Path(".aivyos_test") / "knowledge_verify2"
    home.mkdir(parents=True, exist_ok=True)
    f = home / "knowledge.jsonl"
    f.unlink(missing_ok=True)
    svc = KnowledgeService(KnowledgeStore(f), KnowledgeExtractor(router=engine.router))

    # 1) '记得'句式 LLM 沉淀
    r = await svc.ingest("记得每周五下午三点开项目周会")
    print(f"[记得] {r['action'] if r else 'skip'} → {r['card']['title'] if r else '-'} / {r['card']['category'] if r else '-'}")
    await svc.ingest("我喜欢喝美式咖啡")
    await svc.ingest("敏捷开发的意思是快速迭代")

    # 2) 关联 + 图谱
    cards = svc.list_all()
    if len(cards) >= 2:
        svc.link(cards[0].id, cards[1].id)
    g = svc.graph()
    print(f"[图谱] {len(g['nodes'])} 节点, {len(g['edges'])} 边")

    # 3) 导出单卡
    if cards:
        md = svc.export_card(cards[0].id, "markdown")
        print(f"[导出-md] {md['text'][:80]}...")
        js = svc.export_card(cards[0].id, "json")
        print(f"[导出-json] 长度 {len(js['text'])}")
    print("SMOKE_VERIFY_OK")


if __name__ == "__main__":
    asyncio.run(main())
