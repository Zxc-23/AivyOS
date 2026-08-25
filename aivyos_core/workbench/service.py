"""WorkbenchService：双模型协同统一入口。

链路：cc-switch 读取（优先）→ 手动配置降级 → dispatcher 子进程 → 内存态结果。
机密只进子进程 env；last_claude_result 仅内存持有（供 /review），不落盘。
AIVY-REPORT-001 Task2：run_template 尾部嵌入贾维斯作业报告生成管线。
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from aivyos_core.workbench.cc_switch.reader import CCSwitchReader
from aivyos_core.workbench.dispatchers.claude_code import ClaudeCodeDispatcher, get_before_content_cache
from aivyos_core.workbench.dispatchers.codex import CodexDispatcher
from aivyos_core.workbench.dispatchers.vscode import VSCodeDispatcher
from aivyos_core.workbench.models import (
    AgentResult, AgentTask, ProviderEnv,
    JobReport, ReportFileItem, ReportDiff, ReportValidation,
    ReportReviewSummary, ReportConfigChange,
)
from aivyos_core.workbench.report_tools import (
    unified_diff_str, file_metadata, parse_unittest_output,
    parse_tsc_output, config_json_diff, mask_secrets_in_dict,
)

_REVIEW_MAX = 8000  # 发给 codex 审查的 Claude 输出截断长度


class WorkbenchService:
    def __init__(self, cfg: Dict[str, Any], home: Optional[str] = None) -> None:
        wb = cfg.get("workbench", {})
        self.cfg = wb
        self.timeout_s = float(wb.get("timeout_s", 300))
        ccs = wb.get("cc_switch", {})
        self.cc_switch_enabled = bool(ccs.get("enabled", True))
        self.reader = CCSwitchReader(Path(ccs["db_path"]).expanduser() if ccs.get("db_path") else None)
        agents = wb.get("agents", {})
        claude_cfg = agents.get("claude_code", {})
        codex_cfg = agents.get("codex", {})
        self.agent_enabled = {
            "claude": bool(claude_cfg.get("enabled", True)),
            "codex": bool(codex_cfg.get("enabled", True)),
        }
        self.manual = {
            "claude": claude_cfg.get("manual", {}),
            "codex": codex_cfg.get("manual", {}),
        }
        self.claude = ClaudeCodeDispatcher(
            cli_path=claude_cfg.get("cli_path", "claude"),
            skip_permissions=bool(claude_cfg.get("skip_permissions", True)),
        )
        self.codex = CodexDispatcher(cli_path=codex_cfg.get("cli_path", "codex"))
        self.vscode = VSCodeDispatcher()
        collab = wb.get("collaboration", {})
        self.auto_open_vscode = bool(collab.get("auto_open_vscode", True))
        self.review_via_files = bool(collab.get("review_via_files", True))
        self.last_claude_result: Optional[AgentResult] = None  # 仅内存，供 review 使用
        self.last_notice: str = ""
        # ProviderStore：统一 cc-switch + AivyOS 手动配置（Task 2 新增）
        # • 只读 cc-switch.db；写入 AivyOS 自己 config.json（agents.*.manual / workbench.manual_override）
        # • resolve_credentials_for_dispatch() 为全局真源，_resolve_env 复用其结果
        self.home: Path = Path(home) if home else Path(
            os.environ.get("AIVYOS_HOME", str(Path.home() / ".aivyos"))
        )
        self.home.mkdir(parents=True, exist_ok=True)
        try:
            rows = list(self.reader.list_all() or [])
        except Exception:
            rows = None
        from aivyos_core.workbench.provider_store import ProviderStore
        self.provider_store: ProviderStore = ProviderStore(
            home=str(self.home),
            cc_provider_rows=rows,
            cc_reader=self.reader,
        )
        self.provider_store.reload()

    # ------------------------------------------------------------------
    # 凭据解析：ProviderStore.resolve_credentials 为唯一真源
    # ------------------------------------------------------------------
    def _resolve_env(self, app_type: str) -> Tuple[Optional[ProviderEnv], str]:
        """按 ProviderStore 统一优先级（aivyos-manual override → cc-switch）返回 ProviderEnv。

        保持与旧 _resolve_env 相同的返回契约：Tuple[ProviderEnv|None, notice_str]，
        保证 run_claude / run_codex 等旧调用链无需改动。
        """
        try:
            creds = self.provider_store.resolve_credentials(app_type)
        except Exception as e:
            # ProviderStore 明确抛出错误（没有 cc-current 且未启用 manual 覆盖）
            return None, str(e)
        penv = ProviderEnv(
            app_type=app_type,
            name=creds.display_name or (
                f"AivyOS 手动（{app_type}）" if creds.source == "aivyos-manual"
                else f"cc-switch {app_type}"
            ),
            env=creds.env,
            source=("aivyos-config" if creds.source == "aivyos-manual" else "cc-switch"),
        )
        notice = ""
        if creds.source == "aivyos-manual":
            notice = f"[{app_type}] 使用 AivyOS 手动覆盖配置（{creds.display_name}），优先级高于 cc-switch"
        else:
            notice = f"[{app_type}] 使用 cc-switch 当前激活项（{creds.display_name}）"
        return penv, notice

    # ------------------------------------------------------------------
    # 运行入口
    # ------------------------------------------------------------------
    async def run_claude(self, prompt: str, cwd: Optional[str] = None,
                         timeout_s: Optional[float] = None) -> AgentResult:
        if not self.agent_enabled["claude"]:
            return AgentResult(agent="claude", error="claude_code agent 已禁用（workbench.agents.claude_code.enabled=false）")
        penv, notice = self._resolve_env("claude")
        self.last_notice = notice
        if penv is None:
            return AgentResult(agent="claude", error=notice)
        task = AgentTask(agent="claude", prompt=prompt, cwd=cwd,
                         timeout_s=timeout_s or self.timeout_s)
        result = await self.claude.run(task, penv)
        if result.ok:
            self.last_claude_result = result
            if self.auto_open_vscode and result.output_files:
                await self.open_vscode(result.output_files[0])
        return result

    async def run_codex(self, prompt: str, cwd: Optional[str] = None,
                        timeout_s: Optional[float] = None) -> AgentResult:
        if not self.agent_enabled["codex"]:
            return AgentResult(agent="codex", error="codex agent 已禁用（workbench.agents.codex.enabled=false）")
        penv, notice = self._resolve_env("codex")
        self.last_notice = notice
        if penv is None:
            return AgentResult(agent="codex", error=notice)
        task = AgentTask(agent="codex", prompt=prompt, cwd=cwd,
                         timeout_s=timeout_s or self.timeout_s)
        return await self.codex.run(task, penv)

    async def review(self, cwd: Optional[str] = None) -> AgentResult:
        """用 Codex 审查最近一次 Claude 的输出（内存态）。
        
        当 review_via_files=True 且 Claude 产出了实际文件时，将文件内容一并传给 Codex 审查，
        使审查基于真实代码而非仅文字描述。
        """
        if self.last_claude_result is None or not self.last_claude_result.output.strip():
            return AgentResult(agent="codex", error="没有可审查的 Claude 输出，请先运行 /claude")
        
        from aivyos_core.workbench.dispatchers.claude_code import _build_review_prompt_with_files
        
        if self.review_via_files and self.last_claude_result.files_created:
            prompt = _build_review_prompt_with_files(
                self.last_claude_result.output,
                self.last_claude_result.files_created,
            )
        else:
            snippet = self.last_claude_result.output[:_REVIEW_MAX]
            prompt = f"请审查以下 Claude Code 的输出，指出问题与改进建议：\n\n{snippet}"
        
        return await self.run_codex(prompt, cwd=cwd)

    async def compare(self, prompt: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """并行调用 Claude 与 Codex，输出各自结果供对比。"""
        claude_res, codex_res = await asyncio.gather(
            self.run_claude(prompt, cwd=cwd), self.run_codex(prompt, cwd=cwd)
        )
        return {"claude": claude_res.to_dict(), "codex": codex_res.to_dict()}

    async def open_vscode(self, path: str) -> AgentResult:
        return await self.vscode.open(path)

    async def run_template(self, template: str, prompt: str,
                           cwd: Optional[str] = None) -> Dict[str, Any]:
        """运行预置协作模板（§4.2.2）：implement_then_review / parallel_design / doc_after_api。

        AIVY-REPORT-001 Task2：在主流程结束后、return 之前嵌入贾维斯作业报告生成管线；
        任何 report 异常内吞（_generate_job_report 自处理），绝不影响 run_template 主流程成功返回。
        """
        from aivyos_core.workbench.templates import run_template

        # ① config_before 快照（深拷贝，读不到时 fallback 空 dict）
        config_path = Path(str(self.home)) / "config.json"
        config_before: Dict[str, Any] = {}
        try:
            if config_path.is_file():
                with open(config_path, encoding="utf-8") as f:
                    config_before = copy.deepcopy(json.load(f))
        except Exception:
            config_before = {}

        result = await run_template(template, prompt, self.run_claude, self.run_codex, cwd=cwd)

        try:
            # ② 从 ClaudeCodeDispatcher 返回的 files_created 中收集 before_paths
            before_snapshot_paths: Set[str] = set(get_before_content_cache().keys())
            # ③ get_before_content_cache() 读 before 文本
            before_content_cache: Dict[str, str] = get_before_content_cache()
            # ④ config_after 快照
            config_after: Dict[str, Any] = {}
            try:
                if config_path.is_file():
                    with open(config_path, encoding="utf-8") as f:
                        config_after = json.load(f)
            except Exception:
                config_after = {}

            # 环境变量开关（跳过耗时 subprocess）
            skip_unit = os.environ.get("AIVYOS_REPORT_SKIP_UNITTEST", "") == "1"
            skip_tsc = os.environ.get("AIVYOS_REPORT_SKIP_TSC", "") == "1"

            # ⑤ 给每个 AgentResult 挂 report（只给有 files_created 或输出的挂）
            def _try_attach_report(res: AgentResult, codex_raw: str = "") -> None:
                """辅助：尝试给单个 AgentResult 挂 report，任何异常静默。"""
                try:
                    fc = getattr(res, "files_created", None) or []
                    rep = self._generate_job_report(
                        cwd=str(cwd or os.getcwd()),
                        before_snapshot_paths=before_snapshot_paths,
                        before_content_cache=before_content_cache,
                        files_created=list(fc),
                        config_before=config_before,
                        config_after=config_after,
                        codex_review_raw_output=codex_raw,
                        run_unittest=not skip_unit,
                        run_tsc=not skip_tsc,
                    )
                    if rep is not None:
                        res.report = rep
                except Exception:
                    # run_template 绝不因为 report 失败抛异常
                    pass

            # result 是 dict：结构通常为 {"claude": AgentResult, "codex": AgentResult}（to_dict 后为嵌套 dict）
            # 这里要处理两种可能：aivyos_core.workbench.templates 返回的是 TemplateResult dataclass
            # 或者直接 dict 类型。两种都尝试解析。
            codex_output = ""
            try:
                if hasattr(result, "codex"):
                    codex_obj = getattr(result, "codex")
                    if hasattr(codex_obj, "output"):
                        codex_output = str(getattr(codex_obj, "output") or "")
            except Exception:
                codex_output = ""

            # 遍历 result 中可能的 AgentResult 字段（dict 或 dataclass）
            _fields_to_check: List[Any] = []
            if isinstance(result, dict):
                for v in result.values():
                    _fields_to_check.append(v)
            else:
                for attr in ("claude", "codex"):
                    if hasattr(result, attr):
                        _fields_to_check.append(getattr(result, attr))
            for obj in _fields_to_check:
                if isinstance(obj, AgentResult):
                    _try_attach_report(obj, codex_raw=codex_output)
        except Exception:
            # ⑦ 任何 report 生成异常：run_template 永远不因为 report 失败抛异常
            pass

        return result

    async def review_diff(self, cwd: str) -> AgentResult:
        """捕获 cwd 的 git diff 并交 Codex 审查（§4.2.3 人工确认闭环）。"""
        from aivyos_core.workbench.diff import build_review_prompt, capture_diff

        diff = await capture_diff(cwd)
        if not diff.ok:
            return AgentResult(agent="codex", error=diff.error)
        return await self.run_codex(build_review_prompt(diff.output), cwd=cwd)

    def status(self) -> Dict[str, Any]:
        return {
            "cc_switch": {"enabled": self.cc_switch_enabled, "db_path": str(self.reader.db_path)},
            "agents": {
                k: {
                    "enabled": v,
                    **({"skip_permissions": self.claude.skip_permissions} if k == "claude" else {}),
                }
                for k, v in self.agent_enabled.items()
            },
            "auto_open_vscode": self.auto_open_vscode,
            "review_via_files": self.review_via_files,
            "vscode_available": self.vscode.available(),
            "last_notice": self.last_notice,
        }

    # ─────────────────────────────────────────────────────────────
    # Provider 管理（cc-switch + AivyOS 手动统一入口）
    # ─────────────────────────────────────────────────────────────

    def list_providers(self, app_type: str) -> Dict[str, Any]:
        """Bridge API：返回指定 app_type 的合并 Provider 列表 + override 开关状态 + 预设。"""
        from aivyos_core.workbench.provider_store import ProviderItem
        items = self.provider_store.list_providers(app_type)
        override_enabled = any(i.is_effective and i.source == "aivyos-manual" for i in items)
        presets = [p for p in items if p.source == "preset"]
        real = [p for p in items if p.source != "preset"]
        return {
            "providers": [
                {
                    "id": p.id, "app_type": p.app_type, "name": p.name,
                    "base_url": p.base_url,
                    "base_url_display": p.base_url_truncated,
                    "model": p.model,
                    "source": p.source,
                    "api_key_masked": p.api_key_masked,
                    "is_current_cc": p.is_current_cc,
                    "is_effective": p.is_effective,
                    "preset_id": p.preset_id,
                }
                for p in real
            ],
            "presets": [
                {
                    "id": p.id, "preset_id": p.preset_id, "name": p.name,
                    "base_url": p.base_url, "model": p.model, "app_type": p.app_type,
                }
                for p in presets
            ],
            "manual_override_enabled": override_enabled,
        }

    def save_manual(self, dto: Dict[str, Any]) -> Dict[str, Any]:
        """Bridge API：保存 AivyOS 手动覆盖；校验非法 URL/model 时返回 ok=False+错误信息。"""
        try:
            res = self.provider_store.save_manual(
                app_type=str(dto.get("app_type")),
                name=str(dto.get("name") or ""),
                base_url=str(dto.get("base_url") or ""),
                model=str(dto.get("model") or ""),
                api_key=str(dto.get("api_key") or ""),
                set_override_enabled=(
                    bool(dto["set_override"]) if "set_override" in dto else None
                ),
            )
        except ValueError as e:
            return {"ok": False, "error_message": str(e), "source": "", "active_name": ""}
        return {
            "ok": res.ok, "source": res.source,
            "active_name": res.active_name,
            "error_message": res.error_message,
        }

    def set_override(self, app_type: str, enabled: bool) -> Dict[str, Any]:
        """Bridge API：仅切换 override 开关。"""
        try:
            res = self.provider_store.set_override_toggle(app_type, enabled)
        except ValueError as e:
            return {"ok": False, "error_message": str(e), "source": "", "active_name": ""}
        return {
            "ok": True, "source": res.source,
            "active_name": res.active_name, "error_message": res.error_message,
        }

    def reload_from_ccswitch(self) -> Dict[str, Any]:
        """Bridge API：重新扫 cc-switch；丢弃内存中的未保存修改。"""
        self.provider_store.reload()
        return {
            "ok": True,
            "claude": self.list_providers("claude"),
            "codex":  self.list_providers("codex"),
        }

    def save_preset(self, dto: Dict[str, Any]) -> Dict[str, Any]:
        ok = self.provider_store.save_preset(
            app_type=str(dto.get("app_type")),
            preset_name=str(dto.get("preset_name") or ""),
            base_url=str(dto.get("base_url") or ""),
            model=str(dto.get("model") or ""),
            api_key=str(dto.get("api_key") or ""),
        )
        return {"ok": ok, "presets": self.list_providers(str(dto.get("app_type","claude"))).get("presets", [])}

    def health_check_provider(self, dto: Dict[str, Any]) -> Dict[str, Any]:
        """Bridge API：对当前生效或给定的 provider 发送 1 字探活消息并返回耗时。"""
        import time as _t
        from aivyos_core.workbench.provider_store import Credentials
        app_type = str(dto.get("app_type") or "claude")
        try:
            if dto.get("base_url") and dto.get("model"):
                creds = Credentials(
                    app_type=app_type,  # type: ignore[arg-type]
                    source="manual-probe",
                    base_url=str(dto["base_url"]),
                    model=str(dto["model"]),
                    api_key=str(dto.get("api_key") or "ollama"),
                )
            else:
                creds = self.provider_store.resolve_credentials(app_type)
        except Exception as e:
            return {"ok": False, "latency_ms": None, "error": str(e), "display_name": ""}
        t0 = _t.perf_counter()
        try:
            ok, msg = self._probe_provider(creds)
            elapsed = int((_t.perf_counter() - t0) * 1000)
            if not ok:
                return {"ok": False, "latency_ms": elapsed,
                        "error": msg or "探活失败", "display_name": creds.display_name}
            return {"ok": True, "latency_ms": elapsed,
                    "error": None, "display_name": creds.display_name}
        except Exception as e:
            elapsed = int((_t.perf_counter() - t0) * 1000)
            return {"ok": False, "latency_ms": elapsed,
                    "error": f"{type(e).__name__}: {e}", "display_name": creds.display_name}

    # ── 内部：探活（最小 HTTP 请求，不依赖 aiohttp）────────────
    def _probe_provider(self, creds) -> Tuple[bool, str]:
        """对 /v1/models 或 /v1/chat/completions（1 token）发探活。"""
        import json as _json
        import urllib.request
        import urllib.error
        base = creds.base_url.rstrip("/")
        if creds.app_type == "codex":
            url = f"{base}/models"
            req = urllib.request.Request(url, method="GET")
            if creds.api_key:
                req.add_header("Authorization", f"Bearer {creds.api_key}")
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    data = _json.loads(r.read().decode("utf-8") or "{}")
                if isinstance(data.get("data"), list):
                    return True, "ok"
                return False, f"unexpected body: {str(data)[:200]}"
            except urllib.error.HTTPError as e:
                if e.code in (404, 405):
                    return self._probe_provider_via_completion(creds)
                return False, f"HTTP {e.code}"
            except Exception as e:
                return False, str(e)
        # claude：/v1/messages 请求 1 token
        return self._probe_provider_via_completion(creds)

    def _probe_provider_via_completion(self, creds) -> Tuple[bool, str]:
        import json as _json
        import urllib.request
        import urllib.error
        base = creds.base_url.rstrip("/")
        if creds.app_type == "claude":
            url = f"{base}/v1/messages"
            payload = _json.dumps({
                "model": creds.model, "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            }).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }
            if creds.api_key:
                headers["x-api-key"] = creds.api_key
        else:  # codex (OpenAI compat)
            url = f"{base}/v1/chat/completions"
            payload = _json.dumps({
                "model": creds.model, "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            }).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if creds.api_key:
                headers["Authorization"] = f"Bearer {creds.api_key}"
        req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8):
                return True, "ok"
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}"
        except Exception as e:
            return False, str(e)

    # ── Dispatcher 消费：resolve_credentials_for_dispatch ──
    def resolve_credentials_for_dispatch(self, app_type: str):
        """双 CLI 执行前的统一凭据真源（返回 Credentials dataclass）。"""
        return self.provider_store.resolve_credentials(app_type)

    # =========================================================================
    # AIVY-REPORT-001 Task2: 贾维斯作业报告生成管线
    # =========================================================================

    def _extract_codex_summary(self, raw_output: str) -> ReportReviewSummary:
        """功能描述：从 Codex 审查长文本中提取结构化三段（优点/问题/建议）。
        切分规则：找"## 优点"后逐行匹配"1."/"数字."前缀切 strengths；"## 问题"后逐行匹配"- "前缀切 issues；
        "## 建议"后切 suggestions；任何段找不到时，三段留空列表并把原文前 800 字写入 raw_excerpt 兜底。

        参数类型：
            - raw_output: str — Codex 审查接口返回的原始长文本（可为空串）

        返回值类型：
            - ReportReviewSummary — 含 {raw_excerpt, strengths[], issues[], suggestions[]} 的 dataclass
        """
        text = raw_output or ""
        summary = ReportReviewSummary(raw_excerpt=text[:800])

        def _extract_block(header_marker: str) -> List[str]:
            """按标题切出块后按行提取项。"""
            idx = text.find(header_marker)
            if idx < 0:
                return []
            block = text[idx + len(header_marker):]
            # 截断到下一个"##"段或文末
            next_heading = block.find("\n## ")
            if next_heading >= 0:
                block = block[:next_heading]
            items: List[str] = []
            for line in block.splitlines():
                s = line.strip()
                if not s:
                    continue
                # 优点：数字. 前缀（1. xxx / 2. xxx）
                if header_marker.endswith("优点"):
                    import re as _re
                    m = _re.match(r"^\d+\.\s*(.+)$", s)
                    if m:
                        items.append(m.group(1).strip())
                # 问题：- 前缀
                elif header_marker.endswith("问题"):
                    if s.startswith("- "):
                        items.append(s[2:].strip())
                # 建议：- 前缀 或 数字. 前缀
                elif header_marker.endswith("建议"):
                    if s.startswith("- "):
                        items.append(s[2:].strip())
                    else:
                        import re as _re2
                        m = _re2.match(r"^\d+\.\s*(.+)$", s)
                        if m:
                            items.append(m.group(1).strip())
            return items

        summary.strengths = _extract_block("## 优点")
        summary.issues = _extract_block("## 问题")
        summary.suggestions = _extract_block("## 建议")
        return summary

    def _generate_job_report(
        self,
        *,
        cwd: str,
        before_snapshot_paths: Set[str],
        before_content_cache: Dict[str, str],
        files_created: List[str],
        config_before: Dict[str, Any],
        config_after: Dict[str, Any],
        codex_review_raw_output: str,
        run_unittest: bool = True,
        run_tsc: bool = True,
    ) -> Optional["JobReport"]:
        """功能描述：生成贾维斯作业报告 5 区块容器（①文件总览 + ②diff + ③验证 + ④审查摘要 + ⑤config 变更）。
        所有 subprocess.run 加 timeout=60；所有 subprocess 异常 try/except 内吞成 validation.exit_code=1 空列表；
        方法整体再套一层 try/except，任何异常返回 JobReport(error=str(e))，绝不向上抛。

        参数类型：
            - cwd: str — 工作目录（绝对路径）
            - before_snapshot_paths: Set[str] — 执行前存在的相对路径集合
            - before_content_cache: Dict[str,str] — 执行前 <=500KB 文本内容缓存（相对路径→utf-8文本）
            - files_created: List[str] — Claude Code dispatcher 检测到的新增/修改文件（相对路径）
            - config_before: Dict — 执行前 config.json 深拷贝
            - config_after: Dict — 执行后 config.json
            - codex_review_raw_output: str — Codex 审查接口的原始输出文本
            - run_unittest: bool — 是否运行 python -m unittest discover（AIVYOS_REPORT_SKIP_UNITTEST=1 时置 False）
            - run_tsc: bool — 是否运行 npx --no-install tsc --noEmit（AIVYOS_REPORT_SKIP_TSC=1 时置 False）

        返回值类型：
            - Optional[JobReport] — 永远非 None（异常时 error 字段非空）；向后兼容返回类型注解仍带 Optional
        """
        t_start = time.perf_counter()
        try:
            # ── 区块 ③：验证结果（unittest + tsc）──────────────────────────
            validation = ReportValidation()
            if run_unittest:
                try:
                    t_u0 = time.perf_counter()
                    # unittest 在项目根目录（cwd 父级或自身）跑；找不到 tests 目录时也不抛
                    r = subprocess.run(
                        ["python", "-m", "unittest", "discover", "-s", "tests", "-q"],
                        cwd=cwd,
                        capture_output=True,
                        timeout=60,
                        text=False,
                    )
                    out = (r.stdout or b"").decode("utf-8", errors="replace") + \
                          (r.stderr or b"").decode("utf-8", errors="replace")
                    parsed = parse_unittest_output(out, exit_code=r.returncode)
                    validation.unit_total = int(parsed.get("total", 0))
                    validation.unit_ok = int(parsed.get("ok", 0))
                    validation.unit_failures = int(parsed.get("failures", 0))
                    validation.unit_errors = int(parsed.get("errors", 0))
                    validation.unit_exit_code = int(r.returncode)
                    validation.unit_elapsed_s = time.perf_counter() - t_u0
                    validation.unit_fail_summary = list(parsed.get("fail_summary", []))
                except Exception as e:
                    validation.unit_exit_code = 1
                    validation.unit_elapsed_s = time.perf_counter() - t_start
                    validation.unit_fail_summary = [{"kind": "INTERNAL", "test": "", "class": "", "file": "", "line": "", "msg": f"{type(e).__name__}: {e}"}]

            if run_tsc:
                try:
                    t_t0 = time.perf_counter()
                    # shell 子目录存在则 cd shell，否则仍在 cwd（不抛）
                    tsc_cwd = cwd
                    if os.path.isdir(os.path.join(cwd, "shell")):
                        tsc_cwd = os.path.join(cwd, "shell")
                    r = subprocess.run(
                        ["npx", "--no-install", "tsc", "--noEmit"],
                        cwd=tsc_cwd,
                        capture_output=True,
                        timeout=60,
                        text=False,
                    )
                    out = (r.stdout or b"").decode("utf-8", errors="replace") + \
                          (r.stderr or b"").decode("utf-8", errors="replace")
                    parsed = parse_tsc_output(out, exit_code=r.returncode)
                    validation.tsc_error_count = int(parsed.get("error_count", 0))
                    validation.tsc_exit_code = int(r.returncode)
                    validation.tsc_elapsed_s = time.perf_counter() - t_t0
                    validation.tsc_items = list(parsed.get("items", []))
                except Exception as e:
                    validation.tsc_exit_code = 1
                    validation.tsc_elapsed_s = time.perf_counter() - t_start
                    validation.tsc_items = [{"file": "", "line": "", "col": "", "code": "INTERNAL", "msg": f"{type(e).__name__}: {e}"}]

            # ── 区块 ①②：文件总览 + unified_diff ──────────────────────────
            file_items: List[ReportFileItem] = []
            for rel_path in files_created:
                abs_path = os.path.join(cwd, rel_path) if not os.path.isabs(rel_path) else rel_path
                meta = file_metadata(abs_path, before_paths=before_snapshot_paths, cwd=cwd)
                before_text = before_content_cache.get(rel_path, "")
                after_text = ""
                try:
                    if os.path.isfile(abs_path):
                        raw = Path(abs_path).read_bytes()
                        after_text = raw.decode("utf-8", errors="replace")
                except OSError:
                    after_text = ""
                diff_unified = ""
                hunks = added = removed = 0
                if before_text or after_text:
                    diff_unified = unified_diff_str(
                        before_text, after_text,
                        fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}",
                    )
                    if diff_unified:
                        hunks = diff_unified.count("\n@@ ")
                        for line in diff_unified.splitlines():
                            if line.startswith("+") and not line.startswith("+++"):
                                added += 1
                            elif line.startswith("-") and not line.startswith("---"):
                                removed += 1
                fi = ReportFileItem(
                    path=meta.get("path", rel_path),
                    status=meta.get("status", "new"),
                    bytes=int(meta.get("bytes", 0)),
                    lines=int(meta.get("lines", 0)),
                )
                if diff_unified:
                    fi.diff = ReportDiff(
                        path=rel_path,
                        unified=diff_unified,
                        hunks=hunks,
                        added=added,
                        removed=removed,
                    )
                file_items.append(fi)

            # ── 区块 ④：Codex 审查摘要 ─────────────────────────────────────
            review_summary = self._extract_codex_summary(codex_review_raw_output)

            # ── 区块 ⑤：config 字段级变更 ──────────────────────────────────
            raw_changes = config_json_diff(config_before or {}, config_after or {})
            config_changes: List[ReportConfigChange] = []
            for c in raw_changes:
                config_changes.append(ReportConfigChange(
                    path=str(c.get("path", "")),
                    before=c.get("before"),
                    after=c.get("after"),
                    change_type=str(c.get("change_type", "update")),
                ))

            job_id = f"jr-{int(t_start * 1000)}"
            report = JobReport(
                job_id=job_id,
                generated_at=t_start,
                generation_ms=(time.perf_counter() - t_start) * 1000.0,
                error="",
                files=file_items,
                validation=validation,
                review_summary=review_summary,
                config_changes=config_changes,
            )
            return report
        except Exception as e:
            # 任何异常：绝不向上抛，写进 report.error
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            return JobReport(
                job_id=f"jr-err-{int(time.time() * 1000)}",
                generated_at=t_start,
                generation_ms=elapsed_ms,
                error=f"{type(e).__name__}: {e}",
                files=[],
                validation=ReportValidation(),
                review_summary=ReportReviewSummary(raw_excerpt=""),
                config_changes=[],
            )
