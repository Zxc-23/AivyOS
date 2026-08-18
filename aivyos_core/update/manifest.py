"""更新清单构建与签名（文档 §1.3 / T8.2）：BLAKE3 分块哈希 + Ed25519 签名 + manifest.signed.json。

CI/CD 五步（§1.3）：构建 → 分块哈希 → 生成清单 → Ed25519 签名（附证书链）→ 发布。
哈希：hashlib.blake2b（BLAKE2b-256，§1.3 脚本同款；BLAKE3 为可选增强）。
分块：4MB（CHUNK_SIZE），大文件支持断点续传逐块校验（§1.3 / §2.2 增量下载基础）。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB chunks（§1.3）


def blake2b_hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def file_blake2b(path: Path, chunk_size: int = 8192) -> str:
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def chunk_hashes(path: Path, chunk_size: int = CHUNK_SIZE) -> List[str]:
    """分块哈希列表（§1.3 分块哈希 / §2.2 增量下载基础）。"""
    hashes: List[str] = []
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            hashes.append(hashlib.blake2b(chunk, digest_size=32).hexdigest())
    return hashes


def aggregate_hash(files: List[Dict[str, Any]]) -> str:
    """全包哈希：所有文件哈希的聚合（§1.3，确定性顺序）。"""
    h = hashlib.blake2b(digest_size=32)
    for entry in sorted(files, key=lambda f: f["path"]):
        h.update(entry["path"].encode())
        h.update(entry["hash"].encode())
    return h.hexdigest()


def build_manifest(
    update_root: Path,
    version: str,
    update_type: str = "feature",
    min_required_version: str = "0.0.0",
    rollback_whitelist: Optional[List[str]] = None,
    timestamp: Optional[int] = None,
    chunk_size: int = CHUNK_SIZE,
) -> Dict[str, Any]:
    """构建更新清单（§1.3 / §1.5 格式）：遍历文件计算哈希与分块哈希。"""
    files: List[Dict[str, Any]] = []
    for p in sorted(update_root.rglob("*")):
        if not p.is_file():
            continue
        files.append({
            "path": str(p.relative_to(update_root)).replace("\\", "/"),
            "size": p.stat().st_size,
            "hash": file_blake2b(p),
            "chunks": chunk_hashes(p, chunk_size) if p.stat().st_size > chunk_size else [],
        })
    return {
        "version": version,
        "update_type": update_type,
        "timestamp": timestamp if timestamp is not None else int(time.time()),
        "min_required_version": min_required_version,
        "package_hash": aggregate_hash(files),
        "files": files,
        "rollback_whitelist": rollback_whitelist or [],
    }


def sign_manifest(manifest: Dict[str, Any], leaf_key, cert_chain: List[Dict[str, Any]]) -> Dict[str, Any]:
    """用 Leaf 私钥签名清单（§1.3 阶段 4）：确定性序列化（sort_keys）。"""
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    signature = leaf_key.sign(manifest_bytes)
    return {
        "manifest": manifest,
        "signature": signature.hex(),
        "signer_pubkey": leaf_key.pubkey_hex,
        "cert_chain": cert_chain,
    }


def save_signed_manifest(signed: Dict[str, Any], out_path: Path) -> Path:
    """写出 manifest.signed.json（§1.3 阶段 4）。"""
    out_path.write_text(json.dumps(signed, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
