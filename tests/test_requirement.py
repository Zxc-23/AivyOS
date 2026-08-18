"""需求解析引擎测试（§10.1 阶段1 / T5.2）：规则解析 + LLM 增强降级。"""

import asyncio
import unittest

from aivyos_core.requirement import TEMPLATE_KEYWORDS, ProjectSpec, RequirementParser

from tests import AivyTestCase


class TestRequirementParser(AivyTestCase):
    def setUp(self):
        self.parser = RequirementParser(router=None)  # 无 LLM：规则保底

    def test_detect_react_web_app(self):
        spec = self.parser.parse("帮我做一个个人博客网站，用 react 和 vite")
        self.assertEqual(spec.type, "react-web-app")
        self.assertIn("个人博客", spec.title)

    def test_detect_python_cli(self):
        spec = self.parser.parse("写一个批量重命名文件的命令行工具")
        self.assertEqual(spec.type, "python-cli")
        self.assertTrue(spec.target_dir)

    def test_detect_python_api(self):
        spec = self.parser.parse("做一个用户管理后端 API 服务")
        self.assertEqual(spec.type, "python-api")

    def test_detect_desktop(self):
        spec = self.parser.parse("开发一个带托盘的桌面应用")
        self.assertEqual(spec.type, "tauri-desktop-app")

    def test_default_static_site(self):
        spec = self.parser.parse("随便做个东西")
        self.assertEqual(spec.type, "static-site")
        self.assertEqual(spec.source, "rule")

    def test_features_split(self):
        spec = self.parser.parse("做一个天气查询网页，支持城市搜索和历史记录")
        self.assertTrue(spec.features)
        self.assertLessEqual(len(spec.features), 5)

    def test_to_dict_roundtrip(self):
        spec = self.parser.parse("写一个 cli 工具")
        d = spec.to_dict()
        self.assertEqual(d["type"], spec.type)
        self.assertEqual(d["title"], spec.title)

    def test_enhanced_without_llm_falls_back_to_rule(self):
        spec = asyncio.run(self.parser.parse_enhanced("做一个 python api 服务"))
        self.assertEqual(spec.type, "python-api")
        self.assertEqual(spec.source, "rule")  # 无 LLM → 纯规则

    def test_template_keywords_cover_7_types(self):
        self.assertEqual(
            set(TEMPLATE_KEYWORDS.keys()),
            {"react-web-app", "vue-web-app", "nextjs-app", "python-cli", "python-api", "static-site", "tauri-desktop-app"},
        )


class TestProjectSpec(AivyTestCase):
    def test_defaults(self):
        s = ProjectSpec()
        self.assertEqual(s.type, "static-site")
        self.assertEqual(s.title, "AivyApp")
        self.assertEqual(s.features, [])
        self.assertEqual(s.tech, [])


if __name__ == "__main__":
    unittest.main()
