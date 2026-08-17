"""WebSocket 最小实现测试：握手 / 文本回显 / ping-pong / close。"""

import asyncio
import base64
import os
import socket
import struct
import unittest

from aivyos_core.net.ws import WebSocketServer, compute_accept

from tests import AivyTestCase

# RFC 6455 §1.3 官方测试向量
RFC_KEY = "dGhlIHNhbXBsZSBub25jZQ=="
RFC_ACCEPT = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def _mask_frame(opcode: int, payload: bytes) -> bytes:
    mask = os.urandom(4)
    length = len(payload)
    if length < 126:
        header = bytes([0x80 | opcode, 0x80 | length])
    elif length < 65536:
        header = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", length)
    else:
        header = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", length)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return header + mask + masked


def _parse_server_frame(data: bytes) -> tuple[int, bytes]:
    b0, b1 = data[0], data[1]
    length = b1 & 0x7F
    off = 2
    if length == 126:
        (length,) = struct.unpack(">H", data[2:4])
        off = 4
    return b0 & 0x0F, data[off : off + length]


class TestComputeAccept(AivyTestCase):
    def test_rfc_vector(self):
        self.assertEqual(compute_accept(RFC_KEY), RFC_ACCEPT)


class TestWebSocketServer(AivyTestCase):
    def test_echo_roundtrip(self):
        async def scenario():
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]

            received = []

            async def on_message(conn, text):
                received.append(text)
                await conn.send_text(f"echo:{text}")

            server = WebSocketServer(host="127.0.0.1", port=port, on_message=on_message)
            await server.start()
            try:
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
                self.assertIn(b"101", resp)
                self.assertIn(b"Sec-WebSocket-Accept", resp)

                # 发送掩码文本帧
                writer.write(_mask_frame(0x1, "你好".encode()))
                await writer.drain()
                data = await asyncio.wait_for(reader.read(1024), 5)
                opcode, payload = _parse_server_frame(data)
                self.assertEqual(opcode, 0x1)
                self.assertEqual(payload, "echo:你好".encode())

                # 发送 ping → 期待 pong（opcode 0xA）
                writer.write(_mask_frame(0x9, b"ping"))
                await writer.drain()
                data2 = await asyncio.wait_for(reader.read(1024), 5)
                opcode2, _ = _parse_server_frame(data2)
                self.assertEqual(opcode2, 0xA)

                # close
                writer.write(_mask_frame(0x8, struct.pack(">H", 1000)))
                await writer.drain()
                await asyncio.sleep(0.2)
                writer.close()
                await writer.wait_closed()
            finally:
                await server.stop()

            self.assertEqual(received, ["你好"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
