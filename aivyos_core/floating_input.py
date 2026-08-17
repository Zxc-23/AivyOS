"""悬浮输入框（任务 T1.5 文本输入子系统：悬浮输入框，tkinter 可选）。

零依赖实现（stdlib tkinter）：置顶迷你输入窗，回车提交给处理器。
tkinter 不可用（无 GUI 环境）时导入安全，实例化抛 FloatingInputUnavailable。
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional


class FloatingInputUnavailable(RuntimeError):
    pass


class FloatingInputBox:
    """置顶悬浮输入框：回车回调提交文本。"""

    def __init__(
        self,
        handler: Callable[[str], Awaitable[None]],
        title: str = "AivyOS",
        width: int = 420,
        on_loop=None,
    ) -> None:
        try:
            import tkinter as tk
            import tkinter.font as tkfont  # noqa: F401
        except ImportError as e:
            raise FloatingInputUnavailable(
                "tkinter 不可用（当前环境无 GUI 支持）；请使用 CLI/WebSocket 文本输入"
            ) from e
        self._tk = tk
        self.handler = handler
        self.on_loop = on_loop

        self.root = tk.Tk()
        self.root.title(title)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{width}x40+{self._center_x(width)}+40")

        self.entry = tk.Entry(self.root, font=("Microsoft YaHei", 12))
        self.entry.pack(fill="both", expand=True)
        self.entry.focus_set()
        self.entry.bind("<Return>", lambda e: self.root.after(10, self._submit))
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    @staticmethod
    def _center_x(width: int) -> int:
        try:
            return (FloatingInputBox._screen_width() - width) // 2
        except Exception:
            return 100

    @staticmethod
    def _screen_width() -> int:
        import ctypes

        return ctypes.windll.user32.GetSystemMetrics(0)

    def _submit(self) -> None:
        text = self.entry.get().strip()
        self.entry.delete(0, "end")
        if not text:
            return
        if self.on_loop is not None:
            try:
                self.on_loop.create_task(self.handler(text))
            except Exception:
                asyncio.run(self.handler(text))
        else:
            asyncio.run(self.handler(text))

    def run(self) -> None:
        self.root.mainloop()
