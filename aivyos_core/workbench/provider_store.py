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
