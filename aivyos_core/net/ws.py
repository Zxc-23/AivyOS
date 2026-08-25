"""最小 WebSocket（RFC6455）服务端 — 零第三方依赖实现。

用途：T1.5 文本输入子系统实时通道 / 语音实时通道（§16.3.2 风格消息）。
支持：握手、文本/二进制帧、ping/pong、close；客户端帧需掩码（规范要求）。
Week 2 不处理分片（continuation）与大帧（>2GB）场景。
"""

from __future__ import annotations

import logging
log = logging.getLogger(__name__)

import asyncio
import base64
import hashlib
import struct
from typing import Awaitable, Callable, Optional, Set

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketError(Exception):
    pass


def compute_accept(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


class WebSocketConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self._buf = bytearray()

    # ---- 握手 ----

    async def handshake(self, request: bytes) -> None:
        text = request.decode("latin-1")
        headers: dict[str, str] = {}
        for line in text.split("\r\n")[1:]:
            if not line:
                continue
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        if headers.get("upgrade", "").lower() != "websocket" or "sec-websocket-key" not in headers:
            raise WebSocketError("非 WebSocket 握手请求")
        accept = compute_accept(headers["sec-websocket-key"])
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        self.writer.write(resp.encode("latin-1"))
        await self.writer.drain()

    # ---- 帧 ----

    async def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = await self.reader.read(65536)
            if not chunk:
                raise WebSocketError("连接关闭")
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    async def read_frame(self) -> tuple[int, bytes]:
        b0, b1 = await self._read_exact(2)
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        length = b1 & 0x7F
        if length == 126:
            (length,) = struct.unpack(">H", await self._read_exact(2))
        elif length == 127:
            (length,) = struct.unpack(">Q", await self._read_exact(8))
        mask = b""
        if masked:
            mask = await self._read_exact(4)
        payload = await self._read_exact(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    async def send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header += struct.pack(">H", length)
        else:
            header.append(127)
            header += struct.pack(">Q", length)
        self.writer.write(bytes(header) + payload)
        await self.writer.drain()

    async def send_text(self, text: str) -> None:
        await self.send_frame(0x1, text.encode("utf-8"))

    async def recv(self) -> Optional[str]:
        """返回下一条文本消息；对端关闭返回 None。自动应答 ping。"""
        while True:
            opcode, payload = await self.read_frame()
            if opcode == 0x8:  # close
                await self.close()
                return None
            if opcode == 0x9:  # ping → pong
                await self.send_frame(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode in (0x1, 0x2):
                return payload.decode("utf-8", errors="replace")

    async def close(self, code: int = 1000) -> None:
        try:
            await self.send_frame(0x8, struct.pack(">H", code))
        except Exception as e:
            log.debug("忽略预期内异常: %s", e, exc_info=True)
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception as e:
            log.debug("忽略预期内异常: %s", e, exc_info=True)


MessageHandler = Callable[["WebSocketConnection", str], Awaitable[None]]
ConnectHandler = Callable[["WebSocketConnection"], Awaitable[None]]


class WebSocketServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 31702,
        on_message: Optional[MessageHandler] = None,
        on_connect: Optional[ConnectHandler] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.on_message = on_message
        self.on_connect = on_connect
        self._server: Optional[asyncio.AbstractServer] = None
        self.connections: Set[WebSocketConnection] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        except Exception:
            writer.close()
            return
        conn = WebSocketConnection(reader, writer)
        try:
            await conn.handshake(request)
        except WebSocketError:
            writer.close()
            return
        self.connections.add(conn)
        try:
            if self.on_connect:
                await self.on_connect(conn)
            while True:
                msg = await conn.recv()
                if msg is None:
                    break
                if self.on_message:
                    await self.on_message(conn, msg)
        except (WebSocketError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self.connections.discard(conn)
            try:
                writer.close()
            except Exception as e:
                log.debug("忽略预期内异常: %s", e, exc_info=True)

    async def stop(self) -> None:
        for conn in list(self.connections):
            await conn.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
