"""Workbench 数据模型：ProviderEnv / AgentTask / AgentResult。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

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


# ============================================================================
# AIVY-REPORT-001: 贾维斯作业报告嵌套结构（所有字段默认值确保向后兼容）
# ============================================================================

@dataclass
class ReportDiff:
    """单个文件的 unified_diff 内容（为空表示文件未变或无法读）。"""
    path: str = ""
    unified: str = ""
    hunks: int = 0
    added: int = 0
    removed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReportFileItem:
    """产出文件总览中的单条记录。"""
    path: str = ""
    status: str = "new"                # "new" | "modified" | "unchanged"
    bytes: int = 0
    lines: int = 0
    diff: Optional[ReportDiff] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"path": self.path, "status": self.status, "bytes": self.bytes, "lines": self.lines}
        if self.diff is not None:
            d["diff"] = self.diff.to_dict()
        return d


@dataclass
class ReportValidation:
    """验证结果区块 ③。"""
    unit_total: int = 0
    unit_ok: int = 0
    unit_failures: int = 0
    unit_errors: int = 0
    unit_exit_code: int = 0
    unit_elapsed_s: float = 0.0
    unit_fail_summary: List[Dict[str, str]] = field(default_factory=list)  # [{test,file,line,msg}]
    tsc_error_count: int = 0
    tsc_exit_code: int = 0
    tsc_elapsed_s: float = 0.0
    tsc_items: List[Dict[str, str]] = field(default_factory=list)           # [{file,line,col,code,msg}]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit_total": self.unit_total, "unit_ok": self.unit_ok,
            "unit_failures": self.unit_failures, "unit_errors": self.unit_errors,
            "unit_exit_code": self.unit_exit_code,
            "unit_elapsed_s": round(self.unit_elapsed_s, 2),
            "unit_fail_summary": list(self.unit_fail_summary),
            "tsc_error_count": self.tsc_error_count,
            "tsc_exit_code": self.tsc_exit_code,
            "tsc_elapsed_s": round(self.tsc_elapsed_s, 2),
            "tsc_items": list(self.tsc_items),
        }


@dataclass
class ReportReviewSummary:
    """Codex 审查摘要区块 ④（从长文本中抽取 3 段）。"""
    raw_excerpt: str = ""                # 截取前 800 字原文防丢失
    strengths: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReportConfigChange:
    """系统状态变更区块 ⑤：单个字段级变更记录。"""
    path: str = ""                       # 点号分隔，如 workbench.manual_override.claude_enabled
    before: Optional[Any] = None
    after: Optional[Any] = None
    change_type: str = "update"          # "add" | "update" | "remove"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JobReport:
    """贾维斯作业报告 5 区块容器；所有字段可选空，保证旧 AgentResult.to_dict 不崩。"""
    job_id: str = ""
    generated_at: float = field(default_factory=time.time)
    generation_ms: float = 0.0
    error: str = ""                      # 报告生成失败但主任务成功时填，不阻塞
    files: List[ReportFileItem] = field(default_factory=list)
    validation: ReportValidation = field(default_factory=ReportValidation)
    review_summary: ReportReviewSummary = field(default_factory=ReportReviewSummary)
    config_changes: List[ReportConfigChange] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id, "generated_at": self.generated_at,
            "generation_ms": round(self.generation_ms, 1), "error": self.error,
            "files": [f.to_dict() for f in self.files],
            "validation": self.validation.to_dict(),
            "review_summary": self.review_summary.to_dict(),
            "config_changes": [c.to_dict() for c in self.config_changes],
        }


@dataclass
class AgentResult:
    agent: str = ""
    ok: bool = False
    output: str = ""
    exit_code: int = -1
    elapsed_s: float = 0.0
    output_files: List[str] = field(default_factory=list)
    files_created: List[str] = field(default_factory=list)
    report: Optional[JobReport] = None     # AIVY-REPORT-001: 贾维斯作业报告
    error: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "agent": self.agent, "ok": self.ok, "output": self.output,
            "exit_code": self.exit_code, "elapsed_s": round(self.elapsed_s, 2),
            "output_files": list(self.output_files),
            "files_created": list(self.files_created),
        }
        if self.report is not None:
            d["report"] = self.report.to_dict()
        d["error"] = self.error
        d["created_at"] = self.created_at
        return d
