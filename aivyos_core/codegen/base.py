"""代码生成后端抽象（T5.1）：Cline Plan/Act 双模式语义。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class FilePlan:
    """Cline Plan 模式产物：文件树 + 每个文件职责（§10.1 阶段2）。"""

    files: List[Dict[str, str]]  # [{"path": ..., "purpose": ...}]

    def paths(self) -> List[str]:
        return [f["path"] for f in self.files]


class CodeGenBackend(ABC):
    name: str = "base"

    @abstractmethod
    def plan(self, spec: Any) -> FilePlan:
        """Plan 模式：根据规格规划文件树（§10.1 阶段2）。"""
        raise NotImplementedError

    @abstractmethod
    def generate(self, spec: Any, plan: FilePlan) -> Dict[str, str]:
        """Act 模式：逐文件生成代码（§10.1 阶段3）。"""
        raise NotImplementedError
