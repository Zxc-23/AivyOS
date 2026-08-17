"""IPC 服务入口：ChatEngine ↔ AivyIpcServer 桥接。

运行：python -m aivyos_core.server_entry [--config PATH] [--mode auto|local|cloud|mock]

暴露方法（Tauri 壳层 / 外部客户端调用）：
  ping           → {"pong": true, "version": ...}
  chat.send      params {text, session_id?} → {text, session_id, model, route, latency_ms, memory_hits}
  session.list   → [ {session_id, messages, updated_at} ]
  session.reset  params {session_id} → {"ok": true}
  persona.get    → {…Big Five…}
  persona.set    params {field, value} → {"ok": bool}
  memory.search  params {query, top_k?} → [ {id, text, score, created_at} ]
  memory.add     params {text} → {"id": ...}
  status         → {backend, routes, persona, home, sessions}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.config import load_config
from aivyos_core.ipc.server import AivyIpcServer
from aivyos_core import __version__


def build_server(engine: ChatEngine, cfg: dict) -> AivyIpcServer:
    ipc_cfg = cfg.get("ipc", {})
    server = AivyIpcServer(
        host=ipc_cfg.get("host", "127.0.0.1"),
        port=int(ipc_cfg.get("port", 31701)),
        pipe_name=ipc_cfg.get("pipe_name"),
    )

    @server.method("ping")
    async def ping(params):
        return {"pong": True, "version": __version__}

    @server.method("chat.send")
    async def chat_send(params):
        reply = await engine.send(params["text"], session_id=params.get("session_id"))
        return {
            "text": reply.text,
            "session_id": reply.session_id,
            "model": reply.model,
            "route": reply.route.to_dict(),
            "latency_ms": reply.latency_ms,
            "memory_hits": reply.memory_hits,
        }

    @server.method("session.list")
    async def session_list(params):
        return engine.list_sessions()

    @server.method("session.reset")
    async def session_reset(params):
        engine.reset_session(params["session_id"])
        return {"ok": True}

    @server.method("persona.get")
    async def persona_get(params):
        return engine.persona.to_dict()

    @server.method("persona.set")
    async def persona_set(params):
        return {"ok": engine.set_persona(params["field"], params["value"])}

    @server.method("memory.search")
    async def memory_search(params):
        hits = await engine.memory.search(params.get("query", ""), top_k=int(params.get("top_k", 5)))
        return [h.to_dict() for h in hits]

    @server.method("memory.add")
    async def memory_add(params):
        rid = await engine.memory.add(params["text"])
        return {"id": rid}

    @server.method("status")
    async def status(params):
        return engine.status()

    return server


async def amain(args) -> None:
    cfg = load_config(args.config)
    if args.mode:
        cfg["llm"]["mode"] = args.mode
    engine = ChatEngine(cfg)
    server = build_server(engine, cfg)
    await server.start()
    print(f"AivyOS IPC 服务已启动（transport={server.transport}）")
    print(f"  端口: {cfg['ipc']['port']}  记忆后端: {engine.memory.backend_name}")
    print("  按 Ctrl+C 停止")

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows 部分环境不支持 add_signal_handler
    await stop.wait()
    await server.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AivyOS IPC 服务")
    parser.add_argument("--config", default=None)
    parser.add_argument("--mode", choices=["auto", "local", "cloud", "mock"], default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
