import json
import os
import tomllib
import unittest

from aivyos_core.config import DEFAULT_CONFIG
from tests import AivyTestCase


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "0.1.2"


class TestTauriReleaseConfig(AivyTestCase):
    def test_release_versions_are_aligned(self):
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            python_project = tomllib.load(f)
        with open(os.path.join(ROOT, "shell", "package.json"), encoding="utf-8") as f:
            package = json.load(f)
        with open(os.path.join(ROOT, "shell", "package-lock.json"), encoding="utf-8") as f:
            package_lock = json.load(f)
        with open(os.path.join(ROOT, "shell", "src-tauri", "Cargo.toml"), "rb") as f:
            cargo = tomllib.load(f)
        with open(os.path.join(ROOT, "shell", "src-tauri", "tauri.conf.json"), encoding="utf-8") as f:
            tauri = json.load(f)

        self.assertEqual(python_project["project"]["version"], VERSION)
        self.assertEqual(package["version"], VERSION)
        self.assertEqual(package_lock["version"], VERSION)
        self.assertEqual(package_lock["packages"][""]["version"], VERSION)
        self.assertEqual(cargo["package"]["version"], VERSION)
        self.assertEqual(tauri["version"], VERSION)
        self.assertEqual(DEFAULT_CONFIG["update"]["current_version"], VERSION)

    def test_native_updater_artifacts_remain_enabled(self):
        with open(os.path.join(ROOT, "shell", "src-tauri", "tauri.conf.json"), encoding="utf-8") as f:
            tauri = json.load(f)

        updater = tauri["plugins"]["updater"]
        self.assertTrue(updater["endpoints"])
        self.assertTrue(updater["pubkey"])
        self.assertIn("nsis", tauri["bundle"]["targets"])
        self.assertTrue(tauri["bundle"]["createUpdaterArtifacts"])


if __name__ == "__main__":
    unittest.main()
