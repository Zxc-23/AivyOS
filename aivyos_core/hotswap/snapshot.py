"""状态快照管理器（文档 桌面端规格 §3.2 / Week 11）：热交换前原子快照，失败从快照恢复。

快照对象（§3.2）：session 会话上下文 / tools 工具状态 / scheduler 调度任务 / browser 浏览器。
原子写入：tmp 文件 → os.replace（rename 原子性，§3.2 原子写入）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)


class StateSnapshot:
    def __init__(self, snapshots_dir: Path, version: str = "0.0.0") -> None:
        self.dir = Path(snapshots_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.version = version
        self._providers: Dict[str, Callable[[], Any]] = {}  # key → snapshot 提供者

    # ---- 提供者注册（各子系统快照函数）----

    def register(self, key: str, provider: Callable[[], Any]) -> None:
        self._providers[key] = provider

    # ---- 快照（§3.2 原子写入）----

    def snapshot(self, name: str = "latest") -> Dict[str, Any]:
        """创建完整状态快照并原子写入 latest.json。"""
        data: Dict[str, Any] = {}
        for key, provider in self._providers.items():
            try:
                data[key] = provider()
            except Exception as e:
                log.warning("[快照] %s 提供者失败: %s", key, e)
                data[key] = None
        snap = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "ts_epoch": int(time.time()),
            "version": self.version,
            "state": data,
        }
        path = self.dir / f"{name}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # 原子重命名（§3.2）
        return snap

    def restore(self, name: str = "latest") -> Optional[Dict[str, Any]]:
        """从快照恢复（§3.2）：返回快照内容或 None。"""
        path = self.dir / f"{name}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("[快照] 恢复失败: %s", e)
            return None

    def list_snapshots(self) -> list:
        return [p.stem for p in self.dir.glob("*.json") if not p.name.endswith(".tmp")]
