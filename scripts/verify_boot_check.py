# -*- coding: utf-8 -*-
"""实机验证 boot.check 完全真实性。"""
import asyncio
import sys

sys.path.insert(0, r"F:\AivyOS\aivyos")

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.server_entry import build_server
from tests import make_config


async def main() -> None:
    cfg = make_config()
    cfg["ipc"]["port"] = 0
    engine = ChatEngine(cfg)
    server = build_server(engine, cfg)
    r = await server._handlers["boot.check"]({})
    print(f"总结: {r['summary']} (progress={r['progress']}%)")
    for c in r["checks"]:
        mark = "OK " if c["ok"] else "FAIL"
        print(f"  [{mark}] {c['name']}: {c['detail']}")


if __name__ == "__main__":
    asyncio.run(main())
