"""MCP screenshot Server（文档 §5.1.2 / T3.8）：屏幕截图（mss 可选）+ 1x1 PNG 回退。"""

from __future__ import annotations

import base64
import struct
import zlib
from typing import Any, Dict, Optional, Tuple

from aivyos_core.mcp.types import PermissionLevel, Tool, ToolResult, make_tool


def make_png(width: int, height: int, rgb: Tuple[int, int, int]) -> bytes:
    """最小 PNG 编码器（stdlib zlib + struct）。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b""
    row = b"\x00" + bytes(rgb) * width
    for _ in range(height):
        raw += row
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class ScreenshotServer:
    def __init__(self) -> None:
        self._mss = None
        try:
            import mss  # type: ignore

            self._mss = mss
        except ImportError:
            pass
        self.backend = "mss" if self._mss else "mock"

    async def _capture(self, args: Dict[str, Any]) -> ToolResult:
        if self._mss is not None:
            try:
                with self._mss.mss() as sct:
                    shot = sct.grab(sct.monitors[1])
                    png = self._mss.tools.to_png(shot.rgb, shot.size)
                return ToolResult(True, data={"image": base64.b64encode(png).decode(), "backend": "mss"})
            except Exception as e:
                return ToolResult(False, error=f"截图失败: {e}")
        png = make_png(64, 64, (37, 99, 235))
        return ToolResult(
            True, content="（mock screenshot）接入 mss 后返回真实屏幕图像",
            data={"image": base64.b64encode(png).decode(), "backend": "mock"},
        )

    def tools(self) -> list[Tool]:
        return [
            make_tool(
                "screen_capture", "屏幕截图（L1）",
                {"type": "object", "properties": {}},
                self._capture, PermissionLevel.L1, server="screenshot",
            ),
        ]
