"""更新服务接入层测试（§13）：UpdateService 封装 status/check/install/rollback。"""

import json
import os
import shutil
import subprocess
import sys
import threading
import unittest
import urllib.request

from tests import AivyTestCase


class _FakeHandler:
    """HTTP handler 工厂：返回固定 manifest。"""

    def __init__(self, signed_path):
        self.signed_path = signed_path

    def __call__(self, *args, **kwargs):
        import http.server

        signed_path = self.signed_path

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                try:
                    with open(signed_path, "rb") as f:
                        self.wfile.write(f.read())
                except Exception:
                    self.wfile.write(b'{"error": "no manifest"}')

            def log_message(self, *a):
                pass

        return H(*args, **kwargs)


class TestUpdateService(AivyTestCase):
    def _mk_home(self, tag):
        import uuid

        home = os.path.join(os.getcwd(), ".aivyos_test", f"upd_{tag}_{uuid.uuid4().hex[:6]}")
        os.makedirs(os.path.join(home, "pki"), exist_ok=True)
        return home

    def _sign_pkg(self, home, version, pkg_files):
        """用 UpdateService 的 PKI 密钥签名一个更新包。返回 (pkg_dir, signed_path)。"""
        from aivyos_core.config import load_config
        from aivyos_core.update.service import UpdateService

        svc = UpdateService(load_config(), home)
        svc._ensure_pki()
        pki_dir = os.path.join(home, "pki")

        pkg = os.path.join(home, "pkg_" + version.replace(".", "_"))
        os.makedirs(pkg, exist_ok=True)
        for name, content in pkg_files.items():
            with open(os.path.join(pkg, name), "w", encoding="utf-8") as f:
                f.write(content)

        out = os.path.join(home, "server_" + version.replace(".", "_"))
        os.makedirs(out, exist_ok=True)
        r = subprocess.run(
            [sys.executable, "scripts/sign_update.py", "--root", pkg, "--version", version,
             "--root-key", os.path.join(pki_dir, "root.seed"),
             "--intermediate-key", os.path.join(pki_dir, "intermediate.seed"),
             "--out", out],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        self.assertEqual(r.returncode, 0, f"sign_update 失败: {r.stderr[:300]}")
        return pkg, os.path.join(out, "manifest.signed.json")

    def _serve(self, signed_path):
        import http.server

        srv = http.server.HTTPServer(("127.0.0.1", 0), _FakeHandler(signed_path))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, srv.server_address[1]

    def test_status_initial(self):
        """status：初始状态（当前版本/空安装列表/never 检查）。"""
        from aivyos_core.config import load_config
        from aivyos_core.update.service import UpdateService

        home = self._mk_home("st")
        svc = UpdateService(load_config(), home)
        st = svc.status()
        self.assertTrue(st["ok"])
        self.assertEqual(st["current_version"], "0.1.0")
        self.assertEqual(st["installed_versions"], [])
        self.assertEqual(st["last_check_result"], "never")
        self.assertFalse(st["update_available"])

    def test_check_no_endpoint(self):
        """check：未配置更新源（github_repo 与 endpoint 都空）→ 诚实报错。"""
        from aivyos_core.config import load_config, deep_merge
        from aivyos_core.update.service import UpdateService

        home = self._mk_home("ne")
        cfg = deep_merge(load_config(), {"update": {"github_repo": "", "endpoint": ""}})
        svc = UpdateService(cfg, home)
        r = svc.check()
        self.assertFalse(r["ok"])
        self.assertIn("未配置", r["error"])

    def test_check_server_unreachable(self):
        """check：endpoint 服务器不可达 → 诚实报错（不假装有更新）。"""
        from aivyos_core.config import load_config, deep_merge
        from aivyos_core.update.service import UpdateService

        home = self._mk_home("un")
        cfg = deep_merge(load_config(), {
            "update": {
                "github_repo": "",
                "endpoint": "http://127.0.0.1:1/update/{target}/{arch}/{current_version}",
            }
        })
        svc = UpdateService(cfg, home)
        r = svc.check(timeout=2)
        self.assertFalse(r["ok"])
        self.assertIn("服务器不可达", r["error"])

    def test_full_install_and_rollback(self):
        """完整闭环：check(验签通过) → install → rollback。"""
        from aivyos_core.config import load_config, deep_merge
        from aivyos_core.update.service import UpdateService

        home = self._mk_home("full")
        # 先签名 v1.0.0（作为旧版本），再 v1.2.0（新版本）
        pkg_old, signed_old = self._sign_pkg(home, "1.0.0", {"core.py": "# old\n"})
        pkg_new, signed_new = self._sign_pkg(home, "1.2.0", {"core.py": "# new v1.2.0\n"})

        # 用 v1.0.0 作为"当前已安装"（直接 install 一次）
        srv_old, port_old = self._serve(signed_old)
        cfg = deep_merge(load_config(), {
            "update": {
                "github_repo": "",
                "endpoint": f"http://127.0.0.1:{port_old}/update/{{target}}/{{arch}}/{{current_version}}",
            }
        })
        svc = UpdateService(cfg, home)
        # 放包文件供验签（直接复制签名源，保证哈希一致）
        pending = os.path.join(home, ".update_pending")
        os.makedirs(pending, exist_ok=True)
        shutil.copy(os.path.join(pkg_old, "core.py"), os.path.join(pending, "core.py"))
        r = svc.check(timeout=5)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue(r["update_available"])
        inst = svc.install()
        self.assertTrue(inst["ok"], inst.get("error"))
        srv_old.shutdown()

        # 现在检查 v1.2.0 → 安装 → 回滚到 1.0.0
        srv_new, port_new = self._serve(signed_new)
        cfg2 = deep_merge(cfg, {"update": {"endpoint": f"http://127.0.0.1:{port_new}/update/{{target}}/{{arch}}/{{current_version}}"}})
        svc2 = UpdateService(cfg2, home)
        os.makedirs(pending, exist_ok=True)
        shutil.copy(os.path.join(pkg_new, "core.py"), os.path.join(pending, "core.py"))
        r2 = svc2.check(timeout=5)
        self.assertTrue(r2["ok"], r2.get("error"))
        self.assertEqual(r2["version"], "1.2.0")
        inst2 = svc2.install()
        self.assertTrue(inst2["ok"], inst2.get("error"))
        self.assertEqual(inst2["version"], "1.2.0")
        srv_new.shutdown()

        st = svc2.status()
        self.assertEqual(st["installed_versions"], ["1.2.0", "1.0.0"])
        self.assertEqual(st["active_version"], "1.2.0")

        rb = svc2.rollback()
        self.assertTrue(rb["ok"], rb.get("error"))
        self.assertEqual(rb["version"], "1.0.0")
        st2 = svc2.status()
        self.assertEqual(st2["active_version"], "1.0.0")

    def test_downgrade_rejected(self):
        """防降级：比当前版本低的更新被拒绝。"""
        from aivyos_core.config import load_config, deep_merge
        from aivyos_core.update.service import UpdateService

        home = self._mk_home("downgrade")
        _, signed = self._sign_pkg(home, "0.0.5", {"core.py": "# old\n"})
        srv, port = self._serve(signed)
        cfg = deep_merge(load_config(), {
            "update": {
                "github_repo": "",
                "endpoint": f"http://127.0.0.1:{port}/update/{{target}}/{{arch}}/{{current_version}}",
            }
        })
        svc = UpdateService(cfg, home)
        r = svc.check(timeout=5)
        self.assertFalse(r["ok"])
        self.assertIn("验证失败", r["error"])
        srv.shutdown()


class TestGitHubReleases(AivyTestCase):
    """GitHub Releases 更新源：publish → mock API → check → install。"""

    def _mk_home(self, tag):
        import uuid

        home = os.path.join(os.getcwd(), ".aivyos_test", f"updgh_{tag}_{uuid.uuid4().hex[:6]}")
        os.makedirs(os.path.join(home, "pki"), exist_ok=True)
        return home

    def _publish(self, home, version, pkg_files):
        """用 publish_update.py 生成签名 zip + manifest（复用 UpdateService 的 pki）。"""
        from aivyos_core.config import load_config
        from aivyos_core.update.service import UpdateService

        svc = UpdateService(load_config(), home)
        svc._ensure_pki()
        pki = os.path.join(home, "pki")
        pkg = os.path.join(home, "pkg")
        os.makedirs(pkg, exist_ok=True)
        for name, content in pkg_files.items():
            with open(os.path.join(pkg, name), "w", encoding="utf-8") as f:
                f.write(content)
        out = os.path.join(home, "out")
        r = subprocess.run(
            [sys.executable, "scripts/publish_update.py", "--root", pkg,
             "--version", version, "--out", out, "--pki", pki],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        self.assertEqual(r.returncode, 0, f"publish 失败: {r.stderr[:300]}")
        return os.path.join(out, f"aivyos-{version}.zip"), os.path.join(out, "signed", "manifest.signed.json")

    def test_github_check_install(self):
        """GitHub 源：mock API 返回 release → 下载 zip+manifest → 验签 → 安装。"""
        import http.server
        import uuid

        from aivyos_core.config import load_config, deep_merge
        from aivyos_core.update.service import UpdateService

        home = os.path.join(os.getcwd(), ".aivyos_test", "gh_" + uuid.uuid4().hex[:6])
        os.makedirs(home, exist_ok=True)
        zip_path, manifest_path = self._publish(home, "1.5.0", {"core.py": "# v1.5.0\n"})

        # mock GitHub API + asset 服务器
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if "/releases/latest" in self.path:
                    body = json.dumps({
                        "tag_name": "v1.5.0",
                        "assets": [
                            {"name": "aivyos-1.5.0.zip", "browser_download_url": f"http://127.0.0.1:{port}/assets/aivyos-1.5.0.zip"},
                            {"name": "manifest.signed.json", "browser_download_url": f"http://127.0.0.1:{port}/assets/manifest.signed.json"},
                        ],
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith("/assets/"):
                    name = self.path.split("/")[-1]
                    f = manifest_path if name == "manifest.signed.json" else zip_path
                    self.send_response(200)
                    self.end_headers()
                    with open(f, "rb") as fh:
                        self.wfile.write(fh.read())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        # 客户端：同一 pki，repo 指向本地 mock
        client_home = os.path.join(home, "client")
        os.makedirs(client_home, exist_ok=True)
        shutil.copytree(os.path.join(home, "pki"), os.path.join(client_home, "pki"))

        cfg = deep_merge(load_config(), {"update": {"github_repo": "mock/repo", "current_version": "0.1.0"}})
        svc = UpdateService(cfg, client_home)

        api_base = f"http://127.0.0.1:{port}"
        orig_json = UpdateService._download_json
        orig_bytes = UpdateService._download_bytes

        def fake_json(url, headers, timeout):
            return orig_json(url.replace("https://api.github.com", api_base), headers, timeout)

        def fake_bytes(url, headers, timeout):
            return orig_bytes(url.replace("https://api.github.com", api_base), headers, timeout)

        UpdateService._download_json = staticmethod(fake_json)
        UpdateService._download_bytes = staticmethod(fake_bytes)
        try:
            r = svc.check(timeout=5)
            self.assertTrue(r["ok"], r.get("error"))
            self.assertTrue(r["update_available"])
            self.assertEqual(r["version"], "1.5.0")
            inst = svc.install()
            self.assertTrue(inst["ok"], inst.get("error"))
            st = svc.status()
            self.assertIn("1.5.0", st["installed_versions"])
            self.assertEqual(st["active_version"], "1.5.0")
            self.assertIn("mock/repo", st["source"])
        finally:
            UpdateService._download_json = orig_json
            UpdateService._download_bytes = orig_bytes
            srv.shutdown()

    def test_github_no_release(self):
        """GitHub 源：仓库无 release → 诚实报错。"""
        from aivyos_core.config import load_config, deep_merge
        from aivyos_core.update.service import UpdateService

        home = self._mk_home("ghn")
        cfg = deep_merge(load_config(), {"update": {"github_repo": "nonexistent/repo"}})
        svc = UpdateService(cfg, home)
        r = svc.check(timeout=3)
        self.assertFalse(r["ok"])
        self.assertIn("GitHub", r["error"])


if __name__ == "__main__":
    unittest.main()
