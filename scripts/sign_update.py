# -*- coding: utf-8 -*-
"""CI/CD 更新签名脚本（文档 §1.3 / T8.2）：构建 → 分块哈希 → 清单 → Ed25519 签名 → 发布。

用法：
    python scripts/sign_update.py --root build/update --version 1.3.0 --type feature
    --min 1.2.0 --root-key root.key --intermediate-key intermediate.key --out build/update

流程（§1.3 五步）：① 构建（外部编译）② 分块哈希 ③ 生成 manifest
④ 用 Leaf 私钥 Ed25519 签名 + 附证书链 ⑤ 写出 manifest.signed.json（发布/销毁 Leaf 由 CI 处理）。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根入 path

from aivyos_core.update.ed25519 import public_key as derive_pubkey
from aivyos_core.update.manifest import build_manifest, save_signed_manifest, sign_manifest
from aivyos_core.update.pki import PKI, KeyPair


def load_or_create_key(path: Path, level: str) -> KeyPair:
    """加载已有私钥（hex seed 文件）或生成新 KeyPair（Leaf 单次发布默认新建）。"""
    if path and path.exists():
        seed = bytes.fromhex(path.read_text().strip())
        return KeyPair(seed=seed, pubkey_hex=derive_pubkey(seed).hex(), level=level)
    kp = KeyPair.generate(level)
    if path:
        path.write_text(kp.seed.hex())
    return kp


def main() -> None:
    ap = argparse.ArgumentParser(description="AivyOS 更新签名（§1.3）")
    ap.add_argument("--root", required=True, help="更新包目录（构建产物）")
    ap.add_argument("--version", required=True, help="发布版本（语义版本）")
    ap.add_argument("--type", default="feature", choices=["critical", "feature", "patch"])
    ap.add_argument("--min", default="0.0.0", help="最低支持版本")
    ap.add_argument("--root-key", default=None, help="Root 私钥文件（离线，缺省新建）")
    ap.add_argument("--intermediate-key", default=None, help="Intermediate 私钥文件（CI，缺省新建）")
    ap.add_argument("--out", default=None, help="输出目录（缺省 --root）")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        raise SystemExit(f"更新包目录不存在: {root}")

    # ① ③ 清单构建（BLAKE3 分块哈希）
    manifest = build_manifest(root, args.version, args.type, min_required_version=args.min)

    # ② ④ 三层 PKI + Leaf 签名
    pki, root_kp, intermediate_kp = PKI.bootstrap()
    if args.root_key:
        root_kp = load_or_create_key(Path(args.root_key), "root")
        pki = PKI(root_kp.pubkey_hex)
        intermediate_kp = load_or_create_key(Path(args.intermediate_key), "intermediate")
        pki.intermediate = __import__(
            "aivyos_core.update.pki", fromlist=["make_cert"]
        ).make_cert(
            intermediate_kp, "intermediate",
            manifest["timestamp"], manifest["timestamp"] + 365 * 24 * 3600,
            pki.root_fingerprint, signer=root_kp,
        )
    leaf_kp = pki.issue_leaf(intermediate_kp, manifest["timestamp"])
    signed = sign_manifest(manifest, leaf_kp, pki.cert_chain())

    # ⑤ 发布
    out = Path(args.out) if args.out else root
    out.mkdir(parents=True, exist_ok=True)
    path = save_signed_manifest(signed, out / "manifest.signed.json")
    print(f"[签名] v{args.version} ({args.type}) manifest 已签名 → {path}")
    print(f"[签名] Leaf 公钥: {leaf_kp.pubkey_hex[:16]}…（发布后销毁私钥）")
    print(f"[签名] 包文件数: {len(manifest['files'])} package_hash: {manifest['package_hash'][:16]}…")


if __name__ == "__main__":
    main()
