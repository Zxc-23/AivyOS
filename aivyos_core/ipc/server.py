"""IPC 服务端（文档 §16.2/§12.1）：Tauri 壳层 ↔ Python 核心。

传输：
- TCP 回环（默认，零依赖；127.0.0.1:31701）
- Windows Named Pipe（需 pywin32，自动探测；不可用时降级 TCP）

方法注册：`server.method("chat.send")(handler)`，handler 为 async (params) -> result。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Awaitable, Callable, Dict, Optional

from aivyos_core.ipc.protocol import (
    FrameCodec,
    Notification,
    ProtocolError,
    Request,
    Response,
    encode_frame,
    parse_message,
)

log = logging.getLogger(__name__)

Handler = Callable[[Dict[str, Any]], Awaitable[Any]]


class AivyIpcServer:
    """基于 asyncio 的 IPC 服务端（TCP 回环；NamedPipe 可选）。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 31701, pipe_name: Optional[str] = None) -> None:
        self.host = host
        self.port = port
        self.pipe_name = pipe_name or r"\\.\pipe\aivyos_core"
        self._handlers: Dict[str, Handler] = {}
        self._tcp_server: Optional[asyncio.AbstractServer] = None
        self._pipe_task: Optional[asyncio.Task] = None
        self.transport = "none"

    # ---- 方法注册 ----

    def method(self, name: str) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            self._handlers[name] = fn
            return fn

        return deco

    def register(self, name: str, fn: Handler) -> None:
        self._handlers[name] = fn

    # ---- 生命周期 ----

    async def start(self) -> None:
        self._tcp_server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        self.transport = "tcp"
        log.info("IPC TCP 服务已启动: %s:%s（方法数=%d）", self.host, self.port, len(self._handlers))
        if sys.platform == "win32":
            try:
                await self._start_pipe_server()
                self.transport = "tcp+named_pipe"
            except Exception as e:  # pywin32 缺失或管道创建失败 → 保持 TCP
                log.info("Named Pipe 不可用（%s），保持 TCP 回环", e)

    async def _start_pipe_server(self) -> None:
        """Windows Named Pipe（pywin32，可选）。未安装时抛出并回退 TCP。"""
        try:
            import win32file  # type: ignore
            import win32pipe  # type: ignore
            import pywintypes  # type: ignore
        except ImportError as e:
            raise RuntimeError("pywin32 未安装（pip install pywin32）") from e

        async def pipe_loop() -> None:
            while True:
                try:
                    handle = win32pipe.CreateNamedPipe(
                        self.pipe_name,
                        win32pipe.PIPE_ACCESS_DUPLEX,
                        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                        1, 65536, 65536, 0, None,
                    )
                    win32pipe.ConnectNamedPipe(handle, None)
                    await self._serve_pipe_handle(handle, win32file, win32pipe, pywintypes)
                except Exception:
                    await asyncio.sleep(0.2)

        self._pipe_task = asyncio.create_task(pipe_loop())
        log.info("Named Pipe 已监听: %s", self.pipe_name)

    async def _serve_pipe_handle(self, handle, win32file, win32pipe, pywintypes) -> None:
        codec = FrameCodec()

        async def reply_pipe(resp: Response) -> None:
            win32file.WriteFile(handle, encode_frame(resp.to_dict()))

        while True:
            try:
                _, data = win32file.ReadFile(handle, 65536)
            except pywintypes.error:
                break
            if not data:
                break
            for obj in codec.feed(data):
                await self._dispatch(obj, reply_pipe)

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        codec = FrameCodec()
        peer = writer.get_extra_info("peername")
        log.debug("IPC 连接: %s", peer)
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                for obj in codec.feed(chunk):
                    await self._dispatch(obj, lambda resp: self._reply_tcp(writer, resp))
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("IPC 连接异常")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            log.debug("IPC 连接关闭: %s", peer)

    @staticmethod
    async def _reply_tcp(writer: asyncio.StreamWriter, resp: Response) -> None:
        writer.write(encode_frame(resp.to_dict()))
        await writer.drain()

    async def _dispatch(self, obj: Dict[str, Any], reply) -> None:
        try:
            msg = parse_message(obj)
        except ProtocolError as e:
            await reply(Response(id=None, error={"code": -32700, "message": str(e)}))
            return

        if isinstance(msg, Notification):
            handler = self._handlers.get(msg.method)
            if handler:
                try:
                    await handler(msg.params)
                except Exception:
                    log.exception("notification handler 异常: %s", msg.method)
            return

        handler = self._handlers.get(msg.method)
        if handler is None:
            await reply(Response(id=msg.id, error={"code": -32601, "message": f"未知方法: {msg.method}"}))
            return
        try:
            result = await handler(msg.params)
            await reply(Response(id=msg.id, result=result))
        except Exception as e:
            log.exception("方法执行异常: %s", msg.method)
            await reply(Response(id=msg.id, error={"code": -32603, "message": str(e)}))

    async def stop(self) -> None:
        if self._tcp_server:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
        if self._pipe_task:
            self._pipe_task.cancel()
