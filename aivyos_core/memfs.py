"""Letta MemFS 风格记忆（文档 §8.1：Agent 记忆文件系统，跨重启存活）。

类文件系统记忆抽象：Agent 通过 read/write/list/remove 自主管理记忆生命周期，
默认布局提供结构化记忆文件（用户偏好/事实/任务/项目），重启后自动恢复。
零依赖实现（仅标准库），路径安全（禁止逃逸根目录）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 默认记忆布局（Agent 可自主增删）
DEFAULT_LAYOUT = {
    "profile.md": "# 用户画像\n",
    "facts.md": "# 事实记忆\n",
    "user_prefs.md": "# 用户偏好\n",
    "tasks.md": "# 进行中的任务\n",
    "projects/": None,
    "archive/": None,
}

LAYOUT_ORDER = ["profile.md", "facts.md", "user_prefs.md", "tasks.md", "projects", "archive"]


class MemFSError(Exception):
    pass


class MemFS:
    """类文件系统记忆：所有路径相对 root 解析，防目录逃逸。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ensure_defaults()

    # ---- 路径安全 ----

    def _resolve(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not p.is_relative_to(self.root.resolve()):
            raise MemFSError(f"路径越界: {rel}")
        return p

    # ---- 初始化 ----

    def ensure_defaults(self) -> None:
        for name, content in DEFAULT_LAYOUT.items():
            p = self.root / name
            if name.endswith("/"):
                p.mkdir(parents=True, exist_ok=True)
            elif not p.exists():
                p.write_text(content, encoding="utf-8")

    # ---- 读写 ----

    def read(self, rel: str) -> str:
        p = self._resolve(rel)
        if not p.is_file():
            raise MemFSError(f"不是文件: {rel}")
        return p.read_text(encoding="utf-8")

    def write(self, rel: str, content: str, append: bool = False) -> str:
        """写入记忆文件（append=True 追加并带时间戳）。返回文件相对路径。"""
        p = self._resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        if append:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with p.open("a", encoding="utf-8") as f:
                f.write(f"- [{ts}] {content}\n")
        else:
            p.write_text(content, encoding="utf-8")
        return rel

    def remove(self, rel: str) -> bool:
        p = self._resolve(rel)
        if p.is_file():
            p.unlink()
            return True
        if p.is_dir():
            import shutil

            shutil.rmtree(p)
            return True
        return False

    def list(self, rel: str = "") -> List[str]:
        p = self._resolve(rel)
        if not p.is_dir():
            raise MemFSError(f"不是目录: {rel}")
        return sorted(
            str(x.relative_to(self.root)).replace("\\", "/") for x in p.rglob("*") if x.is_file()
        )

    # ---- 语义化便捷方法（Agent 调用入口）----

    def remember(self, text: str, category: str = "user_prefs.md") -> str:
        """记一条事实/偏好（默认追加到用户偏好，§4.2 记忆写入的 MemFS 通道）。"""
        return self.write(category, text, append=True)

    def get_relevant(self, keyword: str, top_files: int = 3) -> List[Dict[str, Any]]:
        """朴素检索：在记忆文件中找包含关键词的条目（Mem0 增强版检索见 §4.2）。"""
        hits = []
        for rel in self.list():
            if not rel.endswith(".md"):
                continue
            content = self.read(rel)
            for line in content.splitlines():
                if keyword and keyword not in line:
                    continue
                if line.strip() and line.startswith("- ["):
                    hits.append({"file": rel, "text": line.strip()[4:], "score": 1.0 if keyword else 0.5})
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:top_files * 20]

    # ---- 快照 / 恢复（§8.2 / §14.3 状态快照）----

    def snapshot(self) -> Dict[str, Any]:
        """导出完整记忆树（JSON 可序列化，用于热交换/重启恢复）。"""
        tree: Dict[str, Any] = {}
        for rel in self.list():
            node = tree
            parts = rel.split("/")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = self.read(rel)
        return {"root": str(self.root), "files": tree, "snapshot_at": time.time()}

    def restore(self, snapshot: Dict[str, Any]) -> None:
        """从快照重建（先清空再写回）。"""
        for rel in self.list():
            self.remove(rel)
        self.ensure_defaults()
        files = snapshot.get("files", {})
        for rel in self.list():
            node = files
            for part in rel.split("/"):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    break
            else:
                if isinstance(node, str):
                    self.write(rel, node)

    def summary(self) -> str:
        """简短状态摘要（供恢复摘要拼接）。"""
        files = self.list()
        sizes = {rel: len(self.read(rel)) for rel in files}
        return f"MemFS: {len(files)} 个文件，{sum(sizes.values())} 字符"
