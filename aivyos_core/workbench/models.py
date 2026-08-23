"""Workbench 数据模型：ProviderEnv / AgentTask / AgentResult。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# env 中含这些关键字的值视为机密，to_safe_dict() 中一律剥离
_SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def _is_secret_key(key: str) -> bool:
    k = key.upper()
    return any(h in k for h in _SECRET_HINTS)


@dataclass
class ProviderEnv:
    """一个 agent 的运行环境（env 含机密，禁止整体落盘/外发）。"""

    app_type: str            # "claude" | "codex"
    name: str                # provider 名（如 "Kimi"）
    env: Dict[str, str] = field(default_factory=dict)
    source: str = "cc-switch"  # "cc-switch" | "aivyos-config"

    def to_safe_dict(self) -> Dict[str, Any]:
        """脱敏视图：仅保留非机密 env 键与机密键的名字。"""
        return {
            "app_type": self.app_type,
            "name": self.name,
            "source": self.source,
            "env": {k: ("***" if _is_secret_key(k) else v) for k, v in self.env.items()},
        }


@dataclass
class AgentTask:
    agent: str                       # "claude" | "codex"
    prompt: str = ""
    cwd: Optional[str] = None
    timeout_s: float = 300.0
    extra_args: List[str] = field(default_factory=list)


@dataclass
class AgentResult:
    agent: str = ""
    ok: bool = False
    output: str = ""
    exit_code: int = -1
    elapsed_s: float = 0.0
    output_files: List[str] = field(default_factory=list)
    error: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "ok": self.ok,
            "output": self.output,
            "exit_code": self.exit_code,
            "elapsed_s": round(self.elapsed_s, 2),
            "output_files": list(self.output_files),
            "error": self.error,
            "created_at": self.created_at,
        }
