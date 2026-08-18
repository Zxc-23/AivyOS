"""依赖检测脚本测试（scripts/check_deps.py）：结构完整性与 JSON 输出。"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests import AivyTestCase

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_deps.py"


class TestCheckDeps(AivyTestCase):
    def _run(self, *args):
        env = dict(__import__("os").environ)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, env=env,
        )

    def test_json_output_shape(self):
        r = self._run("--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("python", data)
        self.assertIn("groups", data)
        self.assertIn("tools", data)
        self.assertIn("ollama", data)
        self.assertIn("missing_pip_commands", data)
        # 组结构
        for g in data["groups"]:
            self.assertIn("name", g)
            self.assertIn("pip", g)
            self.assertIn("deps", g)
            for d in g["deps"]:
                self.assertIn("module", d)
                self.assertIn("ok", d)
                self.assertIsInstance(d["ok"], bool)
        # 工具结构
        for exe in ("node", "npm", "ollama", "gh"):
            self.assertIn(exe, data["tools"])

    def test_plain_output_contains_summary(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("汇总", r.stdout)
        self.assertIn("降级回退", r.stdout)

    def test_pywin32_expected_state(self):
        """pywin32 未装 → 其 pip 命令应出现在缺失汇总（当前环境预期未装）。"""
        import importlib.util

        if importlib.util.find_spec("win32file"):
            self.skipTest("pywin32 已安装，跳过")
        data = json.loads(self._run("--json").stdout)
        self.assertIn("pip install pywin32", data["missing_pip_commands"])


if __name__ == "__main__":
    unittest.main()
