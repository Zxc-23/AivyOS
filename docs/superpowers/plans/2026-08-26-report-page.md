# 贾维斯作业报告页（AIVY-REPORT-001）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use general_purpose_task for Subagent-Driven execution（每 Task 一个独立 subagent，完成后 review 再进入下一 Task）。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每个协同任务（Claude→Codex 双 CLI）完成后，由贾维斯输出结构化 5 区块报告（①产出文件总览 ②行级 unified_diff 对比 ③验证结果摘要 ④Codex 审查摘要提取 ⑤系统状态变更），并提供底部 3 动作（复制 Markdown / 导出 HTML / VS Code 中对比 Diff），让用户能一眼核验贾维斯"到底改了什么、验证了什么、结论是什么"。

**Architecture:**
- **数据层（Task1）**：在 AgentResult dataclass 中新增 `report: JobReport` 嵌套结构；新增 3 个纯函数工具模块 `report_tools.py`（unified_diff + 文件元数据采集 + unittest/tsc 结果解析 + config 前后 diff）。
- **业务层（Task2）**：WorkbenchService.run_template() 执行前后：① 对 config.json + cwd 取双重前快照；② 跑完 Claude→Codex 后（原有 TemplateResult），额外触发一次 unittest_discover + tsc_noemit 采集验证结果；③ 解析 Codex 长文本为结构化 3 段（优点/问题/建议）；④ config 后快照与前快照字段级对比；⑤ 全部合并填入 AgentResult.report。
- **Bridge + TS DTO（Task3）**：AgentResultDto 新增 7 个可选字段嵌套对应 JobReport；新增 `workbenchCopyReportMarkdown(report)` / `workbenchExportReportHtml(report)` 两个命令；chat.ts 补 2 Promise wrapper。
- **UI 样式（Task4）**：styles.css 追加 `jr-*` 前缀 5 区块 + 3 动作按钮玻璃态暗色样式；响应式：<900px 5 区块单列堆叠。
- **UI 实现（Task5）**：App.tsx 新增 `showJobReport` state + 全屏 overlay 面板（路由改 overlay 更轻）；在 step card 底部"📁 贾维斯产出文件"右侧追加"📋 查看报告"按钮触发面板；tsc --noEmit exit 0。
- **E2E + 登记（Task6）**：后端全量 unittest discover；前端 tsc；说明文档.md §2.3 从"设计就绪"→"执行中"并加子节；§三进度登记 6 子项。

**Tech Stack:**
- 后端：Python 3.11 stdlib difflib（unified_diff 零第三方依赖）+ json（config 字段对比）+ subprocess.run(["python", "-m", "unittest", ...], capture_output=True)
- 前端：React 18 + TypeScript strict + `navigator.clipboard.writeText()`（复制 Markdown 纯浏览器 API）+ Blob→a.download（导出 HTML，无需 html2pdf 依赖）
- 前后端契约：AgentResult.report 嵌套 dict JSON 自由格式（DTO 用嵌套 interface 描述）

---

## 先验不变量（跨 Task 必须遵守）

1. **零新增第三方依赖**：diff 用 difflib、unittest/tsc 调用用 subprocess、Markdown 复制用 navigator.clipboard、HTML 导出用 Blob+URL.createObjectURL；禁止引入 difflib2 / html2canvas / jspdf 等。
2. **贾维斯=主语**：UI 文案一律"贾维斯作业报告"、"贾维斯修改"、"贾维斯验证"，禁止"Agent Report"、"Claude 修改"等非贾维斯主语。
3. **机密数据脱敏**：report 中若出现 api_key / password 等字段，走 ProviderEnv.to_safe_dict() 同款掩码逻辑（首末 2 位 + ***）。
4. **向后兼容**：Task1 改 AgentResult 默认值为空字段；Task2 新管线在 report 生成失败时返回 `report.error` 但整次协作不抛异常（保证 report 是可选增强，不阻塞主流程）；Task3 DTO 全字段可选。

---

### Task 1: 后端数据模型 + 报告工具模块（纯数据层，无 IPC 无业务）

**Files:**
- Modify: `aivyos_core/workbench/models.py:46-69`（AgentResult 追加 `report` 字段；新增 6 dataclass: JobReport / ReportFileItem / ReportDiff / ReportValidation / ReportReviewSummary / ReportConfigChange）
- Create: `aivyos_core/workbench/report_tools.py`（4 类纯函数：① diff(unified_diff) ② file_metadata(size/lines/new_or_modified) ③ unittest_output_parser / tsc_output_parser ④ config_json_diff）
- Create: `tests/test_report_tools.py`（10 条单测覆盖 4 类工具；Task1 必须 10/10 通过）

#### 先验：从现有代码导入

models.py 当前导入：
```python
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
```

report_tools.py 仅允许导入：
```python
from __future__ import annotations
import difflib
import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
```

#### Step 1: Write failing test（10 条 test_report_tools.py）

```python
"""AIVY-REPORT-001 Task1 报告工具单测（10 条）。"""
from __future__ import annotations
import json
import os
import tempfile
import unittest
from pathlib import Path

from aivyos_core.workbench.report_tools import (
    unified_diff_str,
    file_metadata,
    parse_unittest_output,
    parse_tsc_output,
    config_json_diff,
    mask_secrets_in_dict,
)


class TestUnifiedDiff(unittest.TestCase):
    def test_diff_modified_file_returns_hunks(self):
        old = "line1\nline2\nline3\nline4\n"
        new = "line1\nline2MOD\nline3\nline4NEW\n"
        diff = unified_diff_str(old, new, fromfile="a.py", tofile="a.py")
        self.assertIn("@@", diff)
        self.assertIn("-line2", diff)
        self.assertIn("+line2MOD", diff)

    def test_diff_identical_returns_empty_string(self):
        text = "a\nb\nc\n"
        self.assertEqual(unified_diff_str(text, text, "a", "a"), "")

    def test_diff_new_file_old_empty_has_all_added(self):
        diff = unified_diff_str("", "x=1\ny=2\n", fromfile="/dev/null", tofile="new.py")
        self.assertIn("+x=1", diff)


class TestFileMetadata(unittest.TestCase):
    def test_new_file_flags_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "hello.txt"
            p.write_text("line1\nline2\n", encoding="utf-8")
            meta = file_metadata(str(p), before_paths=set())
            self.assertEqual(meta["status"], "new")
            self.assertEqual(meta["bytes"], 12)
            self.assertEqual(meta["lines"], 2)

    def test_modified_file_flags_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.py"
            p.write_text("x=1\n", encoding="utf-8")
            before = {str(p.relative_to(tmp))}
            meta = file_metadata(str(p), before_paths=before, cwd=tmp)
            self.assertEqual(meta["status"], "modified")


class TestOutputParsers(unittest.TestCase):
    def test_parse_unittest_ran_545_pass_543(self):
        sample = ("........................................................................\n"
                  "........................................................................\n"
                  "Ran 545 tests in 65.765s\n"
                  "\n"
                  "FAILED (failures=1, errors=1)\n"
                  "\n"
                  "======================================================================\n"
                  "FAIL: test_ptt_start_stop_empty (tests.test_continuous_voice.TestPTT)\n"
                  "KeyError: 'error' at tests/test_continuous_voice.py:128\n")
        r = parse_unittest_output(sample, exit_code=1)
        self.assertEqual(r["total"], 545)
        self.assertEqual(r["ok"], 543)
        self.assertEqual(r["failures"], 1)
        self.assertEqual(r["errors"], 1)
        self.assertEqual(r["exit_code"], 1)
        self.assertIn("test_ptt_start_stop_empty", r["fail_summary"][0]["test"])

    def test_parse_unittest_all_ok_fallback_000(self):
        self.assertEqual(parse_unittest_output("", exit_code=0)["total"], 0)

    def test_parse_tsc_2_errors(self):
        sample = (
            "src/App.tsx(4711,23): error TS2322: Type 'string' is not assignable to type 'number'.\n"
            "src/chat.ts(1358,5): error TS2304: Cannot find name 'Foo'.\n"
        )
        r = parse_tsc_output(sample, exit_code=2)
        self.assertEqual(r["error_count"], 2)
        self.assertEqual(r["exit_code"], 2)
        self.assertEqual(len(r["items"]), 2)
        self.assertEqual(r["items"][0]["file"], "src/App.tsx")


class TestConfigDiff(unittest.TestCase):
    def test_config_field_level_diff_detects_manual_override(self):
        before = {"workbench": {"manual_override": {"claude_enabled": False}},
                  "agents": {"claude": {"manual": None}}}
        after = {"workbench": {"manual_override": {"claude_enabled": True}},
                 "agents": {"claude": {"manual": {"name": "Ollama"}}}}
        changes = config_json_diff(before, after)
        paths = {c["path"] for c in changes}
        self.assertIn("workbench.manual_override.claude_enabled", paths)
        self.assertIn("agents.claude.manual.name", paths)

    def test_mask_secrets_hides_middle(self):
        d = {"api_key": "sk-abcdefgh1234567890", "name": "ok"}
        masked = mask_secrets_in_dict(d)
        self.assertTrue(masked["api_key"].startswith("sk"))
        self.assertTrue(masked["api_key"].endswith("90"))
        self.assertIn("***", masked["api_key"])
        self.assertEqual(masked["name"], "ok")


if __name__ == "__main__":
    unittest.main()
```

#### Step 2: Run test 验证失败（预期：ImportError 找不到 report_tools 模块）

```powershell
cd f:\AivyOS\aivyos ; python -m unittest tests.test_report_tools -v 2>&1 | Select-Object -First 40
```

**Expected exit code:** 非 0；**Expected first error line:** `ModuleNotFoundError: No module named 'aivyos_core.workbench.report_tools'`

#### Step 3: 最小实现（models.py 追加 dataclass + report_tools.py 实现 6 函数）

**3a. models.py 追加（AgentResult 末尾 + 6 Job dataclass 写在 AgentResult 之前，按依赖顺序）：**

```python
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
```

然后修改 AgentResult dataclass，在 `files_created` 后追加一行：
```python
@dataclass
class AgentResult:
    agent: str = ""
    ok: bool = False
    output: str = ""
    exit_code: int = -1
    elapsed_s: float = 0.0
    output_files: List[str] = field(default_factory=list)
    files_created: List[str] = field(default_factory=list)
    report: Optional[JobReport] = None     # ← 新增这一行
    error: str = ""
    created_at: float = field(default_factory=time.time)
```

并修改 AgentResult.to_dict() 在末尾 files_created 之后、error 之前插入：
```python
    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "agent": self.agent, "ok": self.ok, "output": self.output,
            "exit_code": self.exit_code, "elapsed_s": round(self.elapsed_s, 2),
            "output_files": list(self.output_files),
            "files_created": list(self.files_created),
        }
        if self.report is not None:              # ← 新增：非空才序列化（向后兼容）
            d["report"] = self.report.to_dict()
        d["error"] = self.error
        d["created_at"] = self.created_at
        return d
```

**3b. report_tools.py 完整实现（6 函数，严格零第三方依赖）：**

```python
"""AIVY-REPORT-001 Task1: 报告生成纯函数工具（零第三方依赖）。

包含 6 个导出函数：
1. unified_diff_str(old, new, fromfile, tofile) -> str          # unified_diff 字符串 + 统计元数据
2. file_metadata(path, before_paths, cwd) -> Dict               # 字节数/行数/new|modified 判定
3. parse_unittest_output(stdout_stderr, exit_code) -> Dict      # "Ran N tests" / FAILURES 解析
4. parse_tsc_output(stdout_stderr, exit_code) -> Dict           # TS2322 等格式化解析
5. config_json_diff(before, after) -> List[ReportConfigChange.to_dict()]  # 字段级点路径 diff
6. mask_secrets_in_dict(obj) -> Any                             # 递归掩码 KEY/TOKEN/SECRET/PASSWORD
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# ----------------------------------------------------------------------------
# 6. mask_secrets_in_dict（先写，因为 config_diff 要用）
# ----------------------------------------------------------------------------

_SECRET_KEY_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)


def mask_secrets_in_dict(obj: Any) -> Any:
    """递归掩码含敏感名的字符串字段：首末各 2 位 + ***，其余结构保持不变。"""
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY_RE.search(k) and isinstance(v, str) and len(v) > 4:
                out[k] = v[:2] + "***" + v[-2:]
            else:
                out[k] = mask_secrets_in_dict(v)
        return out
    if isinstance(obj, list):
        return [mask_secrets_in_dict(x) for x in obj]
    return obj


# ----------------------------------------------------------------------------
# 1. unified_diff_str
# ----------------------------------------------------------------------------


def unified_diff_str(old: str, new: str, fromfile: str = "", tofile: str = "") -> str:
    """生成 unified_diff 文本（含 @@ 标记）；内容完全相同时返回空串。"""
    if old == new:
        return ""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return "".join(difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile, lineterm="\n"))


# ----------------------------------------------------------------------------
# 2. file_metadata（new vs modified 判定）
# ----------------------------------------------------------------------------


def file_metadata(path: str, before_paths: Optional[Set[str]] = None, cwd: Optional[str] = None) -> Dict[str, Any]:
    """给定一个绝对或相对路径，产出 {status,bytes,lines} 元数据。

    Args:
        path: 目标文件路径；若 cwd 给定且 path 非绝对，则按 Path(cwd) / path 定位。
        before_paths: 执行前快照中的相对路径集合（相对于 cwd）。path 若在集合内则 status=modified，否则 new。
        cwd: 工作目录。用于把 path 解析成相对路径后匹配 before_paths。
    """
    before_paths = before_paths or set()
    try:
        abs_path = Path(path) if Path(path).is_absolute() else (Path(cwd) / path if cwd else Path(path))
        if not abs_path.is_file():
            return {"path": path, "status": "missing", "bytes": 0, "lines": 0}
        raw = abs_path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        rel = str(abs_path.relative_to(Path(cwd).resolve())) if cwd and abs_path.is_absolute() else path
        status = "modified" if rel in before_paths or path in before_paths else "new"
        return {
            "path": path, "status": status,
            "bytes": len(raw),
            "lines": 0 if not text else text.count("\n") + (0 if text.endswith("\n") else 1),
        }
    except (OSError, ValueError):
        return {"path": path, "status": "error", "bytes": 0, "lines": 0}


# ----------------------------------------------------------------------------
# 3. parse_unittest_output（兼容 unittest discover 文本）
# ----------------------------------------------------------------------------

_RAN_RE = re.compile(r"^Ran (\d+) tests? in ([0-9.]+)s$", re.MULTILINE)
_SUMMARY_RE = re.compile(r"^(OK|FAILED)(?: \((.+)\))?$", re.MULTILINE)
_FAIL_HEAD_RE = re.compile(r"^(FAIL|ERROR):\s+(\S+)\s+\(([^)]+)\)")
_FAIL_FILE_RE = re.compile(r"File\s+\"([^\"]+)\",\s+line\s+(\d+)")


def parse_unittest_output(stdout_stderr: str, exit_code: int) -> Dict[str, Any]:
    """解析 unittest discover 输出。"""
    text = stdout_stderr or ""
    total = 0
    elapsed = 0.0
    status = ""
    extras = ""
    m1 = _RAN_RE.search(text)
    if m1:
        total = int(m1.group(1))
        try:
            elapsed = float(m1.group(2))
        except ValueError:
            elapsed = 0.0
    m2 = _SUMMARY_RE.search(text)
    if m2:
        status = m2.group(1)
        extras = m2.group(2) or ""
    failures = 0
    errors = 0
    if extras:
        for part in extras.split(","):
            kv = part.strip()
            if kv.startswith("failures="):
                try: failures = int(kv.split("=", 1)[1])
                except ValueError: pass
            elif kv.startswith("errors="):
                try: errors = int(kv.split("=", 1)[1])
                except ValueError: pass
    # 提取 FAIL / ERROR 块的首条摘要（最多 10 条，避免过大）
    fail_summary: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    for line in text.splitlines():
        m_head = _FAIL_HEAD_RE.match(line.strip())
        if m_head:
            if current and len(fail_summary) < 10:
                fail_summary.append(current)
            current = {
                "kind": m_head.group(1),
                "test": m_head.group(2),
                "class": m_head.group(3),
                "file": "", "line": "", "msg": "",
            }
            continue
        if current:
            m_file = _FAIL_FILE_RE.search(line)
            if m_file:
                current["file"] = m_file.group(1)
                current["line"] = m_file.group(2)
                continue
            if not current["msg"] and line.strip() and "------" not in line and "======" not in line:
                current["msg"] = line.strip()[:200]
    if current and len(fail_summary) < 10:
        fail_summary.append(current)
    ok_count = total - failures - errors
    if ok_count < 0:
        ok_count = 0
    return {
        "total": total, "ok": ok_count, "failures": failures, "errors": errors,
        "exit_code": exit_code, "elapsed_s": round(elapsed, 2),
        "status": status or ("ok" if exit_code == 0 else "fail"),
        "fail_summary": fail_summary,
    }


# ----------------------------------------------------------------------------
# 4. parse_tsc_output（TS 错误行：file(line,col): error TSxxxx: msg）
# ----------------------------------------------------------------------------

_TSC_ERR_RE = re.compile(
    r"^(?P<file>[^(]+)\((?P<line>\d+)(?:,(?P<col>\d+))?\):\s*error\s+TS(?P<code>\d+):\s*(?P<msg>.*)$"
)


def parse_tsc_output(stdout_stderr: str, exit_code: int) -> Dict[str, Any]:
    items: List[Dict[str, str]] = []
    for line in (stdout_stderr or "").splitlines():
        m = _TSC_ERR_RE.match(line.strip())
        if m:
            items.append({
                "file": m.group("file"), "line": m.group("line"),
                "col": m.group("col") or "", "code": "TS" + m.group("code"),
                "msg": m.group("msg"),
            })
    return {
        "error_count": len(items), "exit_code": exit_code, "items": items,
    }


# ----------------------------------------------------------------------------
# 5. config_json_diff（字段级点路径）
# ----------------------------------------------------------------------------


def _flatten(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """把嵌套 dict 扁平化成 {'a.b.c': value}，list 保持原值（不展开 index）。"""
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(_flatten(v, key))
            else:
                out[key] = v
    else:
        if prefix:
            out[prefix] = obj
    return out


def config_json_diff(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    """返回点路径级别的变更列表；敏感值自动掩码。"""
    b = _flatten(mask_secrets_in_dict(before or {}))
    a = _flatten(mask_secrets_in_dict(after or {}))
    changes: List[Dict[str, Any]] = []
    for path in sorted(set(b) | set(a)):
        in_b = path in b
        in_a = path in a
        if in_b and in_a:
            if b[path] != a[path]:
                changes.append({"path": path, "before": b[path], "after": a[path], "change_type": "update"})
        elif in_a:
            changes.append({"path": path, "before": None, "after": a[path], "change_type": "add"})
        else:
            changes.append({"path": path, "before": b[path], "after": None, "change_type": "remove"})
    return changes
```

#### Step 4: 运行 tests.test_report_tools 验证 10/10 通过

```powershell
cd f:\AivyOS\aivyos ; python -m unittest tests.test_report_tools -v
```

**Expected:** `Ran 10 tests in ... OK`（exit_code 0）

---

### Task 2: WorkbenchService.run_template() 内嵌报告生成管线

**Files:**
- Modify: `aivyos_core/workbench/service.py:23-...`（WorkbenchService 新增 `_generate_job_report()` + 在 `run_template()` 尾部调用并挂到主 AgentResult.report）
- Modify: `aivyos_core/workbench/dispatchers/claude_code.py:35-71`（`_take_snapshot()` 升级保留文件内容 hash 备份到 `Path(cwd) / .aivyos_tmp_before`，供 unified_diff 读 before 文本；`_detect_changes()` 兼容返回旧 Dict[str, float] 外再提供新 Dict[str, str] 内容哈希版）
- Modify: `tests/test_provider_store.py`（追加 `TestJobReportPipeline` 类 4 条集成单测：① report_generated_ok ② fail_masked ③ unittest_parser_real_invocation ④ config_diff_real_invocation）

> 本 Task 先写 4 条 failing test → 确认失败 → 实现 service.py 的 report 管线 → 确认 4/4 过。

Step 1-5 实现在 Subagent-Driven 派发 Task2 时由 subagent 完整写出；此处只锁定关键签名：

**关键新函数签名（先锁定，subagent 必须遵守）：**
```python
# service.py
def _generate_job_report(
    self,
    *,
    cwd: str,
    before_snapshot_paths: Set[str],
    before_content_cache: Dict[str, str],     # path -> 执行前文本（utf-8 replace 读）
    files_created: List[str],
    config_before: Dict[str, Any],
    config_after: Dict[str, Any],
    codex_review_raw_output: str,
    run_unittest: bool = True,                # 环境变量 AIVYOS_REPORT_SKIP_UNITTEST=1 时置 False
    run_tsc: bool = True,                     # AIVYOS_REPORT_SKIP_TSC=1 时置 False
) -> Optional["JobReport"]: ...
```

**关键：run_template 不抛异常原则**：`_generate_job_report` 内部所有 `subprocess.run` 必须 timeout=60s，且任何异常 try/except 包成 `JobReport(error=str(e))` 返回，**绝不允许向上抛导致 run_template 失败**。

---

### Task 3: Bridge 命令 + chat.ts DTO 扩展（把 report 带到前端 + 3 动作）

**Files:**
- Modify: `aivyos_core/server_entry.py`（在 L2239 附近追加 2 个 @server.method：`workbench.copy_report_markdown`、`workbench.export_report_html`；两者都接受 `report_dict` 参数返回 `{ok, copied_to_clipboard:bool, html_preview_url?:str, error?:str}`）
- Modify: `shell/src/chat.ts`（`AgentResultDto` 内嵌 `report?: JobReportDto` 对应 5 区块；新增 `workbenchCopyReportMarkdown(report)` / `workbenchExportReportHtml(report)` 2 Promise wrapper；DTO 所有字段带 `?` 可选向后兼容）
- Verify: `python -c "from aivyos_core.server_entry import build_server; s=build_server({}); print('ok')"`（import smoke）；`npx tsc --noEmit` exit 0

**DTO 结构锁定（subagent 必须严格一致）：**
```typescript
export interface ReportDiffDto { path: string; unified: string; hunks: number; added: number; removed: number; }
export interface ReportFileItemDto { path: string; status: "new"|"modified"|"unchanged"|"missing"|"error"; bytes: number; lines: number; diff?: ReportDiffDto; }
export interface ReportFailSummaryDto { kind?: string; test?: string; class?: string; file?: string; line?: string; msg?: string; }
export interface ReportTscItemDto { file: string; line: string; col: string; code: string; msg: string; }
export interface ReportValidationDto {
  unit_total: number; unit_ok: number; unit_failures: number; unit_errors: number;
  unit_exit_code: number; unit_elapsed_s: number; unit_fail_summary: ReportFailSummaryDto[];
  tsc_error_count: number; tsc_exit_code: number; tsc_elapsed_s: number; tsc_items: ReportTscItemDto[];
}
export interface ReportReviewSummaryDto { raw_excerpt: string; strengths: string[]; issues: string[]; suggestions: string[]; }
export interface ReportConfigChangeDto { path: string; before?: any; after?: any; change_type: "add"|"update"|"remove"; }
export interface JobReportDto {
  job_id: string; generated_at: number; generation_ms: number; error: string;
  files: ReportFileItemDto[];
  validation: ReportValidationDto;
  review_summary: ReportReviewSummaryDto;
  config_changes: ReportConfigChangeDto[];
}
export interface AgentResultDto {
  agent: string; ok: boolean; output: string; exit_code?: number; elapsed_s?: number;
  output_files?: string[]; files_created?: string[];
  report?: JobReportDto;          // ← 新增
  error?: string; created_at?: number;
}
```

---

### Task 4: styles.css 贾维斯作业报告页玻璃态暗色主题

**Files:**
- Modify: `shell/src/styles.css`（末尾追加 280 行左右 `jr-*` 前缀样式；5 区块 + 3 动作；响应式断点 <900px 5 区块堆叠）

**类名契约（App.tsx Task5 会严格使用，不可改动）：**
- `.jr-overlay`（全屏 backdrop，rgba(2,6,23,0.75)）
- `.jr-panel`（max-width: 1200px, width: 92vw, max-height: 92vh, overflow: auto, glass态）
- `.jr-header`（标题"📋 贾维斯作业报告" + 右上关闭 ✕ 按钮）
- `.jr-meta`（job_id + 生成耗时 + 生成时间）
- `.jr-sections`（display:grid; grid-template-columns: 1fr 1fr; gap: 12px; <900px grid-template-columns: 1fr）
- `.jr-card`（5 区块卡片，glass态 background: rgba(255,255,255,0.03), border: 1px solid var(--line)）
- `.jr-card-title`（13px semibold，前 4 字用 emoji 前缀：①📁 / ②📊 / ③🧪 / ④🔍 / ⑤⚙️）
- `.jr-file-list`（max-height: 280px, overflow:auto, 每行列 file + status pill + bytes + lines）
- `.jr-status-new`（pill green: bg rgba(34,197,94,0.15), border 1px solid rgba(34,197,94,0.35), color #4ade80）
- `.jr-status-modified`（pill yellow: bg rgba(234,179,8,0.15), border 1px solid rgba(234,179,8,0.35), color #facc15）
- `.jr-diff-block`（<pre> 10px, background #0b1020, padding 8px, border-radius 6px; +行 color #22c55e; -行 color #ef4444; @@ color #60a5fa）
- `.jr-valid-ok`（pill green "✅ unittest 543/545"）
- `.jr-valid-fail`（pill red "❌ 失败 2：1fail+1error"）
- `.jr-actions`（底部 sticky, 三按钮：复制 Markdown / 导出 HTML / VS Code 对比 Diff）
- `.jr-btn`（height 36px, padding 0 16px, border-radius 8px, font-size 12px, font-weight 600, cursor pointer）
- `.jr-btn-primary`（background: linear-gradient(135deg,#6c8cff,#4db8c7), color white, border 0）
- `.jr-btn-secondary`（background: rgba(255,255,255,0.04), color var(--ink), border 1px solid var(--line)）

---

### Task 5: App.tsx 贾维斯作业报告页 UI（overlay 面板 + 5 区块渲染 + 3 动作）

**Files:**
- Modify: `shell/src/App.tsx`（新增 hooks: `jrVisible`, `jrReport: JobReportDto|null`；新增 handler: `jrClose`, `jrOpenFromStep(step: WbStepDto)`；在 step card L5275 后面追加 button「📋 查看贾维斯作业报告」onClick=jrOpenFromStep；底部 3 动作按钮分别绑定 `workbenchCopyReportMarkdown` / `workbenchExportReportHtml` / `workbenchVscodeOpen` + 本地 fallback）
- Verify: `npx tsc --noEmit` exit 0（零错误门槛）

**3 动作行为锁定（不可改动）：**
1. **复制 Markdown**：先本地构建 Markdown 文本（5 区块格式化为 md 标题 + 列表 + ```diff``` 块）→ `navigator.clipboard.writeText(md)`；若失败再 fallback 到 bridge `workbench.copy_report_markdown`；成功弹 toast "✅ Markdown 已复制到剪贴板"。
2. **导出 HTML**：本地构建 `<html><head>暗色玻璃态 CSS inline</head><body>...</body></html>` → Blob(...,{type:'text/html'}) → `URL.createObjectURL` → `<a href=... download="jarvis-report-{job_id||timestamp}.html">` click → `URL.revokeObjectURL`；成功 toast "📄 HTML 报告已下载"。
3. **VS Code 对比 Diff**：若存在 `report.files[*].diff.unified`，把每个 diff 存到 `tempfile.mkdtemp` 下 `before/after`（通过 bridge workbench.vscode_open 调用 `code --diff before after`）；不存在 diff 时 toast "⚠️ 仅对修改过的文件可对比 Diff"。

---

### Task 6: E2E 冒烟 + 说明文档.md 进度登记

**Files:**
- Modify: `说明文档.md`（§1.4 第 3 项从"📋 设计就绪"→"✅ 已完成"；§1.5 第 4 行实际完成填 2026-08-26；§2.3 从一句话设计升级为与 §2.2 同粒度的三端架构写入策略描述；§三 进度记录追加 7 行：AIVY-REPORT-001 设计就绪→任务启动 + AIVY-REPORT-001-T1..T6 各子项）

**E2E 命令（必须按顺序，非 0 立即暂停）：**
1. 后端单测：`cd f:\AivyOS\aivyos ; python -m unittest discover -s tests -v`
   - 验收：cc-switch 相关 14 条 + report_tools 10 条 + pipeline 4 条 = ≥28 条新增 100% 通过；其余失败仅限 UNRESOLVED 两条（voice PTT + telemetry timing）
2. 前端 tsc：`cd f:\AivyOS\aivyos\shell ; npx tsc --noEmit`
   - 验收：exit_code 0；0 error
3. Python import smoke：`cd f:\AivyOS\aivyos ; python -c "from aivyos_core.server_entry import build_server; from aivyos_core.workbench.models import JobReport, AgentResult; from aivyos_core.workbench.report_tools import unified_diff_str; print('SMOKE_OK')"`
   - 验收：输出 `SMOKE_OK`

---

## Self-Review（writing-plans Skill 强制自检）

1. **Spec 覆盖率 5 区块 × 3 动作**：
   - ①产出文件总览：Task1 ReportFileItem + Task2 调用 file_metadata + Task5 `.jr-file-list` ✔
   - ②unified_diff：Task1 unified_diff_str + Task1 test + Task4 `.jr-diff-block` ✔
   - ③验证结果：Task1 parse_unittest/parse_tsc + Task2 subprocess 调用 + Task4 `.jr-valid-*` ✔
   - ④Codex 审查摘要：Task1 ReportReviewSummary + Task2 3 段抽取 + Task5 渲染 3 列 ✔
   - ⑤系统状态变更：Task1 config_json_diff + mask_secrets_in_dict + Task2 前后 config 快照 ✔
   - 动作1 复制 Markdown：Task5 本地 clipboard + fallback bridge，Task3 DTO ✔
   - 动作2 导出 HTML：Task5 Blob+URL ✔
   - 动作3 VS Code Diff：Task5 workbenchVscodeOpen + Task2 diff 内容 ✔
2. **占位符扫描**：Task1 给出了 10 条测试完整代码 + models.py/report_tools.py 完整代码；Task2-6 给出了精确文件路径、关键签名、DTO 结构、类名契约（无 TODO 无 TBD）。✔
3. **类型一致性**：AgentResultDto.report? (TS) ↔ AgentResult.report: Optional[JobReport] (Python) ↔ to_dict 序列化非空才写入（向后兼容）；点路径字段、掩码逻辑、状态枚举三者跨文件完全一致（"new"|"modified"、"add"|"update"|"remove"）✔

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-26-report-page.md`。**

**执行模式确认（回顾用户已选 "1" = Subagent-Driven）：**
- ✅ 采用 Subagent-Driven：每个 Task1-Task6 派发一个独立 general_purpose_task subagent，完成后 review 再进入下一 Task。
- **启动顺序**：T1 → T2 → T3 → T4 → T5 → T6（严格顺序，因为 T2 依赖 T1 的 JobReport dataclass / DTO，T5 依赖 T4 的 jr-* 样式类名，T3 桥接要与 T1 数据模型字段对齐）
