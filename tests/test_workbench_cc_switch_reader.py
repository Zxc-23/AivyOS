"""cc-switch 读取器测试：临时 SQLite + 双键兼容 + TOML/正则解析。"""

import json
import os
import sqlite3
import unittest

from tests import AivyTestCase, _TMP
from aivyos_core.workbench.cc_switch.reader import CCSwitchReader


def _make_db(rows):
    """在测试目录建一个最小 cc-switch 库，返回路径。"""
    path = os.path.join(_TMP, "cc-switch-test.db")
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT,"
        " settings_config TEXT, is_current BOOLEAN)"
    )
    db.executemany(
        "INSERT INTO providers (id, app_type, name, settings_config, is_current)"
        " VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    db.commit()
    db.close()
    return path


class TestCCSwitchReader(AivyTestCase):
    def test_read_claude_env_auth_token(self):
        """claude provider：env 原样透传，含 ANTHROPIC_AUTH_TOKEN。"""
        cfg = {"env": {"ANTHROPIC_BASE_URL": "https://kimi.example", "ANTHROPIC_AUTH_TOKEN": "tok-1",
                       "ANTHROPIC_MODEL": "kimi-k2"}}
        path = _make_db([("1", "claude", "Kimi", json.dumps(cfg), 1)])
        penv = CCSwitchReader(path).read_provider("claude")
        self.assertIsNotNone(penv)
        self.assertEqual(penv.name, "Kimi")
        self.assertEqual(penv.env["ANTHROPIC_AUTH_TOKEN"], "tok-1")
        self.assertEqual(penv.env["ANTHROPIC_BASE_URL"], "https://kimi.example")
        self.assertEqual(penv.source, "cc-switch")

    def test_read_claude_api_key_alias(self):
        """老版本写 ANTHROPIC_API_KEY 时自动补出 ANTHROPIC_AUTH_TOKEN。"""
        cfg = {"env": {"ANTHROPIC_API_KEY": "tok-old", "ANTHROPIC_BASE_URL": "https://x"}}
        path = _make_db([("1", "claude", "Old", json.dumps(cfg), 1)])
        penv = CCSwitchReader(path).read_provider("claude")
        self.assertEqual(penv.env["ANTHROPIC_AUTH_TOKEN"], "tok-old")
        self.assertEqual(penv.env["ANTHROPIC_API_KEY"], "tok-old")

    def test_read_codex_toml_base_url(self):
        """codex provider：auth 取 key，base_url 从 TOML config 解析。"""
        toml_cfg = '[model_providers.kimi]\nbase_url = "https://kimi.example/v1"\n'
        cfg = {"auth": {"OPENAI_API_KEY": "ok-1"}, "config": toml_cfg}
        path = _make_db([("1", "codex", "Kimi", json.dumps(cfg), 1)])
        penv = CCSwitchReader(path).read_provider("codex")
        self.assertEqual(penv.env["OPENAI_API_KEY"], "ok-1")
        self.assertEqual(penv.env["OPENAI_BASE_URL"], "https://kimi.example/v1")

    def test_codex_base_url_regex_fallback(self):
        """config 不是合法 TOML 时回退正则提取 base_url。"""
        broken = 'base_url = "https://fallback.example"\n[broken'
        cfg = {"auth": {"OPENAI_API_KEY": "ok-2"}, "config": broken}
        path = _make_db([("1", "codex", "Kimi", json.dumps(cfg), 1)])
        penv = CCSwitchReader(path).read_provider("codex")
        self.assertEqual(penv.env["OPENAI_BASE_URL"], "https://fallback.example")

    def test_missing_db_returns_none(self):
        """库不存在 → None，不抛异常。"""
        reader = CCSwitchReader(os.path.join(_TMP, "no-such.db"))
        self.assertIsNone(reader.read_provider("claude"))
        self.assertIsNone(reader.read_provider("codex"))


if __name__ == "__main__":
    unittest.main()
