"""屏幕捕获（文档 §3.3：mss/DXcam 可选；缺失时降级为图像文件输入）。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple


class CaptureUnavailable(RuntimeError):
    pass


class ScreenCapture:
    """屏幕捕获：mss（可选依赖）；全屏/区域截取。"""

    name = "mss"

    def __init__(self) -> None:
        try:
            import mss  # type: ignore

            self.mss = mss
        except ImportError as e:
            raise CaptureUnavailable(
                "屏幕捕获需要 mss：pip install mss（缺失时可使用图像文件输入 load_image）"
            ) from e

    def capture(self, region: Optional[Tuple[int, int, int, int]] = None) -> bytes:
        """截取全屏或区域 (left, top, width, height)，返回 PNG 字节。"""
        import io

        with self.mss.mss() as sct:
            if region:
                shot = sct.grab({"left": region[0], "top": region[1], "width": region[2], "height": region[3]})
            else:
                shot = sct.grab(sct.monitors[1])
        buf = io.BytesIO()
        self.mss.tools.to_png(shot.rgb, shot.size, output=buf)
        return buf.getvalue()


def load_image(path: str | Path) -> bytes:
    """从文件加载图像字节（零依赖回退路径）。"""
    return Path(path).read_bytes()
