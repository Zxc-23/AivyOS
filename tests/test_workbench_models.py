"""Workbench 数据模型测试：序列化与脱敏。"""

import json
import unittest

from tests import AivyTestCase
from aivyos_core.workbench.models import AgentResult, AgentTask, ProviderEnv


class TestWorkbenchModels(AivyTestCase):
    def test_agent_result_to_dict_roundtrip(self):
        """to_dict 包含全部关键字段且可 JSON 序列化。"""
        r = AgentResult(agent="claude", ok=True, output="done", exit_code=0,
                        elapsed_s=1.234, output_files=["a.py"])
        d = r.to_dict()
        json.dumps(d, ensure_ascii=False)  # 不抛异常即可
        self.assertEqual(d["agent"], "claude")
        self.assertEqual(d["output_files"], ["a.py"])
        self.assertEqual(d["elapsed_s"], 1.23)

    def test_provider_env_safe_dict_strips_secrets(self):
        """to_safe_dict：机密值替换为 ***，非机密保留。"""
        penv = ProviderEnv(
            app_type="claude", name="Kimi",
            env={"ANTHROPIC_AUTH_TOKEN": "secret-tok", "ANTHROPIC_BASE_URL": "https://x"},
        )
        safe = penv.to_safe_dict()
        self.assertEqual(safe["env"]["ANTHROPIC_AUTH_TOKEN"], "***")
        self.assertEqual(safe["env"]["ANTHROPIC_BASE_URL"], "https://x")
        self.assertNotIn("secret-tok", json.dumps(safe))

    def test_task_defaults(self):
        """AgentTask 默认：300s 超时、无额外参数。"""
        t = AgentTask(agent="codex", prompt="hi")
        self.assertEqual(t.timeout_s, 300.0)
        self.assertEqual(t.extra_args, [])
        self.assertIsNone(t.cwd)


if __name__ == "__main__":
    unittest.main()
