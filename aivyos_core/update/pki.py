"""三层 PKI 密钥体系（文档 §1.1 / T8.1）：Root CA → Intermediate → Leaf 证书签发。

设计原则（§1.1）：
- L0 Root CA：离线 HSM/气隙机器，仅签发 Intermediate（10 年轮换，§1.7）
- L1 Intermediate：CI 签名服务器，签发 Leaf（1 年轮换）
- L2 Leaf：单次发布，签发后销毁（§1.3 阶段 5）

证书结构（§1.5）：type/pubkey/fingerprint/not_before/not_after/issuer_fingerprint。
纯 stdlib：证书签发 = Ed25519 签名证书载荷（不含实际文件，仅密钥元数据 + 有效期）。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from aivyos_core.update.ed25519 import generate_seed, public_key, sign, verify

# 密钥层级（§1.1）
KEY_LEVELS = ("root", "intermediate", "leaf")

# 轮换周期（秒，§1.7）：Root 10 年 / Intermediate 1 年 / Leaf 单次发布
ROTATION_SECONDS = {
    "root": 10 * 365 * 24 * 3600,
    "intermediate": 365 * 24 * 3600,
    "leaf": 24 * 3600,  # Leaf 仅当天有效（§1.5）
}

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _fmt_ts(ts: Optional[int] = None) -> str:
    import datetime

    dt = datetime.datetime.fromtimestamp(ts if ts is not None else time.time(), tz=datetime.timezone.utc)
    return dt.strftime(_TS_FORMAT)


def parse_ts(s: str) -> int:
    import datetime

    dt = datetime.datetime.strptime(s, _TS_FORMAT).replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp())


def fingerprint(pubkey_hex: str) -> str:
    """证书指纹：sha256:hex（§1.5）。"""
    return "sha256:" + hashlib.sha256(bytes.fromhex(pubkey_hex)).hexdigest()


@dataclass
class KeyPair:
    """Ed25519 密钥对 + 私钥（内存态；Leaf 发布后应销毁）。"""

    seed: bytes
    pubkey_hex: str
    level: str = "leaf"

    def public_key_bytes(self) -> bytes:
        return bytes.fromhex(self.pubkey_hex)

    def sign(self, data: bytes) -> bytes:
        return sign(self.seed, data)

    def verify(self, data: bytes, signature: bytes) -> bool:
        return verify(self.public_key_bytes(), data, signature)

    @staticmethod
    def generate(level: str = "leaf") -> "KeyPair":
        seed = generate_seed()
        return KeyPair(seed=seed, pubkey_hex=public_key(seed).hex(), level=level)


def make_cert(
    keypair: KeyPair,
    cert_type: str,
    not_before_ts: int,
    not_after_ts: int,
    issuer_fingerprint: str,
    signer: Optional[KeyPair] = None,
) -> Dict[str, Any]:
    """构建证书（§1.5 结构）。signer 提供则签名（非根证书由上级签发）。"""
    cert = {
        "type": cert_type,
        "pubkey": keypair.pubkey_hex,
        "fingerprint": fingerprint(keypair.pubkey_hex),
        "not_before": _fmt_ts(not_before_ts),
        "not_after": _fmt_ts(not_after_ts),
        "issuer_fingerprint": issuer_fingerprint,
    }
    if signer is not None:
        cert["signature"] = signer.sign(_cert_payload(cert)).hex()
    return cert


def _cert_payload(cert: Dict[str, Any]) -> bytes:
    """证书签名载荷（确定性序列化，不含签名本身）。"""
    import json

    body = {k: v for k, v in cert.items() if k != "signature"}
    return json.dumps(body, sort_keys=True).encode()


def verify_cert(cert: Dict[str, Any], issuer_pubkey_hex: str) -> bool:
    """验证证书由 issuer 签发（§1.4 证书链验证）。"""
    sig = cert.get("signature")
    if not sig:
        return False
    return verify(bytes.fromhex(issuer_pubkey_hex), _cert_payload(cert), bytes.fromhex(sig))


class PKI:
    """三层 PKI 体系：Root（信任锚点，只存公钥）→ Intermediate → Leaf。"""

    def __init__(self, root_pubkey_hex: str) -> None:
        self.root_pubkey_hex = root_pubkey_hex
        self.root_fingerprint = fingerprint(root_pubkey_hex)
        self.intermediate: Optional[Dict[str, Any]] = None
        self.leaf: Optional[Dict[str, Any]] = None

    @staticmethod
    def bootstrap(now: Optional[int] = None) -> tuple["PKI", KeyPair, KeyPair]:
        """全新搭建：Root（离线）+ Intermediate（CI）。返回 (pki, root_key, intermediate_key)。"""
        now = now if now is not None else int(time.time())
        root = KeyPair.generate("root")
        intermediate = KeyPair.generate("intermediate")
        pki = PKI(root.pubkey_hex)
        pki.intermediate = make_cert(
            intermediate, "intermediate",
            now, now + ROTATION_SECONDS["intermediate"],
            pki.root_fingerprint, signer=root,
        )
        return pki, root, intermediate

    def issue_leaf(self, intermediate_key: KeyPair, now: Optional[int] = None) -> KeyPair:
        """用 Intermediate 签发单次 Leaf（§1.1：Leaf 密钥仅用于单次发布）。"""
        now = now if now is not None else int(time.time())
        leaf = KeyPair.generate("leaf")
        self.leaf = make_cert(
            leaf, "leaf",
            now, now + ROTATION_SECONDS["leaf"],
            self.intermediate["fingerprint"], signer=intermediate_key,
        )
        return leaf

    def cert_chain(self) -> List[Dict[str, Any]]:
        """[Leaf, Intermediate]（§1.5 cert_chain 顺序）。"""
        chain = []
        if self.leaf is not None:
            chain.append(self.leaf)
        if self.intermediate is not None:
            chain.append(self.intermediate)
        return chain

    def verify_chain(self, chain: List[Dict[str, Any]], now: Optional[int] = None) -> bool:
        """§1.4 Step 1-2：证书链验证（Leaf→Intermediate→Root 信任锚点）+ 有效期。"""
        if len(chain) != 2:
            return False
        leaf, intermediate = chain
        # Step 1a: Leaf 由 Intermediate 签发
        if not verify_cert(leaf, intermediate["pubkey"]):
            return False
        # Step 1b: Intermediate 由 Root 信任锚点签发（§1.6.2 Root CA 迁移表按序尝试）
        if not verify_cert(intermediate, self.root_pubkey_hex):
            return False
        # Step 2: 有效期（both certs）
        now = now if now is not None else int(time.time())
        for cert in chain:
            if not (parse_ts(cert["not_before"]) <= now <= parse_ts(cert["not_after"])):
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_pubkey": self.root_pubkey_hex,
            "root_fingerprint": self.root_fingerprint,
            "chain": self.cert_chain(),
        }
