"""WebSocket 实时通道演示客户端（文档 §16.3.2 / T1.5）。

用法：先启动 `python -m aivyos_core.ws_bridge`，再运行：
  python scripts\ws_demo_client.py ["你好"]
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aivyos_core.net.ws import compute_accept  # noqa: E402


def _mask_frame(opcode: int, payload: bytes) -> bytes:
    mask = os.urandom(4)
    length = len(payload)
    if length < 126:
        header = bytes([0x80 | opcode, 0x80 | length])
    elif length < 65536:
        header = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", length)
    else:
        header = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", length)
    return header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def _parse_server_frame(data: bytes) -> tuple[int, bytes]:
    b0, b1 = data[0], data[1]
    length = b1 & 0x7F
    off = 2
    if length == 126:
        (length,) = struct.unpack(">H", data[2:4])
        off = 4
    elif length == 127:
        (length,) = struct.unpack(">Q", data[2:10])
        off = 10
    return b0 & 0x0F, data[off : off + length]


async def main() -> None:
    port = 31702
    text = sys.argv[1] if len(sys.argv) > 1 else "你好"
    reader, writer = await asyncio.open_connection("127.0.0.1", port)

    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    writer.write(req.encode("latin-1"))
    await writer.drain()
    resp = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    accept = [l for l in resp.decode("latin-1").split("\r\n") if l.lower().startswith("sec-websocket-accept:")]
    if accept:
        expected = compute_accept(key)
        print(f"握手验证: {'✓ 通过' if expected in accept[0] else '✗ 失败'}")

    msg = json.dumps({"type": "chat", "text": text}, ensure_ascii=False)
    writer.write(_mask_frame(0x1, msg.encode("utf-8")))
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), 15)
    opcode, payload = _parse_server_frame(data)
    print(f"收到 [{opcode}] 帧:")
    print(json.dumps(json.loads(payload), ensure_ascii=False, indent=2))

    writer.write(_mask_frame(0x8, struct.pack(">H", 1000)))
    await writer.drain()
    writer.close()
    await writer.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
