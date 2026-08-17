"""启动时上下文重建（文档 §8.2 restore_on_boot：三重恢复）。

重启后"醒来"时恢复：
  1. 长期记忆（Mem0/simple 后端 get_all）
  2. Agent 记忆文件系统（MemFS 快照）
  3. 工作流检查点（SQLite 最新）
并生成恢复摘要（§8.1 启动时上下文重建）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from aivyos_core.workflow.checkpointer import SqliteCheckpointer

log = logging.getLogger(__name__)


@dataclass
class RecoverySummary:
    long_term_memories: List[Dict[str, Any]] = field(default_factory=list)
    memfs_state: Dict[str, Any] = field(default_factory=dict)
    workflow_checkpoint: Optional[Dict[str, Any]] = None
    summary_text: str = ""
    recovered_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "long_term_memories": self.long_term_memories[:20],
            "memfs_state": self.memfs_state,
            "workflow_checkpoint": self.workflow_checkpoint,
            "summary_text": self.summary_text,
            "recovered_at": self.recovered_at,
        }


class BootRecovery:
    """§8.2 restore_on_boot：聚合三类持久化并生成恢复摘要。"""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.config = engine.config

    async def restore_on_boot(self) -> RecoverySummary:
        # 1) 长期记忆（§4.2）
        try:
            memories = await self.engine.memory.get_all()
            mem_dicts = [m.to_dict() for m in memories]
        except Exception as e:  # 记忆后端异常不阻断启动
            log.warning("记忆加载失败: %s", e)
            mem_dicts = []

        # 2) MemFS 快照（§8.1）
        try:
            memfs_state = self.engine.memfs.snapshot()
        except Exception as e:
            log.warning("MemFS 加载失败: %s", e)
            memfs_state = {}

        # 3) 工作流检查点（§4.5.2）
        checkpoint = None
        try:
            ckpt_path = self.engine.home / self.config["workflow"]["checkpoint_db"]
            ckpt = SqliteCheckpointer(ckpt_path)
            threads = ckpt.list_threads()
            if threads:
                node, state = ckpt.latest(threads[0]["thread_id"])
                checkpoint = {"thread_id": threads[0]["thread_id"], "node": node, "state": state}
        except Exception as e:
            log.warning("检查点加载失败: %s", e)

        summary_text = self._build_summary(mem_dicts, memfs_state, checkpoint)
        return RecoverySummary(
            long_term_memories=mem_dicts,
            memfs_state=memfs_state,
            workflow_checkpoint=checkpoint,
            summary_text=summary_text,
        )

    @staticmethod
    def _build_summary(memories: List[Dict], memfs_state: Dict, checkpoint: Optional[Dict]) -> str:
        """恢复摘要（朴素模板；Week 3 起可接 LLM 摘要生成）。"""
        lines = [
            f"[恢复] 长期记忆 {len(memories)} 条",
            f"[恢复] MemFS 文件 {sum(1 for _ in (memfs_state.get('files') or {})) if isinstance(memfs_state.get('files'), dict) else 0} 个",
        ]
        if memories:
            top = "；".join(m["text"][:50] for m in memories[:3])
            lines.append(f"[恢复] 近期记忆要点: {top}")
        if checkpoint:
            lines.append(f"[恢复] 工作流中断于节点 {checkpoint['node']}（线程 {checkpoint['thread_id']}），可续传")
        return "\n".join(lines)
