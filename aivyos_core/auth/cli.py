"""认证 CLI — `python -m aivyos_core.auth`。

用法：
  python -m aivyos_core.auth register 张三 --wav sample.wav [--persona tone=casual]
  python -m aivyos_core.auth verify --wav test.wav
  python -m aivyos_core.auth users
  python -m aivyos_core.auth status
  python -m aivyos_core.auth demo                    # 合成音频演示注册+认证全流程

声纹后端自动降级：speechbrain 缺失时使用零依赖频谱嵌入（诚实标注）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import struct
from pathlib import Path

from aivyos_core.auth.service import AuthService
from aivyos_core.audio.wav import read_wav
from aivyos_core.config import load_config


def _band_indices(seed: float) -> list:
    """seed → 4 个不同频带索引（4 个频率区域各取一带 → 音色频谱分区，碰撞率低）。"""
    import hashlib

    h = hashlib.md5(str(seed).encode()).digest()
    return [1 + h[0] % 5, 6 + h[1] % 5, 11 + h[2] % 5, 16 + h[3] % 3]


def synth_voice(seed: float, duration_s: float = 4.0, sample_rate: int = 16000) -> bytes:
    """合成"说话人"音频：seed 决定占据的频带（音色），用于演示/测试。"""
    from aivyos_core.auth.voiceprint import BAND_HZ

    out = bytearray()
    freqs = [BAND_HZ[i] for i in _band_indices(seed)]
    amps = [0.5 + ((seed * 7.13 * (i + 1)) % 1.0) for i in range(len(freqs))]
    for i in range(int(duration_s * sample_rate)):
        t = i / sample_rate
        v = 0.0
        for idx, f in enumerate(freqs):
            v += amps[idx] * 2500 * math.sin(2 * math.pi * f * t)
        v = v / len(freqs) * (0.6 + 0.4 * math.sin(2 * math.pi * 1.3 * t + seed))  # 能量包络起伏
        out += struct.pack("<h", max(-32768, min(32767, int(v))))
    return bytes(out)


def cmd_register(auth: AuthService, args) -> None:
    if args.wav:
        rate, pcm = read_wav(args.wav)
    else:
        rate, pcm = 16000, synth_voice(1.0)
    persona = {}
    if args.persona:
        for pair in args.persona:
            k, _, v = pair.partition("=")
            persona[k] = v
    result = auth.register(args.name, pcm=pcm, persona=persona or None)
    print(f"注册成功: {json.dumps(result, ensure_ascii=False)}")


def cmd_verify(auth: AuthService, args) -> None:
    if args.wav:
        rate, pcm = read_wav(args.wav)
    else:
        rate, pcm = 16000, synth_voice(args.seed)
    result = asyncio.run(auth.authenticate(pcm=pcm))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def cmd_demo(auth: AuthService) -> None:
    print("== 认证演示（合成音色，§9 专属认证流程）==")
    # 注册两个用户（不同音色）
    r1 = auth.register("张三", pcm=synth_voice(1.0), persona={"tone": "casual"})
    r2 = auth.register("李四", pcm=synth_voice(2.5), persona={"tone": "serious"})
    print(f"注册: {r1['name']} / {r2['name']}（声纹后端: {auth.voice.extractor_name}）")

    # 本人语音 → 通过
    ok = asyncio.run(auth.authenticate(pcm=synth_voice(1.0, duration_s=3.0)))
    print(f"张三本人语音 → {'✓ 通过' if ok.accepted else '✗ 拒绝'} (score={ok.voice_score:.3f}, user={ok.user_id})")
    # 他人语音 → 静默拒绝
    bad = asyncio.run(auth.authenticate(pcm=synth_voice(9.0, duration_s=3.0)))
    print(f"陌生人语音  → {'✓ 通过' if bad.accepted else '✗ 静默拒绝'} (score={bad.voice_score:.3f})")
    # 多用户人格
    print(f"张三人格: {auth.get_user_persona(r1['user_id'])}")
    print(f"状态机: {auth.sm.status()['state']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AivyOS 专属认证 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_reg = sub.add_parser("register", help="注册用户（声纹）")
    p_reg.add_argument("name")
    p_reg.add_argument("--wav", default=None, help="注册音频 WAV（默认合成）")
    p_reg.add_argument("--persona", action="append", default=[], help="人格参数 k=v（可多次）")

    p_ver = sub.add_parser("verify", help="认证（声纹）")
    p_ver.add_argument("--wav", default=None)
    p_ver.add_argument("--seed", type=float, default=1.0)

    sub.add_parser("users", help="列出用户")
    sub.add_parser("status", help="认证状态")
    sub.add_parser("demo", help="合成音频演示")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    auth = AuthService(cfg)

    if args.cmd == "register":
        cmd_register(auth, args)
    elif args.cmd == "verify":
        cmd_verify(auth, args)
    elif args.cmd == "users":
        print(json.dumps(auth.voice.list_users(), ensure_ascii=False, indent=2))
    elif args.cmd == "status":
        print(json.dumps(auth.status(), ensure_ascii=False, indent=2))
    elif args.cmd == "demo":
        cmd_demo(auth)


if __name__ == "__main__":
    main()
