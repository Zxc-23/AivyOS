"""人格系统测试（文档 §4.3）。"""

import unittest

from aivyos_core.persona import PERSONA_TEMPLATE, Persona

from tests import AivyTestCase


class TestPersona(AivyTestCase):
    def test_render_system_prompt(self):
        p = Persona(name="Aivy", tone="professional", user_alias="先生")
        prompt = p.render_system_prompt()
        self.assertIn("你是 Aivy，用户的私人AI助理", prompt)
        self.assertIn("开放性: 0.8 / 1.0", prompt)
        self.assertIn("语气: professional", prompt)
        self.assertIn("称呼用户为: 先生", prompt)
        self.assertIn("回复长度: balanced", prompt)
        self.assertIn("语言: zh-CN", prompt)

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
