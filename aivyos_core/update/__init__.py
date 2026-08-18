"""自动更新与签名（Phase 3 Week 10 / T8.x）。

- ed25519：纯 stdlib Ed25519（RFC 8032，§1.2 算法选型）
- pki：三层 PKI 密钥体系（§1.1 / T8.1）
- manifest：BLAKE3 分块哈希 + 清单构建（§1.3 / T8.2）
- verifier：客户端七步验签（§1.4 / T8.3）
- version：版本管理与回滚（§2.3 / T8.6）
- delta：chunk 级增量下载（§2.2 / T8.5）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from aivyos_core.update.delta import DeltaPlanner
from aivyos_core.update.ed25519 import generate_seed, public_key, sign, verify
from aivyos_core.update.manifest import (
    CHUNK_SIZE,
    aggregate_hash,
    build_manifest,
    chunk_hashes,
    file_blake2b,
    save_signed_manifest,
    sign_manifest,
)
from aivyos_core.update.pki import (
    KEY_LEVELS,
    PKI,
    ROTATION_SECONDS,
    KeyPair,
    fingerprint,
    make_cert,
    parse_ts,
    verify_cert,
)
from aivyos_core.update.verifier import ALERT_CODES, MAX_TIMESTAMP_DRIFT_S, UpdateVerifier
from aivyos_core.update.version import Version, VersionError, VersionManager

log = logging.getLogger(__name__)

# 安全审计日志路径（§1.6.2 安全事件上报②）
SECURITY_LOG_NAME = "security_events.jsonl"


def security_log(timestamp: int, code: str, message: str, home: Optional[str] = None) -> None:
    """追加安全审计日志（§1.6.2：隔离 + 审计日志 + 告警）。"""
    import os

    root = Path(home) if home else Path(os.environ.get("AIVYOS_HOME", "."))
    p = root / SECURITY_LOG_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": timestamp, "code": code, "message": message}, ensure_ascii=False) + "\n")


def quarantine_dir(home: Optional[str] = None) -> Path:
    import os

    root = Path(home) if home else Path(os.environ.get("AIVYOS_HOME", "."))
    return root / "quarantine"


__all__ = [
    # ed25519
    "generate_seed", "public_key", "sign", "verify",
    # pki
    "PKI", "KeyPair", "KEY_LEVELS", "ROTATION_SECONDS", "make_cert", "verify_cert", "fingerprint", "parse_ts",
    # manifest
    "CHUNK_SIZE", "build_manifest", "sign_manifest", "save_signed_manifest",
    "file_blake2b", "chunk_hashes", "aggregate_hash",
    # verifier
    "UpdateVerifier", "ALERT_CODES", "MAX_TIMESTAMP_DRIFT_S",
    # version
    "Version", "VersionError", "VersionManager",
    # delta
    "DeltaPlanner",
    # misc
    "security_log", "quarantine_dir",
]
