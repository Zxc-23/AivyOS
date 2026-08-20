"""版本管理与回滚（文档 §2.3 / T8.6）：语义版本比较 + 保留 3 版 + 符号链接切换。

目录结构（§2.3）：
    versions/
        current → v1.2.3/   (符号链接，指向当前版本)
        v1.2.3/             (当前运行版本)
        v1.2.2/             (上一个版本)
        v1.2.1/             (上上版本)
        v1.2.0/             (更早版本，自动清理)
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import List, Optional

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.+-]+)?$")


class VersionError(RuntimeError):
    pass


class Version:
    """语义版本（§1.6.2 版本单调递增）。"""

    def __init__(self, s: str) -> None:
        m = SEMVER_RE.match(s.strip())
        if not m:
            raise VersionError(f"非法语义版本: {s!r}")
        self.raw = s.strip()
        self.major, self.minor, self.patch = (int(x) for x in m.groups())

    def __lt__(self, other: "Version") -> bool:
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Version) and (
            self.major, self.minor, self.patch
        ) == (other.major, other.minor, other.patch)

    @staticmethod
    def is_higher(new: str, current: str) -> bool:
        """§1.4 Step 7 防降级：new > current（拒绝降级）。"""
        try:
            return Version(new) > Version(current)
        except VersionError:
            return False

    @staticmethod
    def is_valid(s: str) -> bool:
        return bool(SEMVER_RE.match(s.strip()))


class VersionManager:
    """版本目录管理：安装新版本 / 切换 / 回滚 / 清理旧版（§2.3 / T8.6）。"""

    KEEP_VERSIONS = 3  # §2.3 保留最近 3 个版本

    def __init__(self, versions_dir: Path) -> None:
        self.root = Path(versions_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- 目录 ----

    def version_dir(self, version: str) -> Path:
        return self.root / f"v{version}"

    def list_versions(self) -> List[str]:
        """已安装版本（按版本降序）。"""
        out = []
        for p in self.root.iterdir():
            if p.is_dir() and p.name.startswith("v") and Version.is_valid(p.name[1:]):
                out.append(p.name[1:])
        return sorted(out, key=Version, reverse=True)

    def current_version(self) -> Optional[str]:
        """current 指向的版本（§2.3）：符号链接或指针文件。"""
        link = self.root / "current"
        if link.is_symlink():
            target = os.readlink(link)
            if target.startswith("v"):
                return target[1:]
        if link.is_file():
            text = link.read_text(encoding="utf-8").strip()
            if text.startswith("v"):
                return text[1:]
        return None

    # ---- 安装 / 切换 ----

    def install(self, version: str, package_dir: Path) -> Path:
        """安装新版本：复制更新包到 versions/v{version}/，切换 current 符号链接。"""
        if not Version.is_valid(version):
            raise VersionError(f"非法版本: {version}")
        dst = self.version_dir(version)
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(package_dir, dst)
        self._switch(version)
        self._prune()
        return dst

    def _switch(self, version: str) -> None:
        """切换 current → v{version}。

        Windows 兼容实现：
        - 优先使用指针文件（写入版本号文本），避免符号链接权限问题
        - 如果之前存在符号链接或目录，先正确清理
        """
        link = self.root / "current"

        # 清理旧的 current 指针
        if link.exists() or link.is_symlink():
            if link.is_symlink():
                # 符号链接：直接删除链接本身，不删除目标
                link.unlink()
            elif link.is_file():
                # 指针文件：直接删除
                link.unlink()
            elif link.is_dir():
                # 真实目录（异常情况）：删除目录
                shutil.rmtree(link, ignore_errors=True)

        # 使用指针文件（跨平台兼容，无需管理员权限）
        link.write_text(f"v{version}", encoding="utf-8")

    def _prune(self) -> None:
        """保留最近 KEEP_VERSIONS 个版本，自动清理更早版本（§2.3）。"""
        for v in self.list_versions()[self.KEEP_VERSIONS:]:
            shutil.rmtree(self.version_dir(v), ignore_errors=True)

    # ---- 回滚（§2.3 一键回滚 / T8.6）----

    def rollback(self) -> Optional[str]:
        """回滚到上一版本（current 指向次新版本）。返回新当前版本或 None。"""
        versions = self.list_versions()
        cur = self.current_version()
        if not versions or cur is None:
            return None
        # 选择低于当前版本的最高版本（忽略回滚白名单 — 白名单在 verifier 层检查）
        candidates = [v for v in versions if Version(v) < Version(cur)]
        if not candidates:
            return None
        target = candidates[0]
        self._switch(target)
        return target
