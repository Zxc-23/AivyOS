"""生成 AivyOS 应用图标 icons/icon.ico（纯标准库，BMP 格式 ICO）。

用法：python scripts/gen_icon.py [size]（默认 32）
输出：shell/src-tauri/icons/icon.ico（tauri-build 的 Windows 资源文件必需）
"""
import struct
import sys
from pathlib import Path

SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 32


def make_icon_pixels(size: int) -> bytes:
    """生成品牌蓝 (#2563EB) 圆角方块图标，BGRA 底部优先行序。"""
    rows = bytearray()
    for y in range(size):
        for x in range(size):
            # 圆角半径
            cx, cy = x - (size - 1) / 2, y - (size - 1) / 2
            r = (size - 1) / 2
            dist = (cx * cx + cy * cy) ** 0.5
            if dist <= r - size / 8:
                b, g, r_, a = 0xEB, 0x63, 0x25, 255      # #2563EB
            elif dist <= r:
                b, g, r_, a = 0xEB, 0x63, 0x25, int(255 * (r - dist) / (size / 8))
            else:
                b, g, r_, a = 0, 0, 0, 0
            rows += bytes((b, g, r_, a))
    # ICO 需要自底向上（翻转行序）+ AND 掩码
    stride = size * 4
    bottom_up = bytearray()
    for y in range(size - 1, -1, -1):
        bottom_up += rows[y * stride : (y + 1) * stride]
    mask = b"\x00" * ((size + 31) // 32 * 4 * size)  # 32bpp 掩码行
    return bytes(bottom_up) + mask


def make_ico(pixels: bytes, size: int) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(pixels), 22
    )
    bih = struct.pack(
        "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, size * size * 4, 0, 0, 0, 0
    )
    return header + entry + bih + pixels


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "shell" / "src-tauri" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "icon.ico"
    path.write_bytes(make_ico(make_icon_pixels(SIZE), SIZE))
    print(f"已生成 {path} ({path.stat().st_size} bytes, {SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
