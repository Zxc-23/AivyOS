"""IPC 层测试：协议编解码 + TCP 服务端（文档 §16.2）。"""

import asyncio
import socket
import unittest

from aivyos_core.ipc.protocol import (
    FrameCodec,
    Notification,
    ProtocolError,
    Request,
    encode_frame,
    parse_message,
)
from aivyos_core.ipc.server import AivyIpcServer

from tests import AivyTestCase


class TestProtocol(AivyTestCase):
    def test_encode_feed_roundtrip(self):
        codec = FrameCodec()
        objs = codec.feed(encode_frame({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}))
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0]["method"], "ping")

    def test_partial_frames(self):
        codec = FrameCodec()
        frame = encode_frame({"jsonrpc": "2.0", "id": 2, "method": "x"})
        out = []
        for i in range(0, len(frame), 3):  # 按 3 字节分片喂入
            out.extend(codec.feed(frame[i : i + 3]))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], 2)

    def test_parse_request_notification(self):
        req = parse_message({"jsonrpc": "2.0", "id": 3, "method": "a", "params": {}})
        self.assertIsInstance(req, Request)
        note = parse_message({"jsonrpc": "2.0", "method": "b"})
        self.assertIsInstance(note, Notification)

    def test_parse_invalid(self):
        with self.assertRaises(ProtocolError):
            parse_message({"foo": 1})


class TestIpcServer(AivyTestCase):
    def test_ping_over_tcp(self):
        async def scenario():
            # 找空闲端口
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]

            server = AivyIpcServer(host="127.0.0.1", port=port)
            results = {}

            @server.method("ping")
            async def ping(params):
                return {"pong": True}

            @server.method("fail")
            async def fail(params):
                raise RuntimeError("boom")

            await server.start()
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                codec = FrameCodec()
                writer.write(encode_frame({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}))
                writer.write(encode_frame({"jsonrpc": "2.0", "id": 2, "method": "fail", "params": {}}))
                writer.write(encode_frame({"jsonrpc": "2.0", "id": 3, "method": "nope", "params": {}}))
                await writer.drain()
                data = await reader.read(65536)
                writer.close()
                await writer.wait_closed()
                responses = codec.feed(data)
                self.assertEqual(len(responses), 3)
                by_id = {r["id"]: r for r in responses}
                self.assertEqual(by_id[1]["result"], {"pong": True})
                self.assertIn("error", by_id[2])
                self.assertEqual(by_id[3]["error"]["code"], -32601)
            finally:
                await server.stop()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
