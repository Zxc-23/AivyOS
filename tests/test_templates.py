"""脚手架模板测试（§10.2 / T5.3）：7 种类型均产出真实可用的 stdlib 骨架。"""

import unittest

from aivyos_core.codegen.templates import TEMPLATES, list_templates, scaffold
from aivyos_core.requirement import ProjectSpec

from tests import AivyTestCase


class TestTemplates(AivyTestCase):
    def test_list_templates_7_types(self):
        names = list_templates()
        self.assertEqual(
            set(names),
            {"static-site", "react-web-app", "vue-web-app", "nextjs-app", "python-cli", "python-api", "tauri-desktop-app"},
        )

    def test_all_templates_have_files(self):
        for name in list_templates():
            self.assertIn(name, TEMPLATES)
            spec = ProjectSpec(type=name, title="测试项目")
            files = TEMPLATES[name](spec)
            self.assertTrue(files, name)
            for path, content in files.items():
                self.assertTrue(path, name)
                self.assertIsInstance(content, str)
                self.assertTrue(content.strip(), f"{name}:{path} 内容为空")

    def test_static_site_has_index_html(self):
        spec = ProjectSpec(type="static-site", title="我的网站")
        files = scaffold("static-site", spec)
        self.assertIn("index.html", files)
        self.assertIn("我的网站", files["index.html"])

    def test_python_cli_executable(self):
        spec = ProjectSpec(type="python-cli", title="rename-tool", features=["重命名"])
        files = scaffold("python-cli", spec)
        self.assertIn("main.py", files)
        # 骨架可直接 python 运行（零依赖）
        ns = {}
        exec(compile(files["main.py"], "main.py", "exec"), ns)  # noqa: S102
        self.assertTrue(callable(ns.get("main")))

    def test_python_api_has_main(self):
        files = scaffold("python-api", ProjectSpec(type="python-api", title="api"))
        self.assertIn("main.py", files)
        self.assertIn("app = FastAPI", files["main.py"])

    def test_react_web_app_skeleton(self):
        files = scaffold("react-web-app", ProjectSpec(type="react-web-app", title="博客"))
        for need in ("package.json", "src/App.jsx", "index.html"):
            self.assertIn(need, files, need)

    def test_scaffold_unknown_type_falls_back(self):
        files = scaffold("unknown-type", ProjectSpec(type="unknown-type", title="x"))
        self.assertTrue(files)


if __name__ == "__main__":
    unittest.main()
