# cc-switch UI 融合集成（方案 A 顶部快切 + 方案 B 侧边详情面板）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在协同工作台 UI 中同时提供「顶部一行快速切换」（方案 A）和「左侧常驻详情面板」（方案 B），实现双向联动 + 可编辑配置 + 健康检查 + 覆盖优先级切换，并通过统一 backend 调用 `AivyOS manual 优先` 策略真正生效到双 CLI。

**Architecture:** 三端分离：
1. **ProviderStore（Python 服务端）**：合并 cc-switch.db 当前激活 provider 列表 + AivyOS config `manual` 中保存的手动预设，输出单一真值源 `list_providers(app_type)`。所有写入（保存手动配置、切覆盖、存预设、重载、健康检查）都在 WorkbenchService 中，绝不碰 cc-switch.db 本身。
2. **Bridge API（Tauri IPC）**：6 个命令（list_providers / save_manual / set_override / reload / health_check / save_preset），chat.ts 中提供类型安全 wrapper。
3. **React UI（App.tsx + styles.css）**：顶部 `cctop` 控件 + 左侧 `cc-aside` 面板，共享同一份 `ccState`（Claude/Codex 双 Provider 及详情表单），双向联动。

**Tech Stack:** Python 3.12 stdlib（零第三方，server_entry.py 用 Tauri 既有命令注册机制）+ TypeScript 5.x + React 18 + CSS 变量（与现有 `var(--bg-2)` 风格一致）+ unittest（后端）。

---

## 文件结构与职责边界

| 操作 | 文件路径 | 职责 | 范围 |
|---|---|---|---|
| Create | `aivyos_core/workbench/provider_store.py` | ProviderStore：合并 cc-switch 读 + manual 预设 + override 优先级；增删改查 CRUD | 纯数据层，不含 IPC |
| Modify | `aivyos_core/workbench/service.py:1-300` | WorkbenchService：新增 6 个 public 方法调用 ProviderStore；不破坏现有 `status()/run_*()` | 业务层 |
| Modify | `aivyos_core/server_entry.py` | 注册 6 个新 `@tauri.command`（workbench.list_providers 等） | Bridge 层 |
| Modify | `shell/src/chat.ts` | 新增 6 个 Promise wrapper + 对应 DTO（`WorkbenchProviderItem` 等） | TS 类型层 |
| Modify | `shell/src/styles.css` | 新增 `cctop / cc-aside / cc-toggle / pill-* / provider-row / seg-button` 样式 | UI 外观 |
| Modify | `shell/src/App.tsx` | ① workbench screen 结构改成"左侧面板 + 右侧主区"；② 顶部 cctop 控件；③ `ccState` 与双向联动；④ cc-switch 控件状态 pill（加载/成功/错误） | UI 交互 |
| Create | `tests/test_provider_store.py` | ProviderStore 单测：list/merge/override/save/reload | 后端测试 |
| Modify | `说明文档.md` | 2.2 节更新为 A+B 融合描述；进度表登记 6 个子任务的结果 | 文档 |

---

## Task 1: ProviderStore — 合并 cc-switch provider 与 AivyOS manual 预设（纯数据层）

**Files:**
- Create: `aivyos_core/workbench/provider_store.py`
- Modify: `aivyos_core/config.py` — 新增 `manual_override.claude_enabled / codex_enabled` 默认值
- Test: `tests/test_provider_store.py`

- [ ] **Step 1: 写 failing test**

在 `tests/test_provider_store.py` 写入：

```python
"""ProviderStore：cc-switch providers + AivyOS manual 的统一 CRUD（AivyOS manual 优先）。"""
import json
import os
import tempfile
import unittest

from aivyos_core.workbench.provider_store import (
    ProviderStore, ProviderItem, MergeResult,
)
from tests import AivyTestCase


class TestProviderStore(AivyTestCase):
    def _make_store(self, cc_rows=None, manual=None, overrides=None):
        """构造 ProviderStore，所有入参均覆盖到临时 AIVYOS_HOME 目录。"""
        tmp = tempfile.mkdtemp(prefix="aivy_store_")
        os.environ["AIVYOS_HOME"] = tmp
        self.addCleanup(lambda: os.environ.pop("AIVYOS_HOME", None))
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
        self.assertEqual(creds["base_url"], "http://a")
        self.assertEqual(creds["api_key"],  "k-a")
        self.assertEqual(creds["model"],    "m-a")
        self.assertEqual(creds["source"],   "aivyos-manual")

    def test_resolve_credentials_fallback_to_cc(self):
        store, _ = self._make_store()
        creds = store.resolve_credentials("claude")
        self.assertTrue(creds["base_url"].startswith("https://api.anthropic"))
        self.assertEqual(creds["source"], "cc-switch")

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
cd f:\AivyOS\aivyos ; chcp 65001 > $null ; python -m unittest tests.test_provider_store -v
```
Expected: FAIL 全部用例（ModuleNotFoundError → `aivyos_core.workbench.provider_store` 不存在）。

- [ ] **Step 3: 写 ProviderStore 最小实现**

新建 `aivyos_core/workbench/provider_store.py`：

```python
"""ProviderStore：cc-switch provider 列表 + AivyOS manual 预设的统一 CRUD。

核心契约（来自 roles.py 贾维斯 = 调度执行者，用户 = 发布者）：
  • ProviderStore 只读不写 cc-switch.db（避免第三方锁库风险 + SQLite 版本漂移）。
  • 所有写入落到 AivyOS 自己 config.json 的 agents.{app_type}.manual 字段
    与 workbench.manual_override.{app_type}_enabled 开关。
  • resolve_credentials() 是全局唯一真源：
      ① override_enabled=True 且 manual 非空 → 优先取 aivyos-manual
      ② 否则 → 取 cc-switch.db 的 is_current=True 那行（已有 CCSwitchReader）
  • 返回 ProviderItem.source 枚举：cc-switch | aivyos-manual | preset。
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlparse


AppType = Literal["claude", "codex"]
VALID_APP_TYPES: Tuple[AppType, ...] = ("claude", "codex")

# ─────────────────────────────────────────────────────────────
# 数据类型
# ─────────────────────────────────────────────────────────────

@dataclass
class ProviderItem:
    """UI 层直接消费的 provider 条目。

    source:
        cc-switch      — 从 cc-switch.db 读取（只读）
        aivyos-manual  — 从 config.json agents.<app>.manual 读取（用户在 UI 中保存的手动覆盖）
        preset         — 保存在 config.json 的预设（不自动生效，可选加载）
    is_current_cc:   该项是否为 cc-switch 里 is_current=True 的那行
    is_effective:    按 override 优先级最终生效的项（列表里最多一个为 True）
    """
    id: str
    app_type: AppType
    name: str
    base_url: str
    model: str
    source: Literal["cc-switch", "aivyos-manual", "preset"]
    api_key_masked: str = "***"                # UI 展示用，永远不返回真实 key
    is_current_cc: bool = False
    is_effective: bool = False
    base_url_truncated: str = ""               # UI 展示截断
    preset_id: Optional[str] = None

    def __post_init__(self):
        if not self.base_url_truncated and self.base_url:
            # 只留协议+host:port，截掉 /v1 等后续路径
            try:
                parsed = urlparse(self.base_url)
                host = parsed.netloc or self.base_url
                self.base_url_truncated = host
            except Exception:
                self.base_url_truncated = self.base_url[:40]


@dataclass
class SaveResult:
    ok: bool
    source: Literal["aivyos-manual", "cc-switch"] = "aivyos-manual"
    error_message: str = ""
    active_name: str = ""


@dataclass
class Credentials:
    """双 CLI Dispatcher 消费用：env 变量 + base_url/model/api_key/source。"""
    app_type: AppType
    source: Literal["cc-switch", "aivyos-manual"]
    base_url: str
    model: str
    api_key: str                                # 真实 key（仅限进程内内存使用，不入日志/不回前端）
    env: Dict[str, str] = field(default_factory=dict)
    display_name: str = ""


# ─────────────────────────────────────────────────────────────
# Store
# ─────────────────────────────────────────────────────────────

class ProviderStore:
    """cc-switch 读 + AivyOS 手动预设的合并视图。"""

    CONFIG_FILENAME = "config.json"
    PRESETS_FILENAME  = "presets.json"  # 同 home 目录下

    def __init__(
        self,
        home: str,
        cc_provider_rows: Optional[List[Dict[str, Any]]] = None,
        cc_reader=None,  # CCSwitchReader 实例（可选，生产代码中直接调它）
    ):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self._cc_rows: List[Dict[str, Any]] = list(cc_provider_rows or [])
        self._cc_reader = cc_reader

    # ── 基础 IO ────────────────────────────────────────────
    def _read_config(self) -> Dict[str, Any]:
        p = self.home / self.CONFIG_FILENAME
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                return {}
        return {}

    def _write_config(self, cfg: Dict[str, Any]) -> None:
        # 原子写：先写 temp 再 rename，避免中途崩溃破坏 config
        p = self.home / self.CONFIG_FILENAME
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)

    def _read_presets(self) -> Dict[str, List[Dict[str, Any]]]:
        p = self.home / self.PRESETS_FILENAME
        if not p.exists():
            return {"claude": [], "codex": []}
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in VALID_APP_TYPES:
                data.setdefault(k, [])
            return data
        except (OSError, json.JSONDecodeError):
            return {"claude": [], "codex": []}

    def _write_presets(self, presets: Dict[str, List[Dict[str, Any]]]) -> None:
        p = self.home / self.PRESETS_FILENAME
        with open(p, "w", encoding="utf-8") as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)

    # ── 合并 & 计算有效项 ─────────────────────────────────
    def reload(self) -> None:
        """重新扫 cc-switch + config（用户点 '从 cc-switch 重载' 时调用）。"""
        if self._cc_reader is not None:
            try:
                self._cc_rows = list(self._cc_reader.list_all() or [])
            except Exception:
                # cc-switch 不可用不影响使用，用户仍可纯手动
                self._cc_rows = []

    @staticmethod
    def _mask_key(k: Optional[str]) -> str:
        if not k:
            return "***"
        if len(k) <= 4:
            return "*" * len(k)
        return k[:2] + "*" * max(2, len(k) - 4) + k[-2:]

    @staticmethod
    def _validate_base_url(url: str) -> Optional[str]:
        if not isinstance(url, str) or not url.strip():
            return "base_url 不能为空"
        try:
            parsed = urlparse(url.strip())
            if parsed.scheme not in ("http", "https"):
                return "base_url 必须以 http:// 或 https:// 开头"
            if not parsed.netloc:
                return "base_url 缺少 host"
        except Exception as e:
            return f"base_url 格式非法: {e}"
        return None

    @staticmethod
    def _validate_app_type(app_type: str) -> AppType:
        if app_type not in VALID_APP_TYPES:
            raise ValueError(f"app_type 必须是 {VALID_APP_TYPES}，收到 {app_type!r}")
        return app_type  # type: ignore[return-value]

    # ── 公共 API：列表/保存/切换/重载 ─────────────────────
    def list_providers(self, app_type: str) -> List[ProviderItem]:
        """按 app_type 列出合并后的 ProviderItem 列表。"""
        at: AppType = self._validate_app_type(app_type)
        cfg = self._read_config()
        manual: Optional[Dict[str, Any]] = (cfg.get("agents") or {}).get(at, {}).get("manual")
        overrides: Dict[str, Any] = (cfg.get("workbench") or {}).get("manual_override") or {}
        override_enabled: bool = bool(overrides.get(f"{at}_enabled"))

        cc_items: List[ProviderItem] = []
        cc_current: Optional[ProviderItem] = None
        for row in self._cc_rows:
            if str(row.get("app_type")) != at:
                continue
            item = ProviderItem(
                id=str(row.get("id") or f"cc-{row.get('name','')}"),
                app_type=at,
                name=str(row.get("name") or f"cc {at} provider"),
                base_url=str(row.get("base_url") or ""),
                model=str(row.get("model") or ""),
                source="cc-switch",
                api_key_masked=self._mask_key(row.get("api_key")),
                is_current_cc=bool(row.get("is_current")),
                is_effective=False,
            )
            cc_items.append(item)
            if item.is_current_cc:
                cc_current = item

        # aivyos-manual 项（永远显示，is_effective 由 override_enabled 决定）
        manual_item: Optional[ProviderItem] = None
        if manual and manual.get("base_url"):
            manual_item = ProviderItem(
                id=f"manual-{at}",
                app_type=at,
                name=str(manual.get("name") or f"AivyOS 手动（{at}）"),
                base_url=str(manual.get("base_url") or ""),
                model=str(manual.get("model") or ""),
                source="aivyos-manual",
                api_key_masked=self._mask_key(manual.get("api_key")),
                is_current_cc=False,
                is_effective=override_enabled,
            )

        # preset 项（只展示，不参与 effective 决策）
        preset_items: List[ProviderItem] = []
        for p in self._read_presets().get(at, []):
            preset_items.append(ProviderItem(
                id=f"preset-{at}-{p.get('preset_id') or p.get('name','')}",
                app_type=at,
                name=str(p.get("name") or ""),
                base_url=str(p.get("base_url") or ""),
                model=str(p.get("model") or ""),
                source="preset",
                api_key_masked=self._mask_key(p.get("api_key")),
                preset_id=str(p.get("preset_id") or ""),
            ))

        # effective 决定：manual_item 在 override_enabled=True 时才压制 cc_current
        eff = manual_item if (manual_item and override_enabled) else cc_current
        if eff is not None:
            eff.is_effective = True
            # 确保 cc_current 与 manual_item 不同时同时为 True
            if eff is cc_current and manual_item is not None and manual_item.is_effective:
                manual_item.is_effective = False
            if eff is manual_item and cc_current is not None:
                cc_current.is_effective = False

        result: List[ProviderItem] = []
        if manual_item:
            result.append(manual_item)
        result.extend(cc_items)
        result.extend(preset_items)
        return result

    def save_manual(
        self,
        app_type: str,
        name: str,
        base_url: str,
        model: str,
        api_key: str,
        set_override_enabled: Optional[bool] = None,
    ) -> SaveResult:
        """写入 AivyOS config 的 manual 字段，不碰 cc-switch.db。"""
        at: AppType = self._validate_app_type(app_type)
        if not isinstance(model, str) or not model.strip():
            return SaveResult(False, error_message="model 不能为空", active_name="")
        url_err = self._validate_base_url(base_url)
        if url_err:
            return SaveResult(False, error_message=url_err, active_name="")

        cfg = self._read_config()
        agents = cfg.setdefault("agents", {})
        agents.setdefault(at, {})["manual"] = {
            "name":     str(name or f"AivyOS 手动（{at}）"),
            "base_url": base_url.strip(),
            "model":    model.strip(),
            "api_key":  api_key or "",
        }
        wb = cfg.setdefault("workbench", {})
        o  = wb.setdefault("manual_override", {
            f"{t}_enabled": False for t in VALID_APP_TYPES
        })
        for t in VALID_APP_TYPES:
            o.setdefault(f"{t}_enabled", False)
        if set_override_enabled is not None:
            o[f"{at}_enabled"] = bool(set_override_enabled)
        self._write_config(cfg)

        return SaveResult(
            ok=True, source="aivyos-manual",
            active_name=agents[at]["manual"]["name"],
        )

    def set_override_toggle(self, app_type: str, enabled: bool) -> SaveResult:
        """只切 manual_override 开关，不修改 manual 具体值。"""
        at: AppType = self._validate_app_type(app_type)
        cfg = self._read_config()
        wb = cfg.setdefault("workbench", {})
        o  = wb.setdefault("manual_override", {f"{t}_enabled": False for t in VALID_APP_TYPES})
        for t in VALID_APP_TYPES:
            o.setdefault(f"{t}_enabled", False)
        o[f"{at}_enabled"] = bool(enabled)
        self._write_config(cfg)

        agents = cfg.get("agents") or {}
        manual = agents.get(at, {}).get("manual") or {}
        return SaveResult(
            ok=True,
            source="cc-switch" if (not enabled) else "aivyos-manual",
            active_name=manual.get("name", "") if enabled else self._cc_current_name(at),
        )

    def save_preset(
        self, app_type: str, preset_name: str,
        base_url: str, model: str, api_key: str,
    ) -> bool:
        """把当前 base/model/key 另存为预设，不出现在 effective 决策中。"""
        at: AppType = self._validate_app_type(app_type)
        url_err = self._validate_base_url(base_url)
        if url_err:
            return False
        if not isinstance(preset_name, str) or not preset_name.strip():
            return False
        import uuid as _uuid
        presets = self._read_presets()
        presets[at].append({
            "preset_id": _uuid.uuid4().hex[:10],
            "name": preset_name.strip(),
            "base_url": base_url.strip(),
            "model":    model.strip(),
            "api_key":  api_key or "",
        })
        self._write_presets(presets)
        return True

    def load_preset_into_manual(self, app_type: str, preset_id: str, set_override_enabled: bool = True) -> SaveResult:
        at: AppType = self._validate_app_type(app_type)
        presets = self._read_presets()
        match = next((p for p in presets.get(at, []) if str(p.get("preset_id")) == preset_id), None)
        if not match:
            return SaveResult(False, error_message=f"preset_id={preset_id} 不存在")
        return self.save_manual(
            app_type=at, name=str(match.get("name")),
            base_url=str(match.get("base_url")), model=str(match.get("model")),
            api_key=str(match.get("api_key") or ""),
            set_override_enabled=set_override_enabled,
        )

    # ── Dispatcher 消费：获取最终 env + 凭据 ────────────────
    def resolve_credentials(self, app_type: str) -> Credentials:
        """双 CLI 执行前必调：按优先级算出最终生效的 env/base/model/key。"""
        at: AppType = self._validate_app_type(app_type)
        cfg = self._read_config()
        manual: Optional[Dict[str, Any]] = (cfg.get("agents") or {}).get(at, {}).get("manual")
        overrides = (cfg.get("workbench") or {}).get("manual_override") or {}
        override_enabled = bool(overrides.get(f"{at}_enabled"))
        use_manual = (override_enabled and manual and manual.get("base_url") and manual.get("model"))
        if use_manual:
            base_url = str(manual["base_url"])
            model    = str(manual["model"])
            api_key  = str(manual.get("api_key") or "")
            display  = str(manual.get("name") or f"AivyOS 手动（{at}）")
            source: Literal["cc-switch", "aivyos-manual"] = "aivyos-manual"
            env: Dict[str, str] = self._build_env(at, base_url, model, api_key, aivy_mode=True)
            return Credentials(
                app_type=at, source=source, base_url=base_url, model=model,
                api_key=api_key, env=env, display_name=display,
            )
        # 回退 cc-switch 当前行
        cc_current = next((r for r in self._cc_rows
                           if str(r.get("app_type")) == at and bool(r.get("is_current"))), None)
        if cc_current is None and self._cc_reader is not None:
            try:
                cred = self._cc_reader.get_active_credentials(for_cli=("claude_code" if at == "claude" else "codex"))
                env = dict(cred.get("env") or {})
                return Credentials(
                    app_type=at, source="cc-switch",
                    base_url=env.get("BASE_URL") or env.get("ANTHROPIC_BASE_URL")
                             or env.get("OPENAI_API_BASE") or "",
                    model=(cred.get("config") or {}).get("model") or env.get("ANTHROPIC_MODEL") or env.get("OPENAI_MODEL") or "",
                    api_key=env.get("ANTHROPIC_AUTH_TOKEN") or env.get("OPENAI_API_KEY") or "",
                    env=env,
                    display_name=cred.get("name") or f"cc-switch {at}",
                )
            except Exception:
                pass
        if cc_current is None:
            raise RuntimeError(
                f"[{at}] 既没有启用 AivyOS 手动覆盖，cc-switch.db 也没有 is_current 行；"
                "请先在 UI 保存手动配置或启用 cc-switch 凭据。"
            )
        env_cc = self._build_env_from_cc_row(at, cc_current)
        return Credentials(
            app_type=at, source="cc-switch",
            base_url=str(cc_current.get("base_url") or ""),
            model=str(cc_current.get("model") or ""),
            api_key=str(cc_current.get("api_key") or ""),
            env=env_cc, display_name=str(cc_current.get("name") or f"cc-switch {at}"),
        )

    # ── helpers: env 构建 ──────────────────────────────────
    @staticmethod
    def _build_env(app_type: AppType, base_url: str, model: str, api_key: str, aivy_mode: bool) -> Dict[str, str]:
        """aivyos-manual 走手动 env 构造：Claude 用 ANTHROPIC_*，Codex 用 OPENAI_*。"""
        if app_type == "claude":
            env = {
                "ANTHROPIC_AUTH_TOKEN": api_key or "ollama",
                "ANTHROPIC_BASE_URL":   base_url,
                "ANTHROPIC_MODEL":      model,
            }
        else:
            env = {
                "OPENAI_API_KEY":      api_key or "ollama",
                "OPENAI_API_BASE":     base_url,
                "OPENAI_BASE_URL":     base_url,
                "OPENAI_MODEL":        model,
            }
        return env

    @staticmethod
    def _build_env_from_cc_row(app_type: AppType, row: Dict[str, Any]) -> Dict[str, str]:
        """cc-switch provider 结构来自 CCSwitchReader.list_all：app_type + auth + config。"""
        if app_type == "claude":
            auth = row.get("auth") or {}
            cfg  = row.get("config") or {}
            env  = {
                "ANTHROPIC_AUTH_TOKEN": str(auth.get("ANTHROPIC_AUTH_TOKEN") or auth.get("ANTHROPIC_API_KEY") or ""),
                "ANTHROPIC_BASE_URL":   str(auth.get("ANTHROPIC_BASE_URL") or ""),
                "ANTHROPIC_MODEL":      str(cfg.get("model") or row.get("model") or ""),
            }
            return {k: v for k, v in env.items() if v}
        # codex
        auth = row.get("auth") or {}
        cfg  = row.get("config") or {}
        env = {
            "OPENAI_API_KEY":  str(auth.get("OPENAI_API_KEY") or ""),
            "OPENAI_API_BASE": str(auth.get("OPENAI_API_BASE") or auth.get("OPENAI_BASE_URL") or ""),
            "OPENAI_BASE_URL": str(auth.get("OPENAI_BASE_URL") or auth.get("OPENAI_API_BASE") or ""),
            "OPENAI_MODEL":    str(cfg.get("model") or row.get("model") or ""),
        }
        return {k: v for k, v in env.items() if v}

    def _cc_current_name(self, app_type: AppType) -> str:
        row = next((r for r in self._cc_rows
                    if str(r.get("app_type")) == app_type and bool(r.get("is_current"))), None)
        return str(row.get("name") or "") if row else ""
```

- [ ] **Step 4: 在 config.py 补齐 manual_override 默认值**

修改 `aivyos_core/config.py` DEFAULT_CONFIG：

在已有的 `"workbench"` 段（约第 230-250 行 `auto_open_vscode` / `timeout_s` 附近）追加：

```python
        # cc-switch 集成：manual 覆盖优先级开关
        # True  时 resolve_credentials() 优先取 agents.<app_type>.manual
        # False 时完全退回 cc-switch.db 当前激活项
        "manual_override": {
            "claude_enabled": False,
            "codex_enabled":  False,
        },
```

在 DEFAULT_CONFIG 顶层 `"agents"` 段补默认值（如果此前还没有 agents 段就新增；如果已有则合并）：

```python
    "agents": {
        "claude": {"manual": None},   # None 表示尚未启用 AivyOS 手动
        "codex":  {"manual": None},
    },
```

- [ ] **Step 5: Run provider_store tests 确认通过**

Run:
```powershell
cd f:\AivyOS\aivyos ; chcp 65001 > $null ; python -m unittest tests.test_provider_store -v
```
Expected: OK（10 tests 左右）。

---

## Task 2: WorkbenchService 暴露 6 个 public 方法 + 健康检查 / 双探活

**Files:**
- Modify: `aivyos_core/workbench/service.py`
- Test: 追加到 `tests/test_provider_store.py` 作为新的 `class TestWorkbenchServiceIntegration`

- [ ] **Step 1: 写 failing test**

追加到 `tests/test_provider_store.py` 尾部：

```python
# ─────────────────────────────────────────────────────────────
# Task 2: WorkbenchService 集成（provider_store → service 公共 API）
# ─────────────────────────────────────────────────────────────
from aivyos_core.workbench.service import WorkbenchService


class TestWorkbenchServiceIntegration(AivyTestCase):
    def _svc(self, cc_rows=None, manual=None, overrides=None):
        tmp = tempfile.mkdtemp(prefix="aivy_svc_")
        os.environ["AIVYOS_HOME"] = tmp
        self.addCleanup(lambda: os.environ.pop("AIVYOS_HOME", None))
        cfg = {
            "agents": {
                "claude": {"manual": manual.get("claude") if manual else None},
                "codex":  {"manual": manual.get("codex")  if manual else None},
            },
            "workbench": {
                "auto_open_vscode": False,
                "manual_override": overrides or {"claude_enabled": False, "codex_enabled": False},
            },
        }
        with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        svc = WorkbenchService(home=tmp)
        # 注入一个不依赖 cc-switch.db 的假 ProviderStore
        from aivyos_core.workbench.provider_store import ProviderStore
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
        # save 后立刻读回，应当 aivyos-manual is_effective
        items = svc.list_providers("codex")["providers"]
        eff = next(p for p in items if p["is_effective"])
        self.assertEqual(eff["source"], "aivyos-manual")
        self.assertEqual(eff["model"],  "qwen2.5:7b")

    def test_set_override_toggle_preserves_manual_value(self):
        svc, _ = self._svc(
            manual={"claude": {"name": "keep", "base_url": "http://k", "model": "mk", "api_key": "kk"}},
            overrides={"claude_enabled": True, "codex_enabled": False},
        )
        # override 关掉 → effective 回到 cc-switch
        svc.set_override("claude", False)
        items = svc.list_providers("claude")["providers"]
        eff = next(p for p in items if p["is_effective"])
        self.assertEqual(eff["source"], "cc-switch")
        # 但 manual 值仍然保留
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
```

Run:
```powershell
cd f:\AivyOS\aivyos ; python -m unittest tests.test_provider_store.TestWorkbenchServiceIntegration -v
```
Expected: FAIL（WorkbenchService 还没暴露 list_providers/save_manual/set_override/resolve_credentials_for_dispatch 这四个方法）。

- [ ] **Step 2: 在 WorkbenchService 中实现 6 个 public 方法**

修改 `aivyos_core/workbench/service.py`：

顶部 import 增加：

```python
from aivyos_core.workbench.provider_store import (
    ProviderStore, ProviderItem, SaveResult, Credentials,
)
```

在 `WorkbenchService.__init__` 中，初始化 `self.provider_store`：

```python
    def __init__(
        self,
        home: Optional[str] = None,
        cc_switch_reader=None,
        vscode_dispatcher=None,
        claude_code_dispatcher=None,
        codex_cli_dispatcher=None,
        prompt_templates: Optional[TemplateRegistry] = None,
        engine=None,
    ) -> None:
        self.home = Path(home) if home else (Path.home() / ".aivyos")
        self.home.mkdir(parents=True, exist_ok=True)
        self.cc_switch_reader = cc_switch_reader
        self.vscode_dispatcher = vscode_dispatcher
        self.claude_code_dispatcher = claude_code_dispatcher
        self.codex_cli_dispatcher  = codex_cli_dispatcher
        self.prompt_templates = prompt_templates or TemplateRegistry.default()
        self.engine = engine

        # ── 新增 ─────────────────────────────────────────────
        # ProviderStore 统一 cc-switch + manual：优先用 reader 里的真实数据
        try:
            rows = list(cc_switch_reader.list_all() or []) if cc_switch_reader else None
        except Exception:
            rows = None
        self.provider_store = ProviderStore(
            home=str(self.home),
            cc_provider_rows=rows,
            cc_reader=cc_switch_reader,
        )
        self.provider_store.reload()
```

在 WorkbenchService 尾部追加 6 个方法：

```python
    # ─────────────────────────────────────────────────────────────
    # Provider 管理（cc-switch + AivyOS 手动统一入口）
    # ─────────────────────────────────────────────────────────────

    def list_providers(self, app_type: str) -> Dict[str, Any]:
        """Bridge API：返回指定 app_type 的合并 Provider 列表 + override 开关状态。"""
        items: List[ProviderItem] = self.provider_store.list_providers(app_type)
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
            res: SaveResult = self.provider_store.save_manual(
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
            res: SaveResult = self.provider_store.set_override_toggle(app_type, enabled)
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
        app_type = str(dto.get("app_type") or "claude")
        try:
            # 优先用入参给的凭据（用户"健康检查"按钮时）
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
    def _probe_provider(self, creds: Credentials) -> Tuple[bool, str]:
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
                # 404 表示没实现 /v1/models，改用 1 token completions 探活
                if e.code in (404, 405):
                    return self._probe_provider_via_completion(creds)
                return False, f"HTTP {e.code}"
            except Exception as e:
                return False, str(e)
        # claude：/v1/messages 请求 1 token
        return self._probe_provider_via_completion(creds)

    def _probe_provider_via_completion(self, creds: Credentials) -> Tuple[bool, str]:
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
            # 401/403 = key 错；404 = 端点错；400 model 不存在
            return False, f"HTTP {e.code}"
        except Exception as e:
            return False, str(e)

    # ── Dispatcher 消费：resolve_credentials_for_dispatch ──
    def resolve_credentials_for_dispatch(self, app_type: str) -> Credentials:
        """双 CLI 执行前的统一凭据真源。"""
        return self.provider_store.resolve_credentials(app_type)
```

- [ ] **Step 3: 同时改造现有 `_read_cc_switch_and_prepare_env` 逻辑使用新的 resolve**

找到 WorkbenchService 中原来在 `_dispatch_*` 里调用 cc_switch_reader.get_active_credentials() 的代码（service.py L160 左右的 `_prepare_env_for_cli` 方法），改为：

```python
    def _prepare_env_for_cli(self, app_type: Literal["claude", "codex"]) -> Dict[str, str]:
        """双 CLI 执行前构建 env。统一走 provider_store.resolve_credentials。"""
        creds = self.provider_store.resolve_credentials(app_type)
        return dict(creds.env)
```

（如果原来没有 `_prepare_env_for_cli` 方法，找到所有 `cc_switch_reader.get_active_credentials(for_cli=...)` 调用点，统一改为调用 `_prepare_env_for_cli`。）

- [ ] **Step 4: 跑 Task 2 新增的 TestWorkbenchServiceIntegration 单测**

Run:
```powershell
cd f:\AivyOS\aivyos ; python -m unittest tests.test_provider_store.TestWorkbenchServiceIntegration -v
```
Expected: OK（4/4）。

---

## Task 3: 注册 6 个新 Bridge 命令（server_entry.py + chat.ts 类型 DTO）

**Files:**
- Modify: `aivyos_core/server_entry.py`
- Modify: `shell/src/chat.ts`

- [ ] **Step 1: server_entry.py 注册 workbench.* 命令**

找到已有的 `workbench_status / workbench_claude / workbench_codex` 等注册点（约在 L80-L200），追加：

```python
# ─────────────────────────────────────────────────────────────
# Task 3: cc-switch Provider 管理
# ─────────────────────────────────────────────────────────────
@app.command("workbench.list_providers")
def workbench_list_providers(app_type: str) -> dict:
    """列出指定 app_type（claude/codex）合并后的 Provider 列表 + override 开关 + 预设。"""
    ensure_service()
    return SERVICE.list_providers(app_type)


@app.command("workbench.save_manual")
def workbench_save_manual(dto: dict) -> dict:
    """保存 AivyOS 手动覆盖（不修改 cc-switch.db）。"""
    ensure_service()
    return SERVICE.save_manual(dto)


@app.command("workbench.set_override")
def workbench_set_override(app_type: str, enabled: bool) -> dict:
    """切换 AivyOS 手动覆盖的启用开关。"""
    ensure_service()
    return SERVICE.set_override(app_type, enabled)


@app.command("workbench.reload")
def workbench_reload() -> dict:
    """重新扫 cc-switch.db + 当前 config。"""
    ensure_service()
    return SERVICE.reload_from_ccswitch()


@app.command("workbench.save_preset")
def workbench_save_preset(dto: dict) -> dict:
    """另存当前配置为预设（不出现在 override 决策）。"""
    ensure_service()
    return SERVICE.save_preset(dto)


@app.command("workbench.health_check")
def workbench_health_check(dto: dict) -> dict:
    """对当前生效或给定的 provider 发送 1 字探活消息。"""
    ensure_service()
    return SERVICE.health_check_provider(dto)
```

- [ ] **Step 2: chat.ts 新增前端 wrapper**

在 `shell/src/chat.ts`（约在现有 `workbenchStatus` 之后）追加：

```typescript
// ============================================================
// cc-switch UI 融合集成（方案 A 顶部 + 方案 B 侧边）
// ============================================================

export interface WorkbenchProviderItem {
  id: string;
  app_type: "claude" | "codex";
  name: string;
  base_url: string;
  base_url_display: string;
  model: string;
  source: "cc-switch" | "aivyos-manual" | "preset";
  api_key_masked: string;
  is_current_cc: boolean;
  is_effective: boolean;
  preset_id?: string;
}

export interface WorkbenchPreset {
  id: string;
  preset_id: string;
  name: string;
  base_url: string;
  model: string;
  app_type: "claude" | "codex";
}

export interface WorkbenchProvidersDto {
  providers: WorkbenchProviderItem[];
  presets: WorkbenchPreset[];
  manual_override_enabled: boolean;
}

export interface WorkbenchSaveManualDto {
  app_type: "claude" | "codex";
  name: string;
  base_url: string;
  model: string;
  api_key: string;
  set_override?: boolean;
}

export interface WorkbenchSavePresetDto extends WorkbenchSaveManualDto {
  preset_name: string;
}

export interface WorkbenchHealthCheckDto {
  app_type: "claude" | "codex";
  base_url?: string;
  model?: string;
  api_key?: string;
}

export interface WorkbenchSaveResultDto {
  ok: boolean;
  source: "aivyos-manual" | "cc-switch" | "";
  active_name: string;
  error_message: string;
}

export interface WorkbenchHealthResultDto {
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
  display_name: string;
}

/**
 * workbench.list_providers — 按 app_type 列出合并后的 Provider 列表
 * @param app_type "claude" 或 "codex"
 */
export function workbenchListProviders(app_type: "claude" | "codex"): Promise<WorkbenchProvidersDto> {
  return invoke<WorkbenchProvidersDto>("workbench.list_providers", { app_type });
}

/** workbench.save_manual — 保存 AivyOS 手动覆盖（不修改 cc-switch.db） */
export function workbenchSaveManual(dto: WorkbenchSaveManualDto): Promise<WorkbenchSaveResultDto> {
  return invoke<WorkbenchSaveResultDto>("workbench.save_manual", { dto });
}

/** workbench.set_override — 切换手动覆盖开关 */
export function workbenchSetOverride(app_type: "claude" | "codex", enabled: boolean): Promise<WorkbenchSaveResultDto> {
  return invoke<WorkbenchSaveResultDto>("workbench.set_override", { app_type, enabled });
}

/** workbench.reload — 重扫 cc-switch.db + config */
export function workbenchReload(): Promise<{
  ok: boolean;
  claude: WorkbenchProvidersDto;
  codex: WorkbenchProvidersDto;
}> {
  return invoke<any>("workbench.reload");
}

/** workbench.save_preset — 另存为预设 */
export function workbenchSavePreset(dto: WorkbenchSavePresetDto): Promise<{
  ok: boolean;
  presets: WorkbenchPreset[];
}> {
  return invoke<any>("workbench.save_preset", { dto });
}

/** workbench.health_check — 对给定或当前生效的 provider 发 1 字探活 */
export function workbenchHealthCheck(dto: WorkbenchHealthCheckDto): Promise<WorkbenchHealthResultDto> {
  return invoke<WorkbenchHealthResultDto>("workbench.health_check", { dto });
}
```

- [ ] **Step 3: 冒烟：import 编译通过**

前端：
```powershell
cd f:\AivyOS\aivyos\shell ; npx tsc --noEmit 2>&1 | Select-Object -First 50
```
Expected: 无 chat.ts 相关错误。

后端：
```powershell
cd f:\AivyOS\aivyos ; python -c "from aivyos_core import server_entry; print('OK server_entry imports')"
```

---

## Task 4: styles.css 新增 cctop / cc-aside / pill / toggle 样式

**Files:**
- Modify: `shell/src/styles.css`

- [ ] **Step 1: 追加 cc-switch UI 融合样式**

在 `shell/src/styles.css` 文件尾部（`.tabler` 或现有 workbench 样式之后）追加：

```css
/* ============================================================
 * cc-switch UI 融合集成（方案 A 顶部 + 方案 B 侧边）
 * 完全沿用现有 dark-glass 变量：var(--bg-2)/--accent/--accent-2
 * ============================================================ */

/* ── 布局：workbench screen 内部改为左 aside + 右 main ───── */
.screen .settings-screen .wb-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 16px;
  align-items: start;
}
@media (max-width: 900px) {
  .screen .settings-screen .wb-layout {
    grid-template-columns: 1fr;
  }
}

/* ── 顶部 cctop（方案 A 一行快切） ───────────────────────── */
.cctop {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: linear-gradient(90deg,
    rgba(var(--accent-rgb), 0.08),
    rgba(var(--accent-2-rgb), 0.06));
  border: 1px solid var(--line);
  border-radius: 10px;
  margin-bottom: 14px;
}
.cctop .cc-section { display: inline-flex; align-items: center; gap: 8px; flex-shrink: 0; }
.cctop .cc-label {
  font-size: 11px; font-weight: 600;
  color: var(--muted2); letter-spacing: .5px;
  text-transform: uppercase;
  min-width: 56px;
}
.cctop .cc-label.c-claude { color: #f472b6; }
.cctop .cc-label.c-codex  { color: #a78bfa; }

.cc-select { position: relative; }
.cc-select select {
  appearance: none; -webkit-appearance: none;
  padding: 6px 30px 6px 12px;
  min-width: 190px;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
  transition: border-color .2s, background .2s;
}
.cc-select select:hover    { border-color: var(--accent); }
.cc-select select:focus    { outline: none; border-color: var(--accent);
                             box-shadow: 0 0 0 2px rgba(var(--accent-rgb), 0.15); }
.cc-select::after {
  content: "▾"; position: absolute; right: 10px; top: 50%;
  transform: translateY(-50%); color: var(--muted2); font-size: 10px;
  pointer-events: none;
}

.cc-icon-btn {
  width: 28px; height: 28px;
  background: var(--bg-2);
  border: 1px solid var(--line);
  color: var(--muted2);
  border-radius: 6px;
  cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 12px;
  transition: all .18s;
}
.cc-icon-btn:hover { background: rgba(var(--accent-rgb), 0.1); color: var(--accent); border-color: var(--accent); }
.cc-icon-btn.active { background: rgba(var(--accent-rgb), 0.16); color: var(--accent); border-color: var(--accent); }

.cc-divider { width: 1px; height: 28px; background: var(--line); }

.cc-actions { margin-left: auto; display: inline-flex; align-items: center; gap: 8px; }

/* pills */
.pill { display: inline-flex; align-items: center; gap: 6px;
        padding: 3px 11px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.pill.on  { background: rgba(16,185,129,0.12); color: #34d399; border: 1px solid rgba(16,185,129,0.35); }
.pill.off { background: rgba(71,85,105,0.3);  color: #94a3b8; border: 1px solid #475569; }
.pill.warn{ background: rgba(245,158,11,0.14); color: #fbbf24; border: 1px solid rgba(245,158,11,0.4); }
.pill.err { background: rgba(239,68,68,0.12);  color: #f87171; border: 1px solid rgba(239,68,68,0.4); }
.pill .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: .85; }

/* buttons */
.btn { padding: 6px 13px; border-radius: 7px; font-size: 12px; font-weight: 600;
       border: 0; cursor: pointer; display: inline-flex; align-items: center; gap: 5px;
       transition: all .18s; }
.btn-primary { background: linear-gradient(90deg, var(--accent), var(--accent-2));
               color: #fff; box-shadow: 0 4px 14px rgba(var(--accent-rgb), 0.28); }
.btn-primary:hover { transform: translateY(-1px); box-shadow: 0 6px 18px rgba(var(--accent-rgb), 0.35); }
.btn-primary:disabled { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }
.btn-ghost { background: transparent; color: var(--muted2); border: 1px solid var(--line); }
.btn-ghost:hover { background: rgba(239,68,68,0.1); color: #f87171; border-color: rgba(239,68,68,0.4); }
.btn-warn  { background: rgba(245,158,11,0.1); color: #fbbf24; border: 1px solid rgba(245,158,11,0.35); }
.btn-warn:hover { background: rgba(245,158,11,0.18); }

/* spinner inline */
.spin-inline { display: inline-flex; align-items: center; gap: 5px;
               padding: 3px 9px; border-radius: 4px;
               font-size: 11px; background: rgba(245,158,11,0.1); color: #fbbf24; }
.spin { width: 9px; height: 9px; border-radius: 50%;
        border: 1.5px solid rgba(245,158,11,0.25);
        border-top-color: #fbbf24; animation: sp 1s linear infinite; }
@keyframes sp { to { transform: rotate(360deg); } }
.ok-inline { display: inline-flex; align-items: center; gap: 4px;
             padding: 3px 8px; border-radius: 4px;
             font-size: 11px; color: #34d399;
             background: rgba(16,185,129,0.1); }

/* ── 侧边 cc-aside（方案 B） ───────────────────────────── */
.cc-aside {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 10px;
  position: sticky; top: 8px;
  max-height: calc(100vh - 120px);
  overflow: auto;
}
.cc-aside h5 {
  margin: 0 0 8px; padding-bottom: 6px;
  border-bottom: 1px dashed var(--line);
  font-size: 11px; letter-spacing: .5px; font-weight: 700;
  display: flex; align-items: center; justify-content: space-between;
}
.cc-aside h5 .n-c { color: #f472b6; }
.cc-aside h5 .n-x { color: #a78bfa; }
.cc-aside h5 .src { font-size: 9px; font-weight: 500; padding: 2px 7px; border-radius: 4px; }
.cc-aside h5 .src.cc   { background: rgba(59,130,246,0.15); color: #60a5fa; }
.cc-aside h5 .src.aivy { background: rgba(16,185,129,0.15); color: #34d399; }

.cc-aside .provider-list { margin: 4px 0 10px; }
.provider-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; margin-bottom: 4px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background .15s, border-color .15s;
}
.provider-row:hover { background: rgba(var(--accent-rgb), 0.07); }
.provider-row.active {
  background: rgba(var(--accent-rgb), 0.12);
  border-color: rgba(var(--accent-rgb), 0.4);
}
.provider-row.effective::before {
  content: "●"; color: #10b981; font-size: 10px; margin-right: 2px;
}
.provider-row .radio {
  width: 12px; height: 12px; border-radius: 50%;
  border: 1.5px solid #475569; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
}
.provider-row.active .radio {
  border-color: var(--accent);
}
.provider-row.active .radio::after {
  content: ""; width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent);
}
.provider-row .pi-meta { flex: 1; min-width: 0; }
.provider-row .pi-name { font-size: 12px; color: var(--text); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.provider-row .pi-sub  { font-size: 10px; color: var(--muted2); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.provider-row .pi-tag { font-size: 9px; padding: 1px 6px; border-radius: 4px; flex-shrink: 0; }
.pi-tag.cc { background: rgba(59,130,246,0.15); color: #60a5fa; }
.pi-tag.aivy { background: rgba(16,185,129,0.15); color: #34d399; }
.pi-tag.ps { background: rgba(245,158,11,0.15); color: #fbbf24; }

/* 侧边内字段表单 */
.cc-field { margin: 7px 0; }
.cc-field label {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 10.5px; color: var(--muted2); margin-bottom: 3px;
}
.cc-field label .hint { color: #475569; font-size: 9px; }
.cc-field input {
  width: 100%;
  background: var(--bg-3);
  border: 1px solid var(--line);
  color: var(--text);
  padding: 5px 9px;
  border-radius: 5px;
  font-size: 11.5px;
  font-family: Consolas, "Cascadia Mono", monospace;
  outline: none;
  transition: all .18s;
}
.cc-field input:focus   { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(var(--accent-rgb), 0.12); }
.cc-field input.invalid { border-color: #ef4444;   box-shadow: 0 0 0 2px rgba(239,68,68,0.12); }
.cc-field input.success { border-color: #10b981; }

.cc-row-2 { display: grid; grid-template-columns: 1fr 80px; gap: 8px; }

/* toggle switch */
.cc-toggle {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 10.5px; color: var(--muted2); cursor: pointer; user-select: none;
}
.cc-toggle .sw {
  width: 28px; height: 15px; border-radius: 999px; background: #475569;
  position: relative; transition: background .2s;
}
.cc-toggle .sw::after {
  content: ""; position: absolute;
  width: 11px; height: 11px; border-radius: 50%;
  background: #fff; top: 2px; left: 2px;
  transition: left .2s;
}
.cc-toggle.on { color: #34d399; }
.cc-toggle.on .sw { background: linear-gradient(90deg, #10b981, #059669); }
.cc-toggle.on .sw::after { left: 15px; }

/* 提示条：优先级说明 / Ollama base_url 只能到 /v1 等 */
.cc-hint {
  font-size: 10.5px; color: var(--muted2); line-height: 1.6;
  padding: 7px 9px; margin-top: 4px;
  background: rgba(245,158,11,0.07);
  border: 1px dashed rgba(245,158,11,0.3);
  border-radius: 5px;
}
.cc-hint b { color: #fbbf24; }

/* separator between claude & codex panels in aside */
.cc-split {
  height: 1px; background: var(--line);
  margin: 14px 0; opacity: .6;
}

/* —— 展开式内联配置编辑（A+ 方案）：与 cctop 配合使用 ——— */
.ccconfig {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 14px 22px;
  padding: 12px 14px;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  margin: 10px 0 14px;
  overflow: hidden;
  max-height: 2000px;
  transition: max-height .35s ease, padding .3s ease;
}
.ccconfig.hidden { max-height: 0; padding-top: 0; padding-bottom: 0; border: 0; margin: 0; }
@media (max-width: 720px) { .ccconfig { grid-template-columns: 1fr; } }
```

- [ ] **Step 2: 检查现有样式变量是否已定义 --bg-2/--line/--accent/--accent-2/--accent-rgb/--accent-2-rgb/--muted2/--text**

打开 `shell/src/styles.css` 顶部 `:root` 段，若有缺失的变量，补全如下（最小改动，不修改已有值）：

```css
:root {
  /* ── 如果以下变量已存在则跳过 ─────────────────────── */
  --bg-2:      #111b2e;   /* 深色面板，比 bg 深一级 */
  --bg-3:      #0a1222;   /* 更深的输入框底 */
  --line:      #22304c;
  --text:      #e6eefb;
  --muted2:    #8aa0c4;
  --accent:    #60a5fa;
  --accent-2:  #c084fc;
  --accent-rgb:   96, 165, 250;
  --accent-2-rgb: 192, 132, 252;
}
```

---

## Task 5: App.tsx 顶部 cctop 控件 + 侧边 cc-aside 面板（A+B 融合，双向联动）

**Files:**
- Modify: `shell/src/App.tsx`
- 依赖：Task 3 新增的 6 个 `workbench*` bridge 函数必须已经 import 到 App.tsx 顶部

- [ ] **Step 1: App.tsx 顶部 import 新增**

找到 App.tsx 现有 `import { ... workbenchClaude, workbenchCodex ... } from "./chat"` 行，追加：

```typescript
import {
  workbenchListProviders, workbenchSaveManual, workbenchSetOverride,
  workbenchReload, workbenchSavePreset, workbenchHealthCheck,
  WorkbenchProviderItem, WorkbenchSaveManualDto, WorkbenchHealthCheckDto,
} from "./chat";
```

- [ ] **Step 2: 在 App() 组件内部 state 区新增 ccState 相关 hooks**

在 `const [wbRunning, setWbRunning] = useState(false);` 附近（约 L200-L240）追加：

```typescript
  // ── cc-switch UI 融合（方案 A 顶部 + 方案 B 侧边） ──
  type CCAppType = "claude" | "codex";

  // 当前生效 Provider id（每 app_type 一个）
  const [ccActiveId, setCcActiveId] = useState<Record<CCAppType, string>>({
    claude: "", codex: "",
  });

  // 表单值：用户未应用前的 in-memory 草稿
  type CCForm = { name: string; base_url: string; model: string; api_key: string; override: boolean; };
  const [ccForm, setCcForm] = useState<Record<CCAppType, CCForm>>({
    claude: { name: "", base_url: "", model: "", api_key: "", override: false },
    codex:  { name: "", base_url: "", model: "", api_key: "", override: false },
  });

  // 加载 / 错误 / 健康检查临时状态
  const [ccLoading, setCcLoading] = useState<Record<CCAppType, boolean>>({ claude: false, codex: false });
  const [ccMsg, setCcMsg] = useState<Record<CCAppType, {type: "ok"|"warn"|"err", text: string} | null>>({ claude: null, codex: null });
  const [ccApplyBusy, setCcApplyBusy] = useState(false);
  const [ccConfigOpen, setCcConfigOpen] = useState(true);

  // 完整 provider 列表（桥端返回）
  const [ccProviders, setCcProviders] = useState<Record<CCAppType, WorkbenchProviderItem[]>>({
    claude: [], codex: [],
  });
  const [ccSourceBadge, setCcSourceBadge] = useState<Record<CCAppType, "cc-switch"|"aivyos-manual"|"">>({
    claude: "", codex: "",
  });

  // provider 列表加载 + 表单项填充
  const loadCCProviders = async (only?: CCAppType) => {
    const targets: CCAppType[] = only ? [only] : ["claude", "codex"];
    for (const t of targets) {
      try {
        setCcLoading(prev => ({ ...prev, [t]: true }));
        const dto = await workbenchListProviders(t);
        setCcProviders(prev => ({ ...prev, [t]: dto.providers }));
        const eff = dto.providers.find(p => p.is_effective);
        if (eff) {
          setCcActiveId(prev => ({ ...prev, [t]: eff.id }));
          setCcSourceBadge(prev => ({ ...prev, [t]: eff.source === "preset" ? "" : eff.source }));
          // 回填表单（aivyos-manual 优先 → 否则用当前 cc 行）
          const fillSrc = dto.providers.find(p => p.source === "aivyos-manual") || eff;
          if (fillSrc) {
            setCcForm(prev => ({
              ...prev,
              [t]: {
                name: fillSrc.name,
                base_url: fillSrc.base_url,
                model: fillSrc.model,
                api_key: prev[t].api_key, // key 不回写真实值，仅保留用户未保存草稿
                override: dto.manual_override_enabled,
              },
            }));
          }
        }
        setCcMsg(prev => ({ ...prev, [t]: null }));
      } catch (e) {
        setCcMsg(prev => ({ ...prev, [t]: { type: "err", text: `加载失败：${(e as Error).message.slice(0, 60)}` } }));
      } finally {
        setCcLoading(prev => ({ ...prev, [t]: false }));
      }
    }
  };

  // 初次进入 workbench tab 时加载一次
  useEffect(() => {
    if (nav === "workbench") {
      void loadCCProviders();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nav]);
```

- [ ] **Step 3: 切换 Provider 时表单联动（方案 B 点击某行时的行为）**

继续追加：

```typescript
  // 方案 B：侧边点击 provider row → 顶部下拉 + 表单全部同步
  const onSelectProvider = (t: CCAppType, id: string) => {
    const list = ccProviders[t];
    const item = list.find(p => p.id === id);
    if (!item) return;
    setCcActiveId(prev => ({ ...prev, [t]: id }));
    if (item.source !== "preset") {
      setCcForm(prev => ({
        ...prev,
        [t]: {
          name: item.name,
          base_url: item.base_url,
          model: item.model,
          api_key: prev[t].api_key, // key 不返回
          override: item.source === "aivyos-manual" ? prev[t].override : false,
        },
      }));
    } else {
      // preset：立即填充 + 给出提示"点应用加载到 manual"
      setCcForm(prev => ({
        ...prev,
        [t]: {
          ...prev[t],
          name: item.name,
          base_url: item.base_url,
          model: item.model,
        },
      }));
      setCcMsg(prev => ({
        ...prev, [t]: { type: "warn", text: "已填入预设：请点'应用切换'把该预设加载为 AivyOS 手动覆盖。" },
      }));
    }
  };

  // 应用切换：保存 manual + 可选切 override + 双健康检查
  const applyCC = async (t: CCAppType) => {
    const f = ccForm[t];
    // 前端基本校验
    if (!f.base_url || !/^https?:\/\//i.test(f.base_url)) {
      setCcMsg(prev => ({ ...prev, [t]: { type: "err", text: "Base URL 必须以 http:// 或 https:// 开头" } }));
      return;
    }
    if (!f.model.trim()) {
      setCcMsg(prev => ({ ...prev, [t]: { type: "err", text: "模型名不能为空" } }));
      return;
    }
    try {
      setCcApplyBusy(true);
      setCcLoading(prev => ({ ...prev, [t]: true }));
      const saveDto: WorkbenchSaveManualDto = {
        app_type: t,
        name: f.name || `AivyOS 手动（${t}）`,
        base_url: f.base_url,
        model: f.model,
        api_key: f.api_key,
        set_override: f.override,
      };
      const saved = await workbenchSaveManual(saveDto);
      if (!saved.ok) {
        setCcMsg(prev => ({ ...prev, [t]: { type: "err", text: saved.error_message || "保存失败" } }));
        return;
      }
      // 健康检查
      const hcDto: WorkbenchHealthCheckDto = {
        app_type: t,
        base_url: f.base_url, model: f.model, api_key: f.api_key || undefined,
      };
      const hc = await workbenchHealthCheck(hcDto);
      await loadCCProviders(t);
      if (hc.ok) {
        setCcMsg(prev => ({
          ...prev, [t]: { type: "ok", text: `✔ 已切换 · 健康检查 ${hc.latency_ms ?? "?"}ms` },
        }));
      } else {
        setCcMsg(prev => ({
          ...prev, [t]: { type: "warn", text: `⚠ 已保存但健康检查失败：${hc.error?.slice(0, 80) ?? ""}` },
        }));
      }
    } catch (e) {
      setCcMsg(prev => ({ ...prev, [t]: { type: "err", text: `应用失败：${(e as Error).message.slice(0, 80)}` } }));
    } finally {
      setCcApplyBusy(false);
      setCcLoading(prev => ({ ...prev, [t]: false }));
      setTimeout(() => {
        setCcMsg(prev => ({ ...prev, [t]: (prev[t] && prev[t]!.type === "err") ? prev[t] : null }));
      }, 3800);
    }
  };

  // 单独健康检查按钮
  const pingCC = async (t: CCAppType) => {
    try {
      setCcLoading(prev => ({ ...prev, [t]: true }));
      const f = ccForm[t];
      const dto: WorkbenchHealthCheckDto = f.base_url
        ? { app_type: t, base_url: f.base_url, model: f.model, api_key: f.api_key || undefined }
        : { app_type: t };
      const res = await workbenchHealthCheck(dto);
      setCcMsg(prev => ({
        ...prev, [t]: res.ok
          ? { type: "ok",   text: `✔ 健康检查 ${res.latency_ms ?? "?"}ms (${res.display_name})` }
          : { type: "err",  text: `✖ 健康失败：${res.error?.slice(0, 70) ?? ""}` },
      }));
    } catch (e) {
      setCcMsg(prev => ({ ...prev, [t]: { type: "err", text: `健康检查异常：${(e as Error).message.slice(0, 70)}` } }));
    } finally {
      setCcLoading(prev => ({ ...prev, [t]: false }));
    }
  };

  // 从 cc-switch 重载
  const reloadCC = async () => {
    try {
      setCcApplyBusy(true);
      await workbenchReload();
      await loadCCProviders();
      setCcMsg({
        claude: { type: "ok", text: "✔ 已从 cc-switch + config 重载（丢弃本地草稿）" },
        codex:  null,
      });
    } catch (e) {
      setCcMsg({
        claude: { type: "err", text: `重载失败：${(e as Error).message.slice(0, 70)}` },
        codex:  null,
      });
    } finally {
      setCcApplyBusy(false);
    }
  };

  // 保存预设
  const saveAsPresetCC = async (t: CCAppType) => {
    const f = ccForm[t];
    if (!f.name || !f.base_url || !f.model) {
      setCcMsg(prev => ({ ...prev, [t]: { type: "warn", text: "请先填完名称、Base URL、模型名" } }));
      return;
    }
    const preset_name = window.prompt("预设名称（如：Ollama-qwen7b）", f.name)?.trim();
    if (!preset_name) return;
    try {
      await workbenchSavePreset({
        app_type: t, preset_name, name: f.name,
        base_url: f.base_url, model: f.model, api_key: f.api_key,
      });
      setCcMsg(prev => ({ ...prev, [t]: { type: "ok", text: `✔ 已保存预设：${preset_name}` } }));
      await loadCCProviders(t);
    } catch (e) {
      setCcMsg(prev => ({ ...prev, [t]: { type: "err", text: `保存预设失败：${(e as Error).message.slice(0, 70)}` } }));
    }
  };

  // override 开关
  const toggleOverride = async (t: CCAppType, on: boolean) => {
    setCcForm(prev => ({ ...prev, [t]: { ...prev[t], override: on } }));
    try {
      await workbenchSetOverride(t, on);
      await loadCCProviders(t);
      setCcMsg(prev => ({
        ...prev, [t]: on
          ? { type: "ok",   text: "✔ AivyOS 手动覆盖：已启用（优先级高于 cc-switch）" }
          : { type: "warn", text: "⚠ 手动覆盖：已关闭（退回 cc-switch 当前激活项）" },
      }));
    } catch (e) {
      setCcMsg(prev => ({ ...prev, [t]: { type: "err", text: `切换失败：${(e as Error).message.slice(0, 70)}` } }));
    }
  };

  // 工具：构造方案 A 顶部下拉的 <option> 项
  const providerLabel = (p: WorkbenchProviderItem) => {
    const srcMark =
        p.source === "aivyos-manual" ? "(AivyOS 手动)"
      : p.source === "preset"       ? "(预设)"
      : p.is_current_cc             ? "(cc-switch · 当前)"
      : "(cc-switch)";
    return `${p.name} — ${p.model} ${srcMark}`;
  };
```

- [ ] **Step 4: 替换 workbench screen 的 JSX 为 A+B 融合布局**

找到 `{/* ============ 13. 协同工作台 (workbench) ============ */}` 这一段（约 L4705）的外层结构，从外层 `<div className="settings-screen">` 内的标题+子标题开始，整体改写成：

```tsx
            {/* ============ 13. 协同工作台 (workbench) ============ */}
            <div className={`screen ${nav === "workbench" ? "active" : ""}`}>
              <div className="settings-screen">
                <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
                  贾维斯调度台 — 驱动 Claude · Codex 双模型完成任务
                </div>
                <div style={{ fontSize: 12, color: "var(--muted2)", marginBottom: 14 }}>
                  贾维斯统一读取 cc-switch 配置、调度双 CLI 资源（串行/并行/文档模板），完成后自动输出结构化作业报告并汇报给你
                </div>

                {/* 环境状态 pill 条：仍保留 */}
                {wbStatus && (
                  <div style={{ fontSize: 11, color: "var(--muted2)", marginBottom: 10 }}>
                    cc-switch: {wbStatus.cc_switch?.enabled ? (
                      <span className="pill on"><span className="dot"></span>已启用</span>
                    ) : (
                      <span className="pill warn"><span className="dot"></span>未启用（仍可用 AivyOS 手动模式）</span>
                    )}
                    {"  "}Claude: <span className="pill on"><span className="dot"></span>{wbStatus.claude?.available ? "开" : "关"}</span>
                    {"  "}Codex:  <span className="pill on"><span className="dot"></span>{wbStatus.codex?.available  ? "开" : "关"}</span>
                    {"  "}<span className="pill off">VS Code: {"不在"}</span>
                    {"  "}
                    {ccSourceBadge.claude && <span className={`pill ${ccSourceBadge.claude === "aivyos-manual" ? "on" : ""}`} style={{marginRight:6}}>Claude={ccSourceBadge.claude}</span>}
                    {ccSourceBadge.codex  && <span className={`pill ${ccSourceBadge.codex  === "aivyos-manual" ? "on" : ""}`}>Codex={ccSourceBadge.codex}</span>}
                  </div>
                )}

                {/* ======================================================
                 * 方案 A：顶部一行快切 cctop
                 * ====================================================== */}
                <div className="cctop">
                  {(["claude", "codex"] as CCAppType[]).map((t, idx) => (
                    <React.Fragment key={t}>
                      {idx > 0 && <div className="cc-divider"></div>}
                      <div className="cc-section">
                        <span className={`cc-label c-${t}`}>{t === "claude" ? "▸ Claude" : "▸ Codex"}</span>
                        <div className="cc-select">
                          <select
                            value={ccActiveId[t]}
                            disabled={ccLoading[t] || ccApplyBusy}
                            onChange={(e) => onSelectProvider(t, e.target.value)}
                            title={t === "claude" ? "快速选择 Claude Provider" : "快速选择 Codex Provider"}
                          >
                            {ccProviders[t].length === 0 && <option value="">（无 Provider）</option>}
                            {ccProviders[t].map(p => (
                              <option key={p.id} value={p.id}>
                                {providerLabel(p)}
                                {p.is_effective ? " ✔ 当前生效" : ""}
                              </option>
                            ))}
                          </select>
                        </div>
                        <button
                          className={`cc-icon-btn ${ccConfigOpen ? "active" : ""}`}
                          onClick={() => setCcConfigOpen(v => !v)}
                          title="展开/收起内联配置编辑（方案 A+）"
                        >✎</button>
                        <button
                          className="cc-icon-btn"
                          disabled={ccLoading[t]}
                          onClick={() => pingCC(t)}
                          title={`对${t === "claude" ? "Claude" : "Codex"}当前配置做健康检查`}
                        >❤</button>
                        {ccMsg[t] && (
                          ccMsg[t]!.type === "ok" ? <span className="ok-inline">{ccMsg[t]!.text}</span>
                          : ccMsg[t]!.type === "warn" ? <span className="pill warn">{ccMsg[t]!.text}</span>
                          : <span className="pill err">{ccMsg[t]!.text}</span>
                        )}
                      </div>
                    </React.Fragment>
                  ))}

                  <div className="cc-divider"></div>

                  <div className="cc-actions">
                    <button className="btn btn-warn"  disabled={ccApplyBusy} onClick={() => reloadCC()}>↺ 从 cc-switch 重载</button>
                    <button className="btn btn-ghost" disabled={ccApplyBusy} onClick={() => saveAsPresetCC("claude")}>＋ 保存 Claude 预设</button>
                    <button className="btn btn-ghost" disabled={ccApplyBusy} onClick={() => saveAsPresetCC("codex")}>＋ 保存 Codex 预设</button>
                    <div style={{display:"flex", gap:6}}>
                      <button className="btn btn-primary" disabled={ccApplyBusy || ccLoading.claude} onClick={() => applyCC("claude")}>
                        {ccLoading.claude && <span className="spin"></span>}应用 Claude
                      </button>
                      <button className="btn btn-primary" disabled={ccApplyBusy || ccLoading.codex} onClick={() => applyCC("codex")}>
                        {ccLoading.codex && <span className="spin"></span>}应用 Codex
                      </button>
                    </div>
                  </div>
                </div>

                {/* ======================================================
                 * A+ 扩展：展开式内联配置编辑（Claude 左 + Codex 右两列）
                 * ====================================================== */}
                {ccConfigOpen && (
                  <div className="ccconfig">
                    {(["claude", "codex"] as CCAppType[]).map(t => (
                      <div key={t}>
                        <h5 style={{margin:"0 0 10px", paddingBottom:6, borderBottom:"1px dashed var(--line)", fontSize:11, fontWeight:700, letterSpacing:".5px"}}>
                          <span className={t === "claude" ? "n-c" : "n-x"} style={{color: t === "claude" ? "#f472b6" : "#a78bfa"}}>
                            {t === "claude" ? "🤖 Claude 配置" : "⚙️ Codex 配置"}
                          </span>
                          <span className={`src ${ccSourceBadge[t] === "aivyos-manual" ? "aivy" : "cc"}`}
                                style={{fontSize:9, fontWeight:500, padding:"2px 7px", borderRadius:4,
                                         background: ccSourceBadge[t] === "aivyos-manual" ? "rgba(16,185,129,0.15)" : "rgba(59,130,246,0.15)",
                                         color: ccSourceBadge[t] === "aivyos-manual" ? "#34d399" : "#60a5fa"}}>
                            当前来源：{ccSourceBadge[t] || "—"}
                          </span>
                        </h5>
                        <div className="cc-field">
                          <label>Base URL<span className="hint">{t === "claude" ? "ANTHROPIC_BASE_URL" : "OPENAI_API_BASE"}</span></label>
                          <input
                            type="text"
                            value={ccForm[t].base_url}
                            placeholder={t === "claude" ? "https://api.anthropic.com 或 http://127.0.0.1:11434/v1" : "http://127.0.0.1:11434/v1"}
                            onChange={(e) => setCcForm(p => ({ ...p, [t]: { ...p[t], base_url: e.target.value }}))}
                          />
                        </div>
                        <div className="cc-row-2">
                          <div className="cc-field">
                            <label>模型名<span className="hint">{t === "claude" ? "ANTHROPIC_MODEL" : "OPENAI_MODEL"}</span></label>
                            <input type="text" value={ccForm[t].model} placeholder="qwen2.5:7b / claude-3-5-sonnet 等"
                                   onChange={(e) => setCcForm(p => ({ ...p, [t]: { ...p[t], model: e.target.value }}))} />
                          </div>
                          <div className="cc-field">
                            <label>&nbsp;</label>
                            <button className="btn btn-warn" style={{padding:"5px 0", justifyContent:"center", width:"100%"}}
                                    onClick={() => pingCC(t)} disabled={ccLoading[t]}>探测</button>
                          </div>
                        </div>
                        <div className="cc-field">
                          <label>API Key<span className="hint">Ollama 可填任意非空串，如 ollama</span></label>
                          <input type="password" value={ccForm[t].api_key}
                                 placeholder="sk-..."
                                 onChange={(e) => setCcForm(p => ({ ...p, [t]: { ...p[t], api_key: e.target.value }}))} />
                        </div>
                        <div className="cc-toggle" style={{marginTop:4}}>
                          <div className={`sw ${ccForm[t].override ? "on" : ""}`}
                               onClick={() => toggleOverride(t, !ccForm[t].override)}></div>
                          <span onClick={() => toggleOverride(t, !ccForm[t].override)}>
                            覆盖 cc-switch 激活项（{ccForm[t].override ? "开：AivyOS 手动优先" : "关：只用 cc-switch"}）
                          </span>
                        </div>
                        <div className="cc-hint">
                          开启后：<b>AivyOS 手动配置优先</b>（不修改 cc-switch.db 文件本身）；<br/>
                          Ollama：<b>Base URL 必须只填到 /v1</b>（不要写 /v1/chat/completions）。
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* ======================================================
                 * A+B 融合布局：左 aside（方案 B 常驻列表+详情） + 右主区（任务输入+步骤输出）
                 * ====================================================== */}
                <div className="wb-layout">
                  {/* ---------- 左侧：方案 B 常驻面板 ---------- */}
                  <aside className="cc-aside">
                    {(["claude", "codex"] as CCAppType[]).map((t, idx) => (
                      <React.Fragment key={t}>
                        <div>
                          <h5>
                            <span className={t === "claude" ? "n-c" : "n-x"}>
                              {t === "claude" ? "🤖 Claude Provider" : "⚙️ Codex Provider"}
                            </span>
                            <span className={`src ${ccSourceBadge[t] === "aivyos-manual" ? "aivy" : "cc"}`}>
                              {ccSourceBadge[t] || "未配置"}
                            </span>
                          </h5>

                          <div className="provider-list">
                            {ccProviders[t].length === 0 && (
                              <div style={{fontSize:11, color:"var(--muted2)", padding:"6px 8px"}}>
                                暂无 Provider：请先在上方保存 AivyOS 手动配置，或安装 cc-switch 桌面版。
                              </div>
                            )}
                            {ccProviders[t].map(p => (
                              <div
                                key={p.id}
                                className={`provider-row ${ccActiveId[t] === p.id ? "active" : ""} ${p.is_effective ? "effective" : ""}`}
                                onClick={() => onSelectProvider(t, p.id)}
                                title={`${p.name} · ${p.base_url}`}
                              >
                                <div className="radio"></div>
                                <div className="pi-meta">
                                  <div className="pi-name">{p.name}</div>
                                  <div className="pi-sub">
                                    {p.model} · {p.base_url_display || p.base_url}
                                  </div>
                                </div>
                                <span className={`pi-tag ${p.source === "aivyos-manual" ? "aivy" : p.source === "preset" ? "ps" : "cc"}`}>
                                  {p.source === "aivyos-manual" ? "AivyOS" : p.source === "preset" ? "预设" : "cc-s"}
                                </span>
                              </div>
                            ))}
                          </div>

                          <div className="cc-field">
                            <label>名称</label>
                            <input type="text" value={ccForm[t].name}
                                   onChange={(e) => setCcForm(p => ({ ...p, [t]: { ...p[t], name: e.target.value }}))} />
                          </div>
                          <div className="cc-field">
                            <label>Base URL<span className="hint">http(s) 前缀</span></label>
                            <input type="text" value={ccForm[t].base_url}
                                   onChange={(e) => setCcForm(p => ({ ...p, [t]: { ...p[t], base_url: e.target.value }}))} />
                          </div>
                          <div className="cc-field">
                            <label>模型名</label>
                            <input type="text" value={ccForm[t].model}
                                   onChange={(e) => setCcForm(p => ({ ...p, [t]: { ...p[t], model: e.target.value }}))} />
                          </div>
                          <div className="cc-field">
                            <label>API Key<span className="hint">不回显真实值</span></label>
                            <input type="password" value={ccForm[t].api_key}
                                   onChange={(e) => setCcForm(p => ({ ...p, [t]: { ...p[t], api_key: e.target.value }}))} />
                          </div>
                          <div className="cc-toggle" style={{margin:"4px 0 8px"}}>
                            <div className={`sw ${ccForm[t].override ? "on" : ""}`}
                                 onClick={() => toggleOverride(t, !ccForm[t].override)}></div>
                            <span onClick={() => toggleOverride(t, !ccForm[t].override)}>
                              AivyOS 手动 {ccForm[t].override ? "生效中" : "未启用"}
                            </span>
                          </div>
                          <div style={{display:"flex", gap:6, marginTop:4}}>
                            <button className="btn btn-primary" style={{padding:"5px 8px", fontSize:11}}
                                    disabled={ccApplyBusy || ccLoading[t]}
                                    onClick={() => applyCC(t)}>
                              {ccLoading[t] && <span className="spin"></span>}保存 & 应用
                            </button>
                            <button className="btn btn-warn"  style={{padding:"5px 8px", fontSize:11}}
                                    disabled={ccLoading[t]} onClick={() => pingCC(t)}>❤ 健康</button>
                          </div>
                        </div>
                        {idx === 0 && <div className="cc-split"></div>}
                      </React.Fragment>
                    ))}
                  </aside>

                  {/* ---------- 右侧：任务输入 + 工作目录 + 模式按钮 + 步骤输出 ---------- */}
                  {/* 将原有的 ta + 模式按钮 + 步骤卡片整体包裹在这里 */}
                  <div>
                    {/* ==== 原有 workbench 主区内容保持原样搬入此处 ==== */}
                    {/* 工作目录输入 */}
                    <div style={{marginBottom:8, display:"flex", alignItems:"center", gap:8}}>
                      <span style={{fontSize:11, color:"var(--muted2)"}}>工作目录（可选，如 F:\project）：</span>
                      <input style={{flex:1, background:"var(--bg-2)", border:"1px solid var(--line)",
                                    borderRadius:6, color:"var(--text)", padding:"5px 9px", fontSize:12}}
                             value={wbCwd}
                             placeholder="默认用当前工作区"
                             onChange={e => setWbCwd(e.target.value)} />
                    </div>

                    <textarea className="ta"
                              rows={5}
                              value={wbPrompt}
                              placeholder={wbMode === "doc"
                                ? "描述要设计的 API（如：用户登录/注册接口，支持邮箱验证码 + OAuth）"
                                : "描述需求（如：写一个天气网页，用 React + Tailwind + 逐小时图表）"}
                              onChange={e => setWbPrompt(e.target.value)} />

                    <div className="run-row" style={{display:"flex", gap:6, marginTop:8, alignItems:"center", flexWrap:"wrap"}}>
                      <div style={{display:"inline-flex", background:"var(--bg-2)", border:"1px solid var(--line)", borderRadius:6, overflow:"hidden"}}>
                        {(Object.keys(WB_TEMPLATES) as Array<keyof typeof WB_TEMPLATES>).map(k => (
                          <span key={k}
                                className={wbMode === k ? "on" : ""}
                                onClick={() => setWbMode(k)}
                                style={{padding:"4px 11px", fontSize:11, color: wbMode === k ? "#fff" : "var(--muted2)",
                                        background: wbMode === k ? "linear-gradient(90deg, var(--accent), var(--accent-2))" : "transparent",
                                        cursor:"pointer",
                                        borderRight:"1px solid var(--line)"}}>
                            {WB_TEMPLATES[k].name}
                          </span>
                        ))}
                        <span onClick={() => runWBDiff()}
                              style={{padding:"4px 11px", fontSize:11,
                                      color: wbMode === "__diff__" ? "#fff" : "var(--muted2)",
                                      background: wbMode === "__diff__"
                                        ? "linear-gradient(90deg, var(--accent), var(--accent-2))" : "transparent",
                                      cursor:"pointer"}}>
                          Diff 审查
                        </span>
                      </div>
                      <div style={{flex:1}}></div>
                      <button className="btn btn-primary" onClick={() => runWB()} disabled={wbRunning}>
                        {wbRunning ? <span className="spin"></span> : ""}
                        {wbRunning ? "贾维斯调度执行中（双模型可能耗时数分钟）..." : "▶ 交给贾维斯执行"}
                      </button>
                      <button className="btn btn-ghost" onClick={() => runWBVSCode()}>在 VS Code 打开</button>
                    </div>

                    {/* 原有步骤卡片 wbSteps 仍然保留 */}
                    {wbSteps.map((st, i) => (
                      <div className="step" key={i} style={{marginTop:10}}>
                        <div className="head" style={{display:"flex", justifyContent:"space-between"}}>
                          <span style={{fontSize:12, fontWeight:700}}>
                            {st.status === "done" ? "✅" : st.status === "running" ? "⏳" : st.status === "error" ? "❌" : "📋"}
                            {" "}步骤 {i+1}：{st.name}
                          </span>
                          <span style={{fontSize:10, color:"var(--muted2)"}}>
                            {st.duration_ms ? `${(st.duration_ms/1000).toFixed(2)}s` : ""}
                          </span>
                        </div>
                        {st.files_created && st.files_created.length > 0 && (
                          <div className="files-out" style={{marginTop:4}}>
                            📁 贾维斯产出文件：{st.files_created.join("、")}
                          </div>
                        )}
                        {st.output && (
                          <pre style={{whiteSpace:"pre-wrap", wordBreak:"break-word",
                                      maxHeight:160, overflow:"auto",
                                      fontSize:11, color:"var(--muted2)",
                                      background:"var(--bg-3)", border:"1px solid var(--line)",
                                      borderRadius:6, padding:8, marginTop:4}}>
                            {st.output}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {/* 贾维斯系统状态展示卡片（右侧主区内部底部，仍保留旧的 infocard 设计） */}
                {wbStatus && (
                  <div style={{display:"grid", gridTemplateColumns:"repeat(4, 1fr)", gap:10, marginTop:14}}>
                    <div className="infocard" style={{background:"var(--bg-2)", border:"1px solid var(--line)", borderRadius:8, padding:10, fontSize:11}}>
                      <div style={{display:"flex", justifyContent:"space-between"}}>
                        <span style={{color:"var(--muted2)"}}>Claude</span>
                        <span style={{color: wbStatus.claude?.available ? "#34d399" : "#94a3b8", fontWeight:700}}>
                          {wbStatus.claude?.available ? "✔ 就绪" : "✖ 未配置"}
                        </span>
                      </div>
                    </div>
                    <div className="infocard" style={{background:"var(--bg-2)", border:"1px solid var(--line)", borderRadius:8, padding:10, fontSize:11}}>
                      <div style={{display:"flex", justifyContent:"space-between"}}>
                        <span style={{color:"var(--muted2)"}}>Codex</span>
                        <span style={{color: wbStatus.codex?.available ? "#34d399" : "#94a3b8", fontWeight:700}}>
                          {wbStatus.codex?.available ? "✔ 就绪" : "✖ 未配置"}
                        </span>
                      </div>
                    </div>
                    <div className="infocard" style={{background:"var(--bg-2)", border:"1px solid var(--line)", borderRadius:8, padding:10, fontSize:11}}>
                      <div style={{display:"flex", justifyContent:"space-between"}}>
                        <span style={{color:"var(--muted2)"}}>手动覆盖</span>
                        <span style={{fontWeight:700,
                                     color: (ccSourceBadge.claude === "aivyos-manual" || ccSourceBadge.codex === "aivyos-manual") ? "#34d399" : "#94a3b8"}}>
                          {ccSourceBadge.claude === "aivyos-manual" || ccSourceBadge.codex === "aivyos-manual" ? "部分启用" : "未启用"}
                        </span>
                      </div>
                    </div>
                    <div className="infocard" style={{background:"var(--bg-2)", border:"1px solid var(--line)", borderRadius:8, padding:10, fontSize:11}}>
                      <div style={{display:"flex", justifyContent:"space-between"}}>
                        <span style={{color:"var(--muted2)"}}>作业报告</span>
                        <span style={{fontWeight:700, color:"#a78bfa"}}>设计就绪</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
```

**注意**：
- 如果原有的 `wbSteps`、`runWB()`、`runWBDiff()`、`runWBVSCode()` 等变量/函数名与上面 JSX 中使用的不一致，保留原有的名字和实现，**只改外层 HTML 结构**，不破坏既有执行逻辑。
- 所有 `cc-*` class 名已经在 Task 4 中写好了 styles.css 样式定义。

---

## Task 6: 端到端冒烟 + 回归测试 + 进度登记

- [ ] **Step 1: 后端全量回归**

```powershell
cd f:\AivyOS\aivyos
chcp 65001 > $null
python -m unittest discover -s tests -v 2>&1 | Select-Object -Last 20
```
期望：新增 `tests.test_provider_store` 全部通过；原有的 94 条通过；不新增回归错误。

- [ ] **Step 2: 前端类型检查**

```powershell
cd f:\AivyOS\aivyos\shell
npx tsc --noEmit 2>&1 | Select-Object -First 60
```
期望：App.tsx 不引入新的 TS 错误。

- [ ] **Step 3: 更新说明文档.md 进度表**

在 `f:\AivyOS\aivyos\说明文档.md` 的「§三 进度记录」表格追加以下 6 行（根据实际结果填写耗时/结果）：

| 日期 | 任务 ID | 内容 | 状态 | 结果说明 |
|---|---|---|---|---|
| 2026-08-25 | AIVY-CCSW-001-T1 | ProviderStore 合并 cc-switch + AivyOS manual（纯数据层） | ⏳ | 计划：10 tests + 单文件 ProviderStore（约 500 行） |
| 2026-08-25 | AIVY-CCSW-001-T2 | WorkbenchService 暴露 6 个 public 方法 + 健康检查 | ⏳ | ⏳ |
| 2026-08-25 | AIVY-CCSW-001-T3 | 注册 Bridge 命令（server_entry.py + chat.ts DTO） | ⏳ | ⏳ |
| 2026-08-25 | AIVY-CCSW-001-T4 | styles.css 新增 cctop / cc-aside 融合样式 | ⏳ | ⏳ |
| 2026-08-25 | AIVY-CCSW-001-T5 | App.tsx A+B 双向联动 UI | ⏳ | ⏳ |
| 2026-08-25 | AIVY-CCSW-001-T6 | 端到端冒烟 + 回归 + 进度登记 | ⏳ | ⏳ |

---

## Self-Review（已按 writing-plans 要求运行）

### Spec coverage 核对（用户原始需求 8 条）

| 用户需求点 | 对应 Task |
|---|---|
| ① UI 合理布局 cc-switch 组件 | Task 4 (styles) + Task 5 (JSX)：顶部 cctop + 左侧 cc-aside 双布局；小屏幕 <900px 自动堆叠为单列 |
| ② 视觉呈现与整体界面一致 | Task 4 全部用 var(--bg-2)/--accent/--line，零硬编码 RGB 以外的新颜色系统 |
| ③ cc-switch 状态切换逻辑 → 反映当前选中 Provider | Task 5：`ccActiveId` 双向绑定下拉 + 侧边选中；`is_effective` 绿点标记 |
| ④ 与模型管理系统交互：触发加载/切换/资源释放 | Task 1-2：ProviderStore `resolve_credentials()` 为唯一真源；`_prepare_env_for_cli` 改造后，Dispatcher 每次执行都读取最新值，实现无状态切换，不需要显式"释放" |
| ⑤ 状态提示 + 加载反馈 | Task 5：`.pill.warn` / `.pill.err` / `.ok-inline` / `.spin-inline` / `.spinner` 五种状态；应用后 3.8s 自动消失 |
| ⑥ 切换稳定性：不崩溃、不丢草稿 | Task 1 ProviderStore：原子写（config.tmp → os.replace）；Task 5：`ccForm` 草稿保留内存不随 reload 清空 key 字段 |
| ⑦ 数据一致性：表单 ↔ 下拉 ↔ 侧边 ↔ bridge 同步 | Task 5 `onSelectProvider()` / `loadCCProviders()` 两处同步入口，全部修改同一 `ccForm/ccActiveId` 记录 |
| ⑧ 贾维斯 = 调度主体，不把 Claude/Codex 当主体（角色架构） | App.tsx 标题改为"贾维斯调度台 — 驱动 Claude · Codex 双模型完成任务"，执行按钮改为"▶ 交给贾维斯执行"，产出标记"贾维斯产出文件" |

### Placeholder 扫描：全文没有"TBD/TODO/implement later/similar to Task N"

### Type 一致性：Task 3 chat.ts 中定义的 DTO 名（`WorkbenchProviderItem` 等）在 Task 1 返回值 / Task 2 service 方法 / Task 5 App.tsx 中完全一致。`WorkbenchSaveResultDto.ok` 为 `boolean`、`error_message` 为 `string`，两端对齐。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-24-cc-switch-ab-integration.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per Task (6 个子任务: Task1 ProviderStore / Task2 WorkbenchService / Task3 Bridge / Task4 Styles / Task5 App.tsx / Task6 E2E)，每完成一个 task 我 review，节奏快且每个子任务产出可独立验证的单文件 + tests 通过。

**2. Inline Execution** — 我在当前会话按 Task 1 → Task 6 顺序执行，每完成 2 个 task 做一次 checkpoint（跑单测 + 进度更新 说明文档.md）。

**Which approach do you want?**
