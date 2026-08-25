"""AIVY-REPORT-001 Task1: 报告生成纯函数工具（零第三方依赖）。

包含 6 个导出函数：
1. unified_diff_str(old, new, fromfile, tofile) -> str          # unified_diff 字符串 + 统计元数据
2. file_metadata(path, before_paths, cwd) -> Dict               # 字节数/行数/new|modified 判定
3. parse_unittest_output(stdout_stderr, exit_code) -> Dict      # "Ran N tests" / FAILURES 解析
4. parse_tsc_output(stdout_stderr, exit_code) -> Dict           # TS2322 等格式化解析
5. config_json_diff(before, after) -> List[Dict[str, Any]]      # 字段级点路径 diff
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
    """功能描述：递归遍历 dict/list 嵌套结构，对含敏感关键词（KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL）
    的字符串值执行掩码处理：保留首尾各 2 个字符，中间替换为 ***；长度不足 5 的字符串保持不变。

    参数类型：
        - obj: Any — 待处理的任意 Python 对象（通常为 dict 或 list）

    返回值类型：
        - Any — 结构与 obj 相同但敏感字符串已掩码的新对象
    """
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
    """功能描述：对比两段文本并输出标准 unified_diff 格式字符串（含 @@ hunk 标记、- 删除行、+ 新增行）；
    若两段文本完全相同则返回空字符串。

    参数类型：
        - old: str — 旧版本文本（换行符分隔）
        - new: str — 新版本文本（换行符分隔）
        - fromfile: str — diff 头部左侧文件名（默认为空串）
        - tofile: str — diff 头部右侧文件名（默认为空串）

    返回值类型：
        - str — unified_diff 文本；old==new 时为 ""
    """
    if old == new:
        return ""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return "".join(difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile, lineterm="\n"))


# ----------------------------------------------------------------------------
# 2. file_metadata（new vs modified 判定）
# ----------------------------------------------------------------------------


def file_metadata(path: str, before_paths: Optional[Set[str]] = None, cwd: Optional[str] = None) -> Dict[str, Any]:
    """功能描述：给定文件路径，采集其元数据（字节数、行数、新增/修改状态）。
    状态判定规则：若文件相对路径存在于 before_paths 集合中则为 "modified"，否则为 "new"；
    文件不存在或读取失败时返回 status="missing"/"error"，bytes/lines 均为 0。

    参数类型：
        - path: str — 目标文件的绝对或相对路径
        - before_paths: Optional[Set[str]] — 执行前快照中的相对路径集合（相对于 cwd）；None 等价于空集
        - cwd: Optional[str] — 工作目录；用于把 path 解析为相对路径后匹配 before_paths

    返回值类型：
        - Dict[str, Any] — 结构为 {path, status, bytes, lines}
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
    """功能描述：解析 `python -m unittest discover` 的合并 stdout/stderr 文本，
    精确匹配 "Ran N tests in Xs" 总行数、"FAILED (failures=N, errors=N)" 摘要，
    并从 "FAIL: test_name (Class)" 块首抽取失败用例摘要（最多保留 10 条）。
    无任何匹配时 total=0 兜底，不会抛异常。

    参数类型：
        - stdout_stderr: str — unittest discover 的 stdout+stderr 合并文本（可为空串）
        - exit_code: int — unittest 进程的 exit_code（透传进结果）

    返回值类型：
        - Dict[str, Any] — 结构为 {total, ok, failures, errors, exit_code, elapsed_s, status, fail_summary}
    """
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
    """功能描述：解析 `tsc --noEmit` 的 stdout/stderr 文本，按行匹配
    `file(line[,col]): error TSxxxx: message` 格式，汇总错误数量和每条明细。
    无匹配时返回 error_count=0、items=[]。

    参数类型：
        - stdout_stderr: str — tsc 的输出文本（可为空串）
        - exit_code: int — tsc 进程的 exit_code（透传进结果）

    返回值类型：
        - Dict[str, Any] — 结构为 {error_count, exit_code, items[{file,line,col,code,msg}]}
    """
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
    """功能描述：把嵌套 dict 扁平化成点号分隔路径的单层 dict（list 保持原值不展开索引）。
    该函数为 config_json_diff 的内部辅助函数，仅供本模块内调用。

    参数类型：
        - obj: Any — 待扁平化的对象（通常为 dict）
        - prefix: str — 当前已累积的点号路径前缀（递归用）

    返回值类型：
        - Dict[str, Any] — {点路径: 叶子值} 的扁平字典
    """
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
    """功能描述：对比两份 dict（通常为 config.json 前后快照），输出字段级点路径的变更列表。
    对值先递归脱敏掩码，再扁平化后逐键对比：仅 before 存在→remove、仅 after 存在→add、
    两边都存在但不等→update。结果按点路径排序输出。

    参数类型：
        - before: Dict[str, Any] — 对比前的配置 dict（None 视作 {}）
        - after: Dict[str, Any] — 对比后的配置 dict（None 视作 {}）

    返回值类型：
        - List[Dict[str, Any]] — 每项结构为 {path, before, after, change_type}
    """
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
