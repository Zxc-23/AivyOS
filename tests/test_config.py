"""配置系统测试。"""

import os
import unittest

from aivyos_core.config import DEFAULT_CONFIG, deep_merge, ensure_home, load_config

from tests import _TMP, AivyTestCase


class TestConfig(AivyTestCase):
    def test_defaults_present(self):
        cfg = load_config()
        self.assertEqual(cfg["llm"]["mode"], "auto")
        self.assertIn("local", cfg["llm"])
        self.assertIn("persona", cfg)
        self.assertIn("ipc", cfg)

    def test_deep_merge(self):
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        over = {"a": {"c": 9}, "e": 4}
        out = deep_merge(base, over)
        self.assertEqual(out["a"], {"b": 1, "c": 9})
        self.assertEqual(out["d"], 3)
        self.assertEqual(out["e"], 4)
        # 不修改原对象
        self.assertEqual(base["a"]["c"], 2)

    def test_env_override(self):
        os.environ["AIVYOS_LLM_MODE"] = "mock"
        try:
            cfg = load_config()
            self.assertEqual(cfg["llm"]["mode"], "mock")
        finally:
            del os.environ["AIVYOS_LLM_MODE"]

    def test_ensure_home_creates_dirs(self):
        cfg = load_config()
        cfg["home"] = os.path.join(_TMP, "home_test")
        home = ensure_home(cfg)
        self.assertTrue(home.exists())
        self.assertTrue((home / "sessions").exists())
        self.assertTrue((home / "memory").exists())
        self.assertTrue((home / "logs").exists())

    def test_default_home_env(self):
        os.environ["AIVYOS_HOME"] = os.path.join(_TMP, "env_home")
        try:
            cfg = load_config()
            self.assertTrue(cfg["home"].endswith("env_home"))
        finally:
            os.environ["AIVYOS_HOME"] = _TMP


if __name__ == "__main__":
    unittest.main()
