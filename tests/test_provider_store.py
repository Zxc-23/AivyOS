"""ProviderStore：cc-switch providers + AivyOS manual 的统一 CRUD（AivyOS manual 优先）。"""
import json
import os
import tempfile
import unittest

from aivyos_core.workbench.provider_store import (
    ProviderStore, ProviderItem,
)
from tests import AivyTestCase


class TestProviderStore(AivyTestCase):
    def _make_store(self, cc_rows=None, manual=None, overrides=None):
        """构造 ProviderStore，所有入参均覆盖到临时 AIVYOS_HOME 目录。"""
        tmp = tempfile.mkdtemp(prefix="aivy_store_")
        # 不污染全局 env：ProviderStore 直接接收 home 入参
        # 写 config.json 带 manual + manual_override
        cfg = {
            "agents": {
                "claude": {"manual": manual.get("claude") if manual else None},
                "codex":  {"manual": manual.get("codex") if manual else None},
            },
            "workbench": {
                "manual_override": overrides or {"claude_enabled": False, "codex_enabled": False},
            },
        }
        with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        # 模拟 CCSwitchReader.list_current + list_all
        fake_cc = cc_rows or [
            {"id": "c1", "app_type": "claude", "name": "Claude 3.5 Sonnet", "base_url": "https://api.anthropic.com", "model": "claude-3-5-sonnet", "is_current": True},
            {"id": "c2", "app_type": "claude", "name": "Kimi K2.7",   "base_url": "https://kimi.example.com",  "model": "kimi-k2.7",         "is_current": False},
            {"id": "x1", "app_type": "codex",  "name": "GPT-4o Mini",  "base_url": "https://api.openai.com",    "model": "gpt-4o-mini",      "is_current": True},
        ]
        store = ProviderStore(home=tmp, cc_provider_rows=fake_cc)
        store.reload()
        return store, tmp

    # ── 基本 merge 行为 ─────────────────────────────────────
    def test_list_providers_claude_only_returns_claude_rows(self):
        store, _ = self._make_store()
        items = store.list_providers("claude")
        self.assertTrue(all(i.app_type == "claude" for i in items))
        self.assertEqual(len(items), 2)

    def test_cc_current_item_is_marked_ccswitch_source(self):
        store, _ = self._make_store()
        items = store.list_providers("codex")
        current = next(i for i in items if i.is_current_cc)
        self.assertEqual(current.source, "cc-switch")
        self.assertEqual(current.name, "GPT-4o Mini")

    # ── manual override 生效 ────────────────────────────────
    def test_manual_provider_appears_and_is_source_aivyos_when_enabled(self):
        manual = {
            "claude": {"name": "Ollama qwen2.5:7b", "base_url": "http://127.0.0.1:11434/v1",
                       "model": "qwen2.5:7b", "api_key": "ollama"},
        }
        store, _ = self._make_store(manual=manual, overrides={"claude_enabled": True, "codex_enabled": False})
        items = store.list_providers("claude")
        aivy = next((i for i in items if i.source == "aivyos-manual"), None)
        self.assertIsNotNone(aivy)
        self.assertEqual(aivy.name, "Ollama qwen2.5:7b")
        self.assertTrue(aivy.is_effective, "override enabled 时 aivyos-manual 应当为实际生效项")
        cc = next(i for i in items if i.id == "c1")
        self.assertFalse(cc.is_effective)

    def test_override_disabled_keeps_cc_current_effective(self):
        manual = {"claude": {"name": "X", "base_url": "x", "model": "x", "api_key": "x"}}
        store, _ = self._make_store(manual=manual, overrides={"claude_enabled": False, "codex_enabled": False})
        items = store.list_providers("claude")
        eff = next(i for i in items if i.is_effective)
        self.assertEqual(eff.id, "c1", "override disabled 时应使用 cc-switch 当前项")

    # ── save_manual 写盘 + 下次 reload 可读回 ─────────────
    def test_save_manual_writes_to_config_json(self):
        store, home = self._make_store()
        res = store.save_manual(
            app_type="claude",
            name="Ollama qwen2.5:7b",
            base_url="http://127.0.0.1:11434/v1",
            model="qwen2.5:7b",
            api_key="ollama",
            set_override_enabled=True,
        )
        self.assertTrue(res.ok)
        self.assertEqual(res.source, "aivyos-manual")
        with open(os.path.join(home, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(
            cfg["agents"]["claude"]["manual"]["model"], "qwen2.5:7b",
        )
        self.assertTrue(cfg["workbench"]["manual_override"]["claude_enabled"])

    # ── set_override_toggle 仅切换开关不改值 ──────────────
    def test_set_override_toggle_does_not_touch_manual_value(self):
        manual = {"claude": {"name": "keep", "base_url": "keep", "model": "keep", "api_key": "keep"}}
        store, home = self._make_store(manual=manual, overrides={"claude_enabled": False, "codex_enabled": False})
        store.set_override_toggle("claude", True)
        with open(os.path.join(home, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["agents"]["claude"]["manual"]["model"], "keep")
        self.assertTrue(cfg["workbench"]["manual_override"]["claude_enabled"])

    # ── resolve_credentials（真源：优先级 100% 正确）─────
    def test_resolve_credentials_override_priority(self):
        manual = {"codex": {"name": "A", "base_url": "http://a", "model": "m-a", "api_key": "k-a"}}
        store, _ = self._make_store(manual=manual, overrides={"claude_enabled": False, "codex_enabled": True})
        creds = store.resolve_credentials("codex")
        self.assertEqual(creds["base_url"] if isinstance(creds, dict) else creds.base_url, "http://a")
        self.assertEqual(creds["api_key"]  if isinstance(creds, dict) else creds.api_key,  "k-a")
        self.assertEqual(creds["model"]    if isinstance(creds, dict) else creds.model,    "m-a")
        self.assertEqual(creds["source"]   if isinstance(creds, dict) else creds.source,   "aivyos-manual")

    def test_resolve_credentials_fallback_to_cc(self):
        store, _ = self._make_store()
        creds = store.resolve_credentials("claude")
        b = creds["base_url"] if isinstance(creds, dict) else creds.base_url
        s = creds["source"]   if isinstance(creds, dict) else creds.source
        self.assertTrue(b.startswith("https://api.anthropic"))
        self.assertEqual(s, "cc-switch")

    # ── 校验规则 ───────────────────────────────────────────
    def test_save_manual_rejects_invalid_app_type(self):
        store, _ = self._make_store()
        with self.assertRaises(ValueError):
            store.save_manual(app_type="wrong", name="a", base_url="u", model="m", api_key="k")

    def test_save_manual_rejects_invalid_base_url_scheme(self):
        store, _ = self._make_store()
        res = store.save_manual("claude", "n", "not-a-url", "m", "k")
        self.assertFalse(res.ok)
        self.assertIn("base_url", res.error_message)


# ─────────────────────────────────────────────────────────────
# Task 2: WorkbenchService 集成（provider_store → service 公共 API）
# ─────────────────────────────────────────────────────────────


class TestWorkbenchServiceIntegration(AivyTestCase):
    def _svc(self, cc_rows=None, manual=None, overrides=None):
        tmp = tempfile.mkdtemp(prefix="aivy_svc_")
        # 写 config.json（ProviderStore 读它的路径是 home 根目录下 config.json）
        cfg = {
            "agents": {
                "claude": {"manual": manual.get("claude") if manual else None},
                "codex":  {"manual": manual.get("codex")  if manual else None},
            },
            "workbench": {
                "auto_open_vscode": False,
                "manual_override": overrides or {"claude_enabled": False, "codex_enabled": False},
                "cc_switch": {"enabled": True, "db_path": ""},
                "agents": {
                    "claude_code": {"enabled": False, "manual": {"api_key": "", "base_url": "", "model": ""}},
                    "codex":       {"enabled": False, "manual": {"api_key": "", "base_url": ""}},
                },
                "collaboration": {"review_via_files": False, "auto_open_vscode": False},
                "timeout_s": 300,
            },
        }
        with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        # 构造 service（传 workbench 子配置 + 显式 home 入参）
        from aivyos_core.workbench.service import WorkbenchService
        from aivyos_core.workbench.provider_store import ProviderStore
        svc = WorkbenchService(cfg["workbench"], home=tmp)
        svc.provider_store = ProviderStore(
            home=tmp,
            cc_provider_rows=cc_rows or [
                {"id": "c1", "app_type": "claude", "name": "Kimi",
                 "base_url": "https://kimi", "model": "kimi-k2.7",
                 "is_current": True, "api_key": "sk-123456"},
                {"id": "x1", "app_type": "codex", "name": "GPT-4o Mini",
                 "base_url": "https://openai", "model": "gpt-4o-mini",
                 "is_current": True, "api_key": "sk-987654"},
            ],
        )
        svc.provider_store.reload()
        return svc, tmp

    def test_list_providers_service_returns_dto_shape(self):
        svc, _ = self._svc()
        dto = svc.list_providers("claude")
        self.assertIn("providers", dto)
        self.assertIn("manual_override_enabled", dto)
        self.assertIsInstance(dto["providers"], list)
        for p in dto["providers"]:
            for k in ("id", "name", "base_url", "model", "source", "is_effective"):
                self.assertIn(k, p, f"provider dto 缺少字段 {k}")
            self.assertNotIn("api_key", p, "provider dto 严禁返回真实 api_key")

    def test_save_manual_round_trip(self):
        svc, _ = self._svc()
        res = svc.save_manual({
            "app_type": "codex",
            "name": "Ollama qwen2.5:7b",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5:7b",
            "api_key": "ollama",
            "set_override": True,
        })
        self.assertTrue(res["ok"])
        items = svc.list_providers("codex")["providers"]
        eff = next(p for p in items if p["is_effective"])
        self.assertEqual(eff["source"], "aivyos-manual")
        self.assertEqual(eff["model"],  "qwen2.5:7b")

    def test_set_override_toggle_preserves_manual_value(self):
        svc, _ = self._svc(
            manual={"claude": {"name": "keep", "base_url": "http://k", "model": "mk", "api_key": "kk"}},
            overrides={"claude_enabled": True, "codex_enabled": False},
        )
        svc.set_override("claude", False)
        items = svc.list_providers("claude")["providers"]
        eff = next(p for p in items if p["is_effective"])
        self.assertEqual(eff["source"], "cc-switch")
        aivy = next(p for p in items if p["source"] == "aivyos-manual")
        self.assertEqual(aivy["model"], "mk")

    def test_resolve_credentials_after_save_manual(self):
        svc, _ = self._svc()
        svc.save_manual({
            "app_type": "claude", "name": "A", "api_key": "K",
            "base_url": "http://a/v1", "model": "ma", "set_override": True,
        })
        creds = svc.resolve_credentials_for_dispatch("claude")
        self.assertEqual(creds.source, "aivyos-manual")
        self.assertEqual(creds.env["ANTHROPIC_MODEL"], "ma")
        self.assertEqual(creds.env["ANTHROPIC_AUTH_TOKEN"], "K")


# ─────────────────────────────────────────────────────────────
# Task 2: TestJobReportPipeline — 贾维斯作业报告管线 4 条集成单测
# ─────────────────────────────────────────────────────────────


class TestJobReportPipeline(AivyTestCase):
    """AIVY-REPORT-001 Task2: 报告生成管线集成测试（4 条）。"""

    # ------------------------------------------------------------------
    # 辅助：构造带 WorkbenchService 的临时环境
    # ------------------------------------------------------------------
    def _svc(self, cc_rows=None, manual=None, overrides=None):
        """与 TestWorkbenchServiceIntegration._svc 同款辅助函数。"""
        tmp = tempfile.mkdtemp(prefix="aivy_jrp_")
        cfg = {
            "agents": {
                "claude": {"manual": manual.get("claude") if manual else None},
                "codex":  {"manual": manual.get("codex")  if manual else None},
            },
            "workbench": {
                "auto_open_vscode": False,
                "manual_override": overrides or {"claude_enabled": False, "codex_enabled": False},
                "cc_switch": {"enabled": True, "db_path": ""},
                "agents": {
                    "claude_code": {"enabled": False, "manual": {"api_key": "", "base_url": "", "model": ""}},
                    "codex":       {"enabled": False, "manual": {"api_key": "", "base_url": ""}},
                },
                "collaboration": {"review_via_files": False, "auto_open_vscode": False},
                "timeout_s": 300,
            },
        }
        with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        from aivyos_core.workbench.service import WorkbenchService
        from aivyos_core.workbench.provider_store import ProviderStore
        svc = WorkbenchService(cfg["workbench"], home=tmp)
        svc.provider_store = ProviderStore(
            home=tmp,
            cc_provider_rows=cc_rows or [
                {"id": "c1", "app_type": "claude", "name": "Kimi",
                 "base_url": "https://kimi", "model": "kimi-k2.7",
                 "is_current": True, "api_key": "sk-123456"},
                {"id": "x1", "app_type": "codex", "name": "GPT-4o Mini",
                 "base_url": "https://openai", "model": "gpt-4o-mini",
                 "is_current": True, "api_key": "sk-987654"},
            ],
        )
        svc.provider_store.reload()
        return svc, tmp

    # ------------------------------------------------------------------
    # Test 1: 报告生成正常路径（subprocess 被 monkeypatch 绕过）
    # ------------------------------------------------------------------
    def test_jrp_1_report_generated_ok(self):
        """_generate_job_report 正常产出报告：files==1，status=="new"，unittest 3/3 通过。"""
        import subprocess as _sp
        svc, home = self._svc()
        # 1. 构造 cwd + 模拟产出文件 a.txt
        cwd = tempfile.mkdtemp(prefix="aivy_jrp_cwd_")
        a_txt = os.path.join(cwd, "a.txt")
        with open(a_txt, "w", encoding="utf-8") as f:
            f.write("hello aivy\nline2\n")
        files_created = ["a.txt"]
        before_snapshot_paths = set()  # a.txt 之前不存在 → status=new
        before_content_cache: dict = {}
        # 2. 前后 config（不变，用于 diff）
        with open(os.path.join(home, "config.json"), encoding="utf-8") as f:
            config_before = json.load(f)
        config_after = json.loads(json.dumps(config_before))
        codex_review_raw = ""

        # 3. monkeypatch subprocess.run：
        #    - unittest discover → exit 0, stdout="Ran 3 tests in 0.01s\n\nOK\n"
        #    - tsc --noEmit → exit 0, stdout=""
        call_count = {"n": 0}
        original_run = _sp.run

        def fake_run(cmd, **kwargs):
            call_count["n"] += 1
            # 按调用顺序：第一次是 unittest，第二次是 tsc
            if call_count["n"] == 1:
                class _R:
                    returncode = 0
                    stdout = "Ran 3 tests in 0.01s\n\nOK\n".encode("utf-8")
                    stderr = b""
                return _R()
            else:
                class _R:
                    returncode = 0
                    stdout = b""
                    stderr = b""
                return _R()

        import aivyos_core.workbench.service as _svc_mod
        _svc_mod.subprocess.run = fake_run  # 打补丁到 service 模块 import 的 subprocess
        try:
            report = svc._generate_job_report(
                cwd=cwd,
                before_snapshot_paths=before_snapshot_paths,
                before_content_cache=before_content_cache,
                files_created=files_created,
                config_before=config_before,
                config_after=config_after,
                codex_review_raw_output=codex_review_raw,
                run_unittest=True,
                run_tsc=True,
            )
        finally:
            _svc_mod.subprocess.run = original_run

        self.assertIsNotNone(report, "_generate_job_report 必须返回 JobReport（非 None）")
        self.assertEqual(report.error, "", "正常路径 report.error 必须为空字符串")
        self.assertEqual(len(report.files), 1, f"files_created 含 1 项应产出 1 条 FileItem，实际 {len(report.files)}")
        self.assertEqual(report.files[0].status, "new", "a.txt 不在 before_snapshot_paths 中应标记 new")
        self.assertEqual(report.validation.unit_total, 3, f"unittest Ran 3 应解析为 unit_total=3，实际={report.validation.unit_total}")
        self.assertEqual(report.validation.unit_ok, 3, f"全部通过时 unit_ok 应=3，实际={report.validation.unit_ok}")

    # ------------------------------------------------------------------
    # Test 2: 报告生成失败被内吞，主流程不抛异常
    # ------------------------------------------------------------------
    def test_jrp_2_report_error_swallows(self):
        """_generate_job_report 内抛 ValueError 必须被包进 report.error，外部不抛。"""
        svc, home = self._svc()
        cwd = tempfile.mkdtemp(prefix="aivy_jrp_cwd_err_")
        before_snapshot_paths = set()
        before_content_cache: dict = {}
        # 至少 1 项才能触发 file_metadata 调用
        files_created: list = ["b.txt"]
        with open(os.path.join(home, "config.json"), encoding="utf-8") as f:
            config_before = json.load(f)
        config_after = json.loads(json.dumps(config_before))

        # service.py 顶部是 from report_tools import file_metadata（本地绑定），
        # 所以必须补丁到 aivyos_core.workbench.service.file_metadata 才能生效
        import aivyos_core.workbench.service as _svc_mod
        original_fm_svc = _svc_mod.file_metadata

        def boom_fm(*a, **kw):
            raise ValueError("boom")

        _svc_mod.file_metadata = boom_fm
        try:
            # 外部必须不抛异常
            report = None
            raised = None
            try:
                report = svc._generate_job_report(
                    cwd=cwd,
                    before_snapshot_paths=before_snapshot_paths,
                    before_content_cache=before_content_cache,
                    files_created=files_created,
                    config_before=config_before,
                    config_after=config_after,
                    codex_review_raw_output="",
                    run_unittest=False,
                    run_tsc=False,
                )
            except Exception as e:
                raised = e
            self.assertIsNone(raised, f"_generate_job_report 绝不能向上抛异常，但实际抛了 {type(raised).__name__}: {raised}")
            self.assertIsNotNone(report, "异常被内吞后仍应返回 JobReport 对象（非 None）")
            self.assertIn("boom", report.error, f"report.error 应含 'boom'，实际={report.error!r}")
        finally:
            _svc_mod.file_metadata = original_fm_svc

    # ------------------------------------------------------------------
    # Test 3: parse_unittest_output 真实调用（5 tests, 1 fail + 1 err → ok=3）
    # ------------------------------------------------------------------
    def test_jrp_3_parse_unittest_real_invocation(self):
        """直接对 report_tools.parse_unittest_output 断言解析结果：5 total → ok=3。"""
        from aivyos_core.workbench.report_tools import parse_unittest_output
        real_output = "Ran 5 tests in 0.01s\nFAILED (failures=1, errors=1)\n"
        r = parse_unittest_output(real_output, exit_code=1)
        self.assertEqual(r["total"], 5, f"total 应=5，实际={r['total']}")
        self.assertEqual(r["failures"], 1)
        self.assertEqual(r["errors"], 1)
        self.assertEqual(r["ok"], 3, f"5-1-1=3 应等于 unit_ok，实际={r['ok']}")
        self.assertEqual(r["exit_code"], 1)

    # ------------------------------------------------------------------
    # Test 4: config_json_diff 真实调用（workbench.manual_override.claude_enabled update）
    # ------------------------------------------------------------------
    def test_jrp_4_config_diff_real_invocation(self):
        """手动构造 before/after dict，断言 workbench.manual_override.claude_enabled 出现 change_type==update。"""
        from aivyos_core.workbench.report_tools import config_json_diff
        before = {
            "workbench": {
                "manual_override": {"claude_enabled": False, "codex_enabled": False},
                "timeout_s": 300,
            },
            "agents": {"claude": {"manual": None}},
        }
        after = {
            "workbench": {
                "manual_override": {"claude_enabled": True, "codex_enabled": False},
                "timeout_s": 300,
            },
            "agents": {"claude": {"manual": {"name": "Ollama qwen2.5:7b"}}},
        }
        changes = config_json_diff(before, after)
        self.assertTrue(len(changes) >= 1, "至少 1 条 change")
        paths = {c["path"]: c for c in changes}
        self.assertIn("workbench.manual_override.claude_enabled", paths,
                      "必须包含 workbench.manual_override.claude_enabled 路径")
        self.assertEqual(
            paths["workbench.manual_override.claude_enabled"]["change_type"], "update",
            f"该路径 change_type 应为 'update'，实际={paths['workbench.manual_override.claude_enabled']['change_type']!r}"
        )
        self.assertEqual(paths["workbench.manual_override.claude_enabled"]["before"], False)
        self.assertEqual(paths["workbench.manual_override.claude_enabled"]["after"], True)


if __name__ == "__main__":
    unittest.main()
