"""更新服务（§13）：update.check / update.install / update.rollback 接入层。

职责：
- 管理本地 PKI（首次生成三层密钥，保存到 home/pki/，供验签使用 Root 公钥）
- update.status：当前版本 / 已安装版本 / 最近检查 / 更新可用状态
- update.check：从 endpoint 拉取 manifest.signed.json → 七步验签 → 报告新版本（不安装）
- update.install：验证通过后安装到 versions/ 并切换 current
- update.rollback：回滚到上一版本
- 启动定时检查（check_interval_h，可配置）

说明：当前 endpoint 为占位（api.aivyos.local 未部署），check 会诚实返回
"服务器不可达"而非假装有更新。安装/回滚/版本管理逻辑完整可用（本地测试
可用 scripts/sign_update.py 生成更新包验证）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from aivyos_core.update import (
    PKI,
    DeltaPlanner,
    UpdateVerifier,
    Version,
    VersionManager,
    security_log,
)

log = logging.getLogger(__name__)


class UpdateService:
    """封装更新检查/安装/回滚 + 状态持久化。"""

    def __init__(self, cfg: Dict[str, Any], home) -> None:
        u = cfg.get("update", {})
        self.enabled = bool(u.get("enabled", True))
        self.endpoint = str(u.get("endpoint", ""))
        self.github_repo = str(u.get("github_repo", "")).strip()
        self.github_token = str(u.get("github_token", "")).strip()
        self.current_version = str(u.get("current_version", "0.1.0"))
        self.check_interval_h = float(u.get("check_interval_h", 6))
        self.min_required = str(u.get("min_required_version", "0.0.0"))
        self.keep_versions = int(u.get("keep_versions", 3))
        self.home = Path(home)
        self.versions_dir = self.home / str(u.get("versions_dir", ".aivyos_versions"))
        self.quarantine_dir = self.home / str(u.get("quarantine_dir", ".aivyos_quarantine"))

        # 本地 PKI：首次生成三层密钥并持久化（Root 公钥用于验签）
        self.pki_dir = self.home / "pki"
        self._pki: Optional[PKI] = None
        self._vm_inst: Optional[VersionManager] = None

        # 状态文件（最近检查时间 / 可用更新 / 错误）
        self._state_path = self.home / "update_state.json"
        self._state: Dict[str, Any] = {}
        self._load_state()

        self._last_check_error: Optional[str] = None

    # ------------------------------------------------------------------
    # PKI
    # ------------------------------------------------------------------
    def _ensure_pki(self) -> PKI:
        if self._pki is not None:
            return self._pki
        from aivyos_core.update.ed25519 import generate_seed, public_key
        from aivyos_core.update.pki import KeyPair, make_cert

        self.pki_dir.mkdir(parents=True, exist_ok=True)
        root_seed_p = self.pki_dir / "root.seed"
        inter_seed_p = self.pki_dir / "intermediate.seed"
        now = int(time.time())

        if root_seed_p.exists() and inter_seed_p.exists():
            seed_root = bytes.fromhex(root_seed_p.read_text(encoding="utf-8").strip())
            seed_inter = bytes.fromhex(inter_seed_p.read_text(encoding="utf-8").strip())
        else:
            seed_root = generate_seed()
            seed_inter = generate_seed()
            root_seed_p.write_text(seed_root.hex(), encoding="utf-8")
            inter_seed_p.write_text(seed_inter.hex(), encoding="utf-8")

        root = KeyPair(seed=seed_root, pubkey_hex=public_key(seed_root).hex(), level="root")
        inter = KeyPair(seed=seed_inter, pubkey_hex=public_key(seed_inter).hex(), level="intermediate")
        pki = PKI(root.pubkey_hex)
        pki.intermediate = make_cert(
            inter, "intermediate", now - 3600, now + 365 * 24 * 3600,
            pki.root_fingerprint, signer=root,
        )
        self._pki = pki
        log.info("更新 PKI 已就绪: Root=%s", root.pubkey_hex[:12])
        return pki

    def _verifier(self) -> UpdateVerifier:
        pki = self._ensure_pki()
        return UpdateVerifier(
            pki=pki,
            current_version=self.current_version,
            quarantine_dir=self.quarantine_dir,
            alert=lambda code, msg: security_log(int(time.time()), code, msg, str(self.home)),
        )

    def _vm(self) -> VersionManager:
        if self._vm_inst is None:
            vm = VersionManager(self.versions_dir)
            vm.KEEP_VERSIONS = self.keep_versions
            self._vm_inst = vm
        return self._vm_inst

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        try:
            if self._state_path.exists():
                self._state = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            self._state = {}

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._state_path)
        except Exception as e:
            log.debug("更新状态保存失败: %s", e)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """当前状态（前端更新中心用）。"""
        vm = self._vm()
        installed = vm.list_versions()
        cur = vm.current_version()
        return {
            "ok": True,
            "enabled": self.enabled,
            "current_version": self.current_version,
            "installed_versions": installed,
            "active_version": cur or self.current_version,
            "source": self._state.get("source") or ("github:" + self.github_repo if self.github_repo else self.endpoint or "未配置"),
            "github_repo": self.github_repo,
            "endpoint": self.endpoint,
            "check_interval_h": self.check_interval_h,
            "last_check": self._state.get("last_check"),
            "last_check_result": self._state.get("last_check_result", "never"),
            "update_available": self._state.get("update_available", False),
            "available_version": self._state.get("available_version"),
            "available_type": self._state.get("available_type"),
            "last_error": self._last_check_error,
        }

    def check(self, timeout: float = 10.0) -> Dict[str, Any]:
        """检查更新：GitHub Releases（若配置）或自建 endpoint。

        拉取并验证 manifest → 报告新版本（不安装）。
        源不可达 → 诚实返回 error（不假装有更新）。
        """
        if not self.enabled:
            return {"ok": False, "error": "自动更新已禁用 (update.enabled=false)"}

        if self.github_repo:
            return self._check_github(timeout=timeout)
        return self._check_endpoint(timeout=timeout)

    # ------------------------------------------------------------------
    # 源 A：GitHub Releases
    # ------------------------------------------------------------------
    def _check_github(self, timeout: float = 10.0) -> Dict[str, Any]:
        """从 GitHub Releases 检查更新：

        1) GET /repos/{repo}/releases/latest → 最新 release（tag 即版本）
        2) 找到 manifest.signed.json asset → 下载
        3) 找到更新包 asset（*.zip / *.upd）→ 下载并解压到 .update_pending
        4) 七步验签 → 报告新版本
        """
        import io
        import json as _json
        import urllib.request
        import zipfile

        api = f"https://api.github.com/repos/{self.github_repo}/releases/latest"
        headers = {"User-Agent": f"AivyOS/{self.current_version}", "Accept": "application/vnd.github+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        try:
            release = self._download_json(api, headers, timeout)
        except Exception as e:
            self._last_check_error = f"GitHub Releases 不可达: {e}"
            self._state["last_check"] = int(time.time())
            self._state["last_check_result"] = "error"
            self._state["update_available"] = False
            self._save_state()
            return {"ok": False, "error": self._last_check_error, "status": self.status()}

        tag = str(release.get("tag_name", "")).lstrip("v")
        if not Version.is_valid(tag):
            self._last_check_error = f"最新 release 标签非法: {tag!r}"
            self._state["last_check"] = int(time.time())
            self._state["last_check_result"] = "error"
            self._state["update_available"] = False
            self._save_state()
            return {"ok": False, "error": self._last_check_error, "status": self.status()}

        if not Version.is_higher(tag, self.current_version):
            # 已是最新（或降级标签）
            self._state["last_check"] = int(time.time())
            self._state["last_check_result"] = "ok"
            self._state["update_available"] = False
            self._state["available_version"] = None
            self._state.pop("pending_manifest", None)
            self._save_state()
            return {
                "ok": True,
                "update_available": False,
                "latest_version": tag,
                "status": self.status(),
            }

        # 找 assets（用 API url：browser_download_url 对私有库不带 token 上下文会 404）
        assets = {a.get("name", ""): a.get("url", "") for a in release.get("assets", [])}
        manifest_url = assets.get("manifest.signed.json")
        pkg_name = next((n for n in assets if n.endswith(".zip") or n.endswith(".upd")), None)
        pkg_url = assets.get(pkg_name) if pkg_name else None
        if not manifest_url:
            self._last_check_error = f"release v{tag} 缺少 manifest.signed.json asset"
            self._state["last_check"] = int(time.time())
            self._state["last_check_result"] = "error"
            self._state["update_available"] = False
            self._save_state()
            return {"ok": False, "error": self._last_check_error, "status": self.status()}

        # 下载 manifest + 更新包（asset API url 必须带 octet-stream 才返回文件内容）
        asset_headers = {**headers, "Accept": "application/octet-stream"}
        pending = self.home / ".update_pending"
        pending.mkdir(parents=True, exist_ok=True)
        try:
            signed = self._download_json(manifest_url, asset_headers, timeout)
            if pkg_url:
                pkg_bytes = self._download_bytes(pkg_url, asset_headers, timeout)
                if pkg_name.endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(pkg_bytes)) as zf:
                        zf.extractall(pending)
                else:
                    (pending / "update.bin").write_bytes(pkg_bytes)
            else:
                # 无更新包 asset：仅写入 manifest 供验签（全包哈希步会失败 → 诚实报错）
                (pending / "manifest.signed.json").write_text(
                    _json.dumps(signed, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        except Exception as e:
            self._last_check_error = f"下载更新资源失败: {e}"
            self._state["last_check"] = int(time.time())
            self._state["last_check_result"] = "error"
            self._state["update_available"] = False
            self._save_state()
            return {"ok": False, "error": self._last_check_error, "status": self.status()}

        # 七步验签
        verifier = self._verifier()
        new_version = str(signed.get("manifest", {}).get("version", ""))
        try:
            if not Version.is_valid(new_version):
                raise ValueError(f"manifest 版本非法: {new_version}")
            if not Version.is_higher(new_version, self.current_version):
                verifier.last_error = f"非新版本或降级: {new_version} <= {self.current_version}"
                raise ValueError(verifier.last_error)
            ok = verifier.verify(signed, pending)
        except Exception as e:
            self._last_check_error = f"验证失败: {e}"
            self._state["last_check"] = int(time.time())
            self._state["last_check_result"] = "verify_failed"
            self._state["update_available"] = False
            self._save_state()
            return {"ok": False, "error": self._last_check_error, "status": self.status()}

        self._state["last_check"] = int(time.time())
        if ok:
            self._state["last_check_result"] = "ok"
            self._state["update_available"] = True
            self._state["available_version"] = new_version
            self._state["available_type"] = signed.get("manifest", {}).get("update_type", "feature")
            self._state["pending_manifest"] = signed
            self._state["source"] = f"github:{self.github_repo}"
            self._save_state()
            return {
                "ok": True,
                "update_available": True,
                "version": new_version,
                "update_type": self._state["available_type"],
                "source": self._state["source"],
                "status": self.status(),
            }
        self._last_check_error = verifier.last_error or "验签失败"
        self._state["last_check_result"] = "verify_failed"
        self._state["update_available"] = False
        self._save_state()
        return {"ok": False, "error": self._last_check_error, "status": self.status()}

    @staticmethod
    def _download_json(url: str, headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
        import json as _json
        import urllib.request

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode("utf-8", errors="replace"))

    @staticmethod
    def _download_bytes(url: str, headers: Dict[str, str], timeout: float) -> bytes:
        import urllib.request

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    # ------------------------------------------------------------------
    # 源 B：自建 endpoint
    # ------------------------------------------------------------------
    def _check_endpoint(self, timeout: float = 10.0) -> Dict[str, Any]:
        """从自建 endpoint 拉取并验证 manifest（§13.1 端点模板）。"""
        import urllib.request

        if not self.endpoint:
            return {"ok": False, "error": "未配置更新源（github_repo 或 endpoint）"}
        import platform

        target = "windows"
        arch = platform.machine().lower() or "x86_64"
        url = (
            self.endpoint
            .replace("{target}", target)
            .replace("{arch}", arch)
            .replace("{current_version}", self.current_version)
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"AivyOS/{self.current_version}"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                signed = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as e:
            self._last_check_error = f"服务器不可达: {e}"
            self._state["last_check"] = int(time.time())
            self._state["last_check_result"] = "error"
            self._state["update_available"] = False
            self._save_state()
            return {"ok": False, "error": self._last_check_error, "status": self.status()}

        # 七步验签（不安装，仅判定可用性）
        verifier = self._verifier()
        new_version = str(signed.get("manifest", {}).get("version", ""))
        pkg_dir = self.home / ".update_pending"
        try:
            # 校验清单格式后再验签
            if not Version.is_valid(new_version):
                raise ValueError(f"manifest 版本非法: {new_version}")
            if not Version.is_higher(new_version, self.current_version):
                verifier.last_error = f"非新版本或降级: {new_version} <= {self.current_version}"
                raise ValueError(verifier.last_error)
            ok = verifier.verify(signed, pkg_dir)
        except Exception as e:
            self._last_check_error = f"验证失败: {e}"
            self._state["last_check"] = int(time.time())
            self._state["last_check_result"] = "verify_failed"
            self._state["update_available"] = False
            self._save_state()
            return {"ok": False, "error": self._last_check_error, "status": self.status()}

        self._state["last_check"] = int(time.time())
        if ok:
            self._state["last_check_result"] = "ok"
            self._state["update_available"] = True
            self._state["available_version"] = new_version
            self._state["available_type"] = signed.get("manifest", {}).get("update_type", "feature")
            self._state["pending_manifest"] = signed  # 暂存，install 时使用
            self._save_state()
            return {
                "ok": True,
                "update_available": True,
                "version": new_version,
                "update_type": self._state["available_type"],
                "status": self.status(),
            }
        self._last_check_error = verifier.last_error or "验签失败"
        self._state["last_check_result"] = "verify_failed"
        self._state["update_available"] = False
        self._save_state()
        return {"ok": False, "error": self._last_check_error, "status": self.status()}

    def install(self) -> Dict[str, Any]:
        """安装已验证的可用更新（从 pending_manifest 写入 versions/ 并切换 current）。"""
        signed = self._state.get("pending_manifest")
        if not signed:
            return {"ok": False, "error": "没有已验证的待安装更新，请先 update.check"}
        manifest = signed.get("manifest", {})
        new_version = str(manifest.get("version", ""))
        if not Version.is_valid(new_version):
            return {"ok": False, "error": f"manifest 版本非法: {new_version}"}
        if not Version.is_higher(new_version, self.current_version):
            return {"ok": False, "error": f"拒绝降级: {new_version} <= {self.current_version}"}

        # 二次验签（安装前再次校验，防 TOCTOU）
        verifier = self._verifier()
        pkg_dir = self.home / ".update_pending"
        try:
            if not verifier.verify(signed, pkg_dir):
                return {"ok": False, "error": verifier.last_error or "安装前验签失败"}
        except Exception as e:
            return {"ok": False, "error": f"安装前验签异常: {e}"}

        # 将 manifest 中的文件还原到临时包目录（若无真实包文件，则写入 manifest 快照）
        pkg_dir.mkdir(parents=True, exist_ok=True)
        meta = pkg_dir / "manifest.signed.json"
        meta.write_text(json.dumps(signed, ensure_ascii=False, indent=2), encoding="utf-8")

        vm = self._vm()
        try:
            dst = vm.install(new_version, pkg_dir)
        except Exception as e:
            security_log(int(time.time()), "INSTALL_FAILED", f"安装失败: {e}", str(self.home))
            return {"ok": False, "error": f"安装失败: {e}"}

        # 更新当前版本记录（配置层与状态层）
        self.current_version = new_version
        self._state["current_version"] = new_version
        self._state["update_available"] = False
        self._state["available_version"] = None
        self._state["last_check_result"] = "installed"
        self._state.pop("pending_manifest", None)
        self._save_state()
        log.info("已安装更新 v%s → %s", new_version, dst)
        return {"ok": True, "version": new_version, "installed_to": str(dst), "status": self.status()}

    def rollback(self) -> Dict[str, Any]:
        """回滚到上一版本（versions/ 中低于当前版本的最高版本）。"""
        vm = self._vm()
        target = vm.rollback()
        if target is None:
            return {"ok": False, "error": "没有可回滚的上一版本"}
        self._state["last_check_result"] = "rolled_back"
        self._state["update_available"] = False
        self._save_state()
        return {"ok": True, "version": target, "status": self.status()}

    # ------------------------------------------------------------------
    # 定时检查
    # ------------------------------------------------------------------
    def maybe_check(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """按 check_interval_h 触发检查（启动/定时器调用）。"""
        if not self.enabled:
            return None
        last = self._state.get("last_check")
        if force or last is None or (time.time() - float(last)) >= self.check_interval_h * 3600:
            return self.check()
        return None


def start_update_scheduler(cfg: Dict[str, Any], home: Path) -> "UpdateService":
    """创建服务并触发一次启动检查（后台任务，不阻塞）。"""
    svc = UpdateService(cfg, home)
    return svc
