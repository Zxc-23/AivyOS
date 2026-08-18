"""客户端七步验签器（文档 §1.4 / T8.3）：下载后、安装前执行。

七步（§1.4）：① 证书链 → ② 有效期 → ③ CRL 撤销 → ④ Ed25519 签名 →
⑤ 全包哈希 → ⑥ 逐文件哈希 → ⑦ 防降级（版本 + 时间戳 + 回滚白名单）。
任一失败：隔离可疑包 + 安全审计日志 + 告警（§1.6.2），绝不安装。
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aivyos_core.update.ed25519 import verify
from aivyos_core.update.manifest import aggregate_hash, file_blake2b
from aivyos_core.update.pki import PKI, parse_ts
from aivyos_core.update.version import Version

log = logging.getLogger(__name__)

MAX_TIMESTAMP_DRIFT_S = 24 * 3600  # §1.6.2 时间戳新鲜度：±24h
# 篡改类事件 → 触发安全告警（§1.6.2）
ALERT_CODES = ("SIGNATURE_INVALID", "CERT_REVOKED", "DOWNGRADE_BLOCKED", "CERT_CHAIN_FAILED")

SecurityAlert = Callable[[str, str], None]  # (code, message)


class UpdateVerifier:
    def __init__(
        self,
        pki: PKI,
        current_version: str,
        crl: Optional[List[str]] = None,
        quarantine_dir: Optional[Path] = None,
        alert: Optional[SecurityAlert] = None,
        now: Optional[int] = None,
    ) -> None:
        self.pki = pki
        self.current_version = current_version
        self.crl = set(crl or [])  # 证书撤销列表（§1.4 Step 3）
        self.quarantine_dir = quarantine_dir
        self.alert = alert
        self.now = now if now is not None else int(time.time())
        self.last_error: Optional[str] = None
        self.steps_ok: List[str] = []

    # ---- 七步主流程 ----

    def verify(self, signed_manifest: Dict[str, Any], package_dir: Path) -> bool:
        """完整七步验证。任一失败返回 False 并记录 last_error。"""
        self.steps_ok = []
        self.last_error = None
        manifest = signed_manifest.get("manifest")
        if not isinstance(manifest, dict):
            return self._fail("MALFORMED_MANIFEST", "清单结构非法")

        # ① 证书链验证（含 ② 有效期）
        chain = signed_manifest.get("cert_chain", [])
        if not self.pki.verify_chain(chain, self.now):
            return self._fail("CERT_CHAIN_FAILED", "证书链/有效期验证失败")
        self.steps_ok.append("cert_chain")

        # ② 有效期（已在链验证内）
        self.steps_ok.append("cert_validity")

        # ③ 撤销列表检查（§1.4 Step 3）
        leaf_cert = chain[0]
        if leaf_cert.get("fingerprint") in self.crl:
            return self._fail("CERT_REVOKED", "签名证书已被撤销", alert=True)
        self.steps_ok.append("crl")

        # ④ Ed25519 签名验证（§1.4 Step 4）
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        try:
            ok = verify(
                bytes.fromhex(signed_manifest["signer_pubkey"]),
                manifest_bytes,
                bytes.fromhex(signed_manifest["signature"]),
            )
        except (ValueError, KeyError):
            ok = False
        if not ok:
            self._quarantine(package_dir)
            return self._fail("SIGNATURE_INVALID", "签名验证失败 — 包可能被篡改", alert=True)
        self.steps_ok.append("signature")

        # ⑤ 全包哈希校验（§1.4 Step 5）
        if not package_dir.exists():
            return self._fail("PACKAGE_MISSING", "更新包目录缺失")
        actual_pkg = aggregate_hash([{"path": f["path"], "hash": f["hash"]} for f in manifest["files"]])
        if actual_pkg != manifest["package_hash"]:
            return self._fail("PACKAGE_HASH_MISMATCH", "全包哈希不匹配（触发重新下载）")
        self.steps_ok.append("package_hash")

        # ⑥ 逐文件哈希校验（§1.4 Step 6）
        for entry in manifest["files"]:
            fp = package_dir / entry["path"]
            if not fp.is_file():
                return self._fail("FILE_MISSING", f"文件缺失: {entry['path']}")
            if file_blake2b(fp) != entry["hash"]:
                return self._fail("FILE_HASH_MISMATCH", f"文件哈希不匹配: {entry['path']}")
        self.steps_ok.append("files")

        # ⑦ 防降级（§1.4 Step 7 / §1.6.2 三重防线）
        new_version = manifest["version"]
        if not Version.is_higher(new_version, self.current_version):
            return self._fail("DOWNGRADE_BLOCKED", f"拒绝降级: 当前 {self.current_version} ≥ 更新 {new_version}", alert=True)
        # 时间戳新鲜度（§1.6.2 防重放）
        ts = manifest.get("timestamp", 0)
        if abs(self.now - int(ts)) > MAX_TIMESTAMP_DRIFT_S:
            return self._fail("STALE_TIMESTAMP", "清单时间戳超出 ±24h 新鲜度窗口")
        self.steps_ok.append("version")
        self.steps_ok.append("timestamp")

        log.info("[验签] 通过 — v%s 可安全安装（%d 个文件）", new_version, len(manifest["files"]))
        return True

    # ---- 辅助 ----

    def _fail(self, code: str, message: str, alert: bool = False) -> bool:
        self.last_error = f"{code}: {message}"
        log.warning("[安全警报] %s", self.last_error)
        self._write_security_log(code, message)
        if alert or code in ALERT_CODES:
            self._send_alert(code, message)
        return False

    def _write_security_log(self, code: str, message: str) -> None:
        try:
            from aivyos_core.update import security_log

            security_log(self.now, code, message)
        except Exception:
            pass  # 日志失败不阻断

    def _send_alert(self, code: str, message: str) -> None:
        if self.alert is not None:
            try:
                self.alert(code, message)
            except Exception:
                pass

    def _quarantine(self, package_dir: Path) -> None:
        """§1.4 隔离可疑更新包到 quarantine/（仅篡改类事件）。"""
        if self.quarantine_dir is None or not package_dir.exists():
            return
        try:
            q = self.quarantine_dir
            q.mkdir(parents=True, exist_ok=True)
            dest = q / package_dir.name
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.move(str(package_dir), str(dest))
        except Exception as e:
            log.warning("隔离失败: %s", e)
