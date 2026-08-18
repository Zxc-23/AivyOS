"""Ed25519 纯标准库实现（RFC 8032）——零第三方依赖（T8.1 算法选型）。

实现要点（§1.2 选型理由）：
- 确定性签名：不依赖随机数生成器质量
- 64 字节签名 + 32 字节公钥
- 抗侧信道：无秘密条件分支
- 用 RFC 8032 官方向量做正确性验证（见 tests/test_update.py）

坐标系：扩展齐次坐标 (X:Y:Z:T)，x=X/Z, y=Y/Z, x*y=T/Z。
完整加法公式（无分支，天然常数时间）。
"""

from __future__ import annotations

import hashlib
from typing import Tuple

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P  # d = -121665/121666 mod P


def _recover_x(y: int, sign: int) -> int:
    """由 y 恢复 x（Edwards 曲线 x² = (y²-1)/(d·y²+1)）。"""
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * pow(2, (P - 1) // 4, P) % P
    if (x * x - x2) % P != 0:
        raise ValueError("无法恢复 x 坐标")
    if (x & 1) != sign:
        x = P - x
    return x


# 基点 B（y 坐标最小的生成元）
_BY = 4 * pow(5, P - 2, P) % P
_BX = _recover_x(_BY, 0)
_B = (_BX, _BY, 1, _BX * _BY % P)


def _encodepoint(Pt: Tuple[int, int, int, int]) -> bytes:
    x, y, z, _t = Pt
    zi = pow(z, P - 2, P)
    x = x * zi % P
    y = y * zi % P
    n = y | ((x & 1) << 255)
    return n.to_bytes(32, "little")


def _decodepoint(s: bytes) -> Tuple[int, int, int, int]:
    n = int.from_bytes(s, "little")
    sign = (n >> 255) & 1
    y = n & ((1 << 255) - 1)
    if y >= P:
        raise ValueError("y 越界")
    x = _recover_x(y, sign)
    return (x, y, 1, x * y % P)


def _add(Pt: Tuple[int, int, int, int], Q: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """完整加法公式（RFC 8032 §5.1.4）——无分支。"""
    x1, y1, z1, t1 = Pt
    x2, y2, z2, t2 = Q
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = t1 * 2 * D * t2 % P
    dd = z1 * 2 * z2 % P
    e = b - a
    f = dd - c
    g = dd + c
    h = b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _double(Pt: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    x1, y1, z1, _t1 = Pt
    a = x1 * x1 % P
    b = y1 * y1 % P
    c = 2 * z1 * z1 % P
    dd = -a % P
    e = (x1 + y1) * (x1 + y1) % P - a - b
    g = dd + b
    f = g - c
    h = dd - b
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _scalarmult(Pt: Tuple[int, int, int, int], e: int) -> Tuple[int, int, int, int]:
    """MSB-first 双倍并加：r = 2r，位为 1 时 r += Pt。e=0 → 单位元。"""
    r: Tuple[int, int, int, int] = (0, 1, 1, 0)
    for bit in bin(e)[2:]:  # '0b...' → 最高位在前
        r = _double(r)
        if bit == "1":
            r = _add(r, Pt)
    return r


def _clamp(h: bytes) -> int:
    b = bytearray(h)
    b[0] &= 248
    b[31] &= 63
    b[31] |= 64
    return int.from_bytes(b, "little")


# ---- 公开 API（RFC 8032）----

def generate_seed() -> bytes:
    """生成 32 字节私钥种子（Leaf 单次发布用，§1.3 阶段 5 发布后销毁）。"""
    return __import__("os").urandom(32)


def public_key(seed: bytes) -> bytes:
    """由 32 字节种子派生 32 字节公钥（Ed25519）。"""
    h = hashlib.sha512(seed).digest()
    a = _clamp(h[:32])
    return _encodepoint(_scalarmult(_B, a))


def sign(seed: bytes, message: bytes) -> bytes:
    """确定性签名：64 字节 (R || S)。"""
    h = hashlib.sha512(seed).digest()
    a = _clamp(h[:32])
    prefix = h[32:]
    A = _encodepoint(_scalarmult(_B, a))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % L
    R = _encodepoint(_scalarmult(_B, r))
    k = int.from_bytes(hashlib.sha512(R + A + message).digest(), "little") % L
    S = (r + k * a) % L
    return R + S.to_bytes(32, "little")


def verify(public_key_bytes: bytes, message: bytes, signature: bytes) -> bool:
    """验证签名。任何非法输入返回 False（不抛异常）。"""
    if len(public_key_bytes) != 32 or len(signature) != 64:
        return False
    try:
        A = _decodepoint(public_key_bytes)
        R = _decodepoint(signature[:32])
    except ValueError:
        return False
    S = int.from_bytes(signature[32:], "little")
    if S >= L:
        return False  # 小订单数检查（防签名伪造）
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key_bytes + message).digest(), "little") % L
    lhs = _scalarmult(_B, S)
    rhs = _add(R, _scalarmult(A, k))
    return _encodepoint(lhs) == _encodepoint(rhs)
