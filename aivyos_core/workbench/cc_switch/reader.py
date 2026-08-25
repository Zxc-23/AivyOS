"""cc-switch SQLite 读取器：读取当前激活 provider 的运行环境（只读）。

实测库结构（cc-switch 桌面版）：
- 表 providers(id, app_type, name, settings_config(JSON), is_current, ...)
- app_type: "claude" | "codex" | "gemini" | ...，每个 app_type 至多一行 is_current=1
- claude: settings_config.env = {ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN(或 ANTHROPIC_API_KEY), ANTHROPIC_MODEL, ...}
- codex:  settings_config.auth.OPENAI_API_KEY；base_url 埋在 settings_config.config 的 TOML 字符串里

读取原则（计划书 §2.3）：只读不写；任何异常/缺库/缺字段 → 返回 None（由上层降级）。
"""

from __future__ import annotations

import logging
log = logging.getLogger(__name__)

import json
import re
import sqlite3
import tomllib
from pathlib import Path
from typing import Any, Dict, Optional

from aivyos_core.workbench.models import ProviderEnv

_BASE_URL_RE = re.compile(r'base_url\s*=\s*"([^"]+)"')


def default_db_path() -> Path:
    return Path.home() / ".cc-switch" / "cc-switch.db"


class CCSwitchReader:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else default_db_path()

    def read_provider(self, app_type: str) -> Optional[ProviderEnv]:
        """读取指定 app_type 的激活 provider；失败一律返回 None。"""
        try:
            if not self.db_path.exists():
                return None
            # mode=ro：只读打开，绝不写 cc-switch 的库
            uri = f"file:{self.db_path.as_posix()}?mode=ro"
            db = sqlite3.connect(uri, uri=True)
            try:
                row = db.execute(
                    "SELECT name, settings_config FROM providers"
                    " WHERE app_type = ? AND is_current = 1 LIMIT 1",
                    (app_type,),
                ).fetchone()
                if row is None:  # 无激活行：取该类型任意一行兜底
                    row = db.execute(
                        "SELECT name, settings_config FROM providers"
                        " WHERE app_type = ? LIMIT 1",
                        (app_type,),
                    ).fetchone()
            finally:
                db.close()  # with 块只提交事务不关闭连接，Windows 下不关会锁文件
            if row is None:
                return None
            name, raw = row
            cfg = json.loads(raw)
            env = self._extract_env(app_type, cfg)
            if not env:
                return None
            return ProviderEnv(app_type=app_type, name=name or "", env=env, source="cc-switch")
        except Exception:
            return None

    @staticmethod
    def _extract_env(app_type: str, cfg: Dict[str, Any]) -> Dict[str, str]:
        if app_type == "claude":
            env = cfg.get("env")
            if not isinstance(env, dict):
                return {}
            out = {str(k): str(v) for k, v in env.items() if v}
            # 实测 cc-switch 写 ANTHROPIC_AUTH_TOKEN；老版本可能写 ANTHROPIC_API_KEY，两者都认
            if "ANTHROPIC_AUTH_TOKEN" not in out and out.get("ANTHROPIC_API_KEY"):
                out["ANTHROPIC_AUTH_TOKEN"] = out["ANTHROPIC_API_KEY"]
            return out
        if app_type == "codex":
            auth = cfg.get("auth")
            if not isinstance(auth, dict) or not auth.get("OPENAI_API_KEY"):
                return {}
            out = {"OPENAI_API_KEY": str(auth["OPENAI_API_KEY"])}
            base_url = _parse_codex_base_url(str(cfg.get("config", "")))
            if base_url:
                out["OPENAI_BASE_URL"] = base_url
            return out
        return {}


def _parse_codex_base_url(config_toml: str) -> Optional[str]:
    """从 codex 的 TOML 配置字符串中提取第一个 base_url；tomllib 失败回退正则。"""
    if not config_toml.strip():
        return None
    try:
        doc = tomllib.loads(config_toml)
        found = _find_key(doc, "base_url")
        if found:
            return found
    except Exception as e:
        log.debug("忽略预期内异常: %s", e, exc_info=True)
    m = _BASE_URL_RE.search(config_toml)
    return m.group(1) if m else None


def _find_key(node: Any, key: str) -> Optional[str]:
    if isinstance(node, dict):
        if isinstance(node.get(key), str):
            return node[key]
        for v in node.values():
            hit = _find_key(v, key)
            if hit:
                return hit
    elif isinstance(node, list):
        for item in node:
            hit = _find_key(item, key)
            if hit:
                return hit
    return None
