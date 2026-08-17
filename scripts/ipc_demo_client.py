"""IPC 演示客户端：连接 AivyOS 核心服务，调用 ping / chat.send / status。

用法：先启动 `python -m aivyos_core.server_entry`，再运行本脚本。
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aivyos_core.ipc.protocol import FrameCodec, encode_frame


async def call(host: str, port: int, requests: list[dict]) -> list[dict]:
    reader, writer = await asyncio.open_connection(host, port)
    codec = FrameCodec()
    for req in requests:
        writer.write(encode_frame(req))
    await writer.drain()

    responses: list[dict] = []
    try:
        while len(responses) < len(requests):
            chunk = await asyncio.wait_for(reader.read(65536), 5)
            if not chunk:
                break
            responses.extend(codec.feed(chunk))
    except asyncio.TimeoutError:
        pass
    finally:
        writer.close()
        await writer.wait_closed()
    return responses


async def main() -> None:
    host, port = "127.0.0.1", 31701
    text = sys.argv[1] if len(sys.argv) > 1 else "你好"
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "chat.send", "params": {"text": text}},
        {"jsonrpc": "2.0", "id": 3, "method": "status", "params": {}},
    ]
    responses = await call(host, port, requests)
    for resp in responses:
        print(json.dumps(resp, ensure_ascii=False, indent=2)[:400])
        print("-" * 40)


if __name__ == "__main__":
    asyncio.run(main())
