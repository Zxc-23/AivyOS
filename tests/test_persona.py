"""人格系统测试（文档 §4.3）。"""

import unittest

from aivyos_core.persona import PERSONA_TEMPLATE, Persona
from aivyos_core.roles import AGENT_ROLE_DEFINITION

from tests import AivyTestCase


class TestPersona(AivyTestCase):
    def test_render_system_prompt(self):
        """System Prompt 需包含贾维斯（资源调度+任务执行）与用户（任务发布者）的完整角色定义。

        2026-08-24 架构锁定后：
          - 贾维斯 = 整个 AivyOS 系统的【资源调度者】与【任务执行者】
          - 用户   = 【任务发布者】
          - 必须附带汇报证据链的行为准则（不能只说"已完成"）
        """
        p = Persona(name="贾维斯", tone="professional", user_alias="先生")
        prompt = p.render_system_prompt()
        # 标题声明：贾维斯（Jarvis）身份
        self.assertIn("你是 贾维斯（Jarvis），用户指定的 AI 助手", prompt)
        # 角色定位双段式
        self.assertIn("【资源调度者】", prompt)
        self.assertIn("【任务执行者】", prompt)
        self.assertIn("【任务发布者】", prompt)
        # 角色总定义引用来自 roles.py 的 AGENT_ROLE_DEFINITION 文本
        for keyword in ("资源调度者", "任务执行者", "Claude", "Codex"):
            self.assertIn(
                keyword, AGENT_ROLE_DEFINITION,
                f"AGENT_ROLE_DEFINITION 缺少关键词 '{keyword}'，需要同步 roles.py 与测试",
            )
        self.assertIn(AGENT_ROLE_DEFINITION, prompt)
        # Big Five / 交互风格结构仍然保留
        self.assertIn("开放性: 0.8 / 1.0", prompt)
        self.assertIn("语气: professional", prompt)
        self.assertIn("称呼用户为: 先生", prompt)
        self.assertIn("回复长度: balanced", prompt)
        self.assertIn("语言: zh-CN", prompt)
        # 行为准则 4：证据链汇报硬性要求
        self.assertIn("证据链", prompt)
        self.assertIn("关键变更点摘要", prompt)

    def test_update_valid(self):
        p = Persona()
        self.assertTrue(p.update("openness", 0.95))
        self.assertEqual(p.openness, 0.95)
        self.assertTrue(p.update("tone", "casual"))
        self.assertEqual(p.tone, "casual")
        self.assertTrue(p.update("user_alias", "老板"))

    def test_update_invalid(self):
        p = Persona()
        self.assertFalse(p.update("openness", 1.5))
        self.assertFalse(p.update("tone", "aggressive"))
        self.assertFalse(p.update("response_length", "huge"))
        self.assertFalse(p.update("nonexistent", 1))

    def test_from_config(self):
        p = Persona.from_config({"name": "X", "openness": 0.5, "extra_rules": ["规则1"]})
        self.assertEqual(p.name, "X")
        self.assertEqual(p.openness, 0.5)
        self.assertIn("规则1", p.render_system_prompt())

    def test_extra_rules_in_prompt(self):
        p = Persona(extra_rules=["不确定时先说不知道"])
        self.assertIn("不确定时先说不知道", p.render_system_prompt())


if __name__ == "__main__":
    unittest.main()
