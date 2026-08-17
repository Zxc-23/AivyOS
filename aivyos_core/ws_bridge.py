"""WebSocket 实时对话通道（文档 §16.3.2 风格，T1.5 文本输入子系统）。

运行：python -m aivyos_core.ws_bridge [--port 31702]

客户端消息（JSON 文本帧）：
  {"type": "chat",   "text": "...", "session_id": null}
  {"type": "ping"}
服务端回复：
  {"type": "reply",  "session_id": "...", "text": "...", "model": "...", "route": {...}}
  {"type": "pong",   "ts": 123.45}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Optional

from aivyos_core.chat.engine import ChatEngine
from aivyos_core.config import load_config
from aivyos_core.net.ws import WebSocketConnection, WebSocketServer


async def handle_message(engine: ChatEngine, conn: WebSocketConnection, raw: str) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        await conn.send_text(json.dumps({"type": "error", "message": "JSON 解析失败"}, ensure_ascii=False))
        return

    if msg.get("type") == "ping":
        import time

        await conn.send_text(json.dumps({"type": "pong", "ts": time.time()}))
        return

    if msg.get("type") == "chat":
        text = msg.get("text", "")
        if not text:
            await conn.send_text(json.dumps({"type": "error", "message": "text 为空"}, ensure_ascii=False))
            return
        reply = await engine.send(text, session_id=msg.get("session_id"))
        await conn.send_text(
            json.dumps(
                {
                    "type": "reply",
                    "session_id": reply.session_id,
                    "text": reply.text,
                    "model": reply.model,
                    "route": reply.route.to_dict(),
                    "latency_ms": reply.latency_ms,
                },
                ensure_ascii=False,
            )
        )
        return

    await conn.send_text(json.dumps({"type": "error", "message": f"未知消息类型: {msg.get('type')}"}, ensure_ascii=False))


async def amain(args) -> None:
    cfg = load_config(args.config)
    if args.mode:
        cfg["llm"]["mode"] = args.mode
    engine = ChatEngine(cfg)
    ws_cfg = cfg.get("ws", {})
    port = args.port or int(ws_cfg.get("port", 31702))
    host = ws_cfg.get("host", "127.0.0.1")

    server = WebSocketServer(
        host=host, port=port,
        on_message=lambda conn, msg: handle_message(engine, conn, msg),
    )
    await server.start()
    print(f"AivyOS WebSocket 实时通道已启动: ws://{host}:{port}")
    print(f"  记忆后端: {engine.memory.backend_name} | 按 Ctrl+C 停止")

    stop = asyncio.Event()
    try:
        import signal

        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop.set)
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    except NotImplementedError:
        pass
    await stop.wait()
    await server.stop()


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="AivyOS WebSocket 实时通道")
    parser.add_argument("--config", default=None)
    parser.add_argument("--port", type=int, default=None)
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
