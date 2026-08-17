"""SQLite 检查点（文档 §4.5.2 / §18.3：checkpoints.sqlite，断点续传）。

零依赖实现（stdlib sqlite3）：每个图节点执行成功后保存该线程的最新状态，
失败/断电后可从最后成功节点恢复（LangGraph SqliteSaver 语义子集）。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id  TEXT PRIMARY KEY,
    node       TEXT NOT NULL,
    state_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class SqliteCheckpointer:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def save(self, thread_id: str, node: str, state: Dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO checkpoints(thread_id, node, state_json, updated_at) VALUES(?,?,?,?)",
            (thread_id, node, json.dumps(state, ensure_ascii=False), time.time()),
        )
        self._conn.commit()

    def latest(self, thread_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        row = self._conn.execute(
            "SELECT node, state_json FROM checkpoints WHERE thread_id=?", (thread_id,)
        ).fetchone()
        if not row:
            return None
        return row[0], json.loads(row[1])

    def list_threads(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT thread_id, node, updated_at FROM checkpoints ORDER BY updated_at DESC"
        ).fetchall()
        return [
            {"thread_id": t, "node": n, "updated_at": u} for t, n, u in rows
        ]

    def clear(self, thread_id: Optional[str] = None) -> None:
        if thread_id:
            self._conn.execute("DELETE FROM checkpoints WHERE thread_id=?", (thread_id,))
        else:
            self._conn.execute("DELETE FROM checkpoints")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
