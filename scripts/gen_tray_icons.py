"""生成 AivyOS 托盘 8 状态图标（纯标准库，PNG 经 zlib）。

用法：python scripts/gen_tray_icons.py
输出：shell/src-tauri/icons/tray/{state}_{size}.png（8 状态 × 16/24/32/48）
图标：品牌色圆底 + 白色状态字形（圈/环/条/叉/暂停杠/闪电三角等），纯像素绘制。
"""

import struct
import zlib
from pathlib import Path

SIZES = (16, 24, 32, 48)
STATES = {
    "idle":      ("#2563EB", "dot"),      # 实心圆
    "listening": ("#0EA5E9", "ring"),     # 圆环
    "working":   ("#059669", "dot"),      # 实心圆（绿）
    "voice":     ("#7C3AED", "bars"),     # 三条竖杠
    "updating":  ("#D97706", "arc"),      # 弧
    "booting":   ("#6366F1", "bolt"),     # 闪电三角
    "error":     ("#DC2626", "cross"),    # 叉
    "paused":    ("#6B7280", "pause"),    # 双竖杠
}


def hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def draw_shape(px, size, shape, color):
    """在 RGBA 像素网格上绘制白色字形（在彩色圆底之上）。"""
    white = (255, 255, 255, 255)
    cx = cy = (size - 1) / 2
    if shape == "dot":
        r = size * 0.22
        for y in range(size):
            for x in range(size):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    px[y][x] = white
    elif shape == "ring":
        r1, r2 = size * 0.30, size * 0.42
        for y in range(size):
            for x in range(size):
                d2 = (x - cx) ** 2 + (y - cy) ** 2
                if r1 * r1 <= d2 <= r2 * r2:
                    px[y][x] = white
    elif shape == "bars":
        w, hh, gap = max(1, size // 12), size * 0.42, size * 0.07
        for i, x0 in enumerate((cx - w - gap, cx, cx + gap)):
            x0 = int(x0)
            for y in range(int(cy - hh), int(cy + hh)):
                for x in range(x0, x0 + w):
                    if 0 <= x < size and 0 <= y < size:
                        px[y][x] = white
    elif shape == "pause":
        w, hh, gap = max(1, size // 10), size * 0.38, size * 0.09
        for x0 in (int(cx - w - gap), int(cx + gap)):
            for y in range(int(cy - hh), int(cy + hh)):
                for x in range(x0, x0 + w):
                    if 0 <= x < size and 0 <= y < size:
                        px[y][x] = white
    elif shape == "cross":
        t = max(1, size // 14)
        for y in range(size):
            for x in range(size):
                d1 = abs((x - cx) - (y - cy))
                d2 = abs((x - cx) + (y - cy) - (size - 1))
                if d1 <= t or d2 <= t:
                    px[y][x] = white
    elif shape == "bolt":
        # 闪电：两个三角形拼合
        for y in range(size):
            for x in range(size):
                t = (y - cy) / max(1, size / 2)
                if -0.5 <= t <= 0.5:
                    half = size * 0.16 * (1 - abs(t))
                    if abs(x - cx) <= half:
                        px[y][x] = white
    elif shape == "arc":
        r1, r2 = size * 0.24, size * 0.38
        for y in range(size):
            for x in range(size):
                d2 = (x - cx) ** 2 + (y - cy) ** 2
                ang = ((x - cx) / (size / 2), (y - cy) / (size / 2))
                top_half = ang[1] < 0
                if r1 * r1 <= d2 <= r2 * r2 and top_half:
                    px[y][x] = white


def make_png(size: int, color_hex: str, shape: str) -> bytes:
    r, g, b = hex_rgb(color_hex)
    px = [[(r, g, b, 255)] * size for _ in range(size)]
    # 圆角矩形底（去四角）
    rad = size * 0.22
    for y in range(size):
        for x in range(size):
            cx = min(x, size - 1 - x)
            cy = min(y, size - 1 - y)
            if cx < rad and cy < rad:
                if (rad - cx) ** 2 + (rad - cy) ** 2 > rad * rad:
                    px[y][x] = (0, 0, 0, 0)
    draw_shape(px, size, shape, color_hex)
    raw = bytearray()
    for row in px:
        raw.append(0)  # filter: None
        for p in row:
            raw += bytes(p)
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "shell" / "src-tauri" / "icons" / "tray"
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for state, (color, shape) in STATES.items():
        for size in SIZES:
            p = out / f"{state}_{size}.png"
            p.write_bytes(make_png(size, color, shape))
            count += 1
    print(f"已生成 {count} 个托盘图标 → {out}")


if __name__ == "__main__":
    main()
