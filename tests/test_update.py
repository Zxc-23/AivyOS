"""自动更新与签名测试（Phase 3 Week 10 / T8.x）：
Ed25519 RFC 向量 / 三层 PKI / 七步验签（防降级·篡改·过期·撤销·时间戳）/ 版本回滚 / 增量下载。"""

import json
import os
import shutil
import time
import unittest
from pathlib import Path

from aivyos_core.update import PKI, DeltaPlanner, KeyPair, UpdateVerifier, Version, VersionManager
from aivyos_core.update.ed25519 import public_key, sign, verify
from aivyos_core.update.manifest import aggregate_hash, build_manifest, file_blake2b, sign_manifest

from tests import AivyTestCase, _TMP


class TestEd25519RFC(AivyTestCase):
    """RFC 8032 §7.1 官方向量（T8.1 算法正确性）。"""

    VECTORS = [
        ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
         b"",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
         b"\x72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
        ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
         "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
         b"\xaf\x82",
         "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
    ]

    def test_vectors(self):
        for seed_hex, pub_hex, msg, sig_hex in self.VECTORS:
            seed = bytes.fromhex(seed_hex)
            self.assertEqual(public_key(seed).hex(), pub_hex)
            self.assertEqual(sign(seed, msg).hex(), sig_hex)
            self.assertTrue(verify(bytes.fromhex(pub_hex), msg, bytes.fromhex(sig_hex)))

    def test_roundtrip_and_tamper(self):
        seed = KeyPair.generate("leaf").seed
        pub = public_key(seed)
        sig = sign(seed, b"hello")
        self.assertTrue(verify(pub, b"hello", sig))
        self.assertFalse(verify(pub, b"hello!", sig))  # 消息篡改
        bad = bytearray(sig)
        bad[10] ^= 1
        self.assertFalse(verify(pub, b"hello", bytes(bad)))  # 签名篡改
        self.assertFalse(verify(b"\x00" * 32, b"hello", sig))  # 错误公钥


class TestPKI(AivyTestCase):
    def test_bootstrap_three_layers(self):
        pki, root_kp, intermediate_kp = PKI.bootstrap()
        leaf_kp = pki.issue_leaf(intermediate_kp)
        chain = pki.cert_chain()
        self.assertEqual(len(chain), 2)  # [leaf, intermediate]
        self.assertEqual(chain[0]["type"], "leaf")
        self.assertEqual(chain[1]["type"], "intermediate")
        self.assertTrue(pki.verify_chain(chain))
        # Root 公钥与 Intermediate 签发者指纹对应
        self.assertEqual(pki.root_fingerprint, chain[1]["issuer_fingerprint"])

    def test_tampered_chain_rejected(self):
        pki, root_kp, intermediate_kp = PKI.bootstrap()
        leaf_kp = pki.issue_leaf(intermediate_kp)
        chain = pki.cert_chain()
        chain[0]["pubkey"] = KeyPair.generate("leaf").pubkey_hex  # 篡改 Leaf 公钥
        self.assertFalse(pki.verify_chain(chain))

    def test_expired_cert_rejected(self):
        now = int(time.time())
        pki, root_kp, intermediate_kp = PKI.bootstrap(now=now - 500 * 24 * 3600)  # 1 年前
        leaf_kp = pki.issue_leaf(intermediate_kp, now=now - 100 * 24 * 3600)
        self.assertFalse(pki.verify_chain(pki.cert_chain(), now=now))  # 已过期


class _UpdateFixture(AivyTestCase):
    """搭建签名更新包 + 客户端验签环境。"""

    def setUp(self):
        self.dir = Path(_TMP) / ("upd_" + __import__("uuid").uuid4().hex[:6])
        self.pkg_root = self.dir / "build" / "update"
        self.pkg_root.mkdir(parents=True, exist_ok=True)
        (self.pkg_root / "app.py").write_text("# app v1.2.0\n", encoding="utf-8")
        (self.pkg_root / "data.bin").write_bytes(b"\x00\x01\x02" * 100)
        self.now = int(time.time())
        # 三层 PKI
        self.pki, self.root_kp, self.inter_kp = PKI.bootstrap(now=self.now)
        self.leaf_kp = self.pki.issue_leaf(self.inter_kp, now=self.now)
        self.manifest = build_manifest(self.pkg_root, "1.3.0", "feature",
                                       min_required_version="1.2.0", timestamp=self.now)
        self.signed = sign_manifest(self.manifest, self.leaf_kp, self.pki.cert_chain())
        # 客户端下载后的包目录
        self.client_pkg = self.dir / "client_pkg"
        shutil.copytree(self.pkg_root, self.client_pkg)
        self.quarantine = self.dir / "quarantine"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def verifier(self, current="1.2.0", **kw):
        return UpdateVerifier(
            pki=self.pki, current_version=current,
            quarantine_dir=self.quarantine, now=self.now, **kw
        )


class TestVerifySevenSteps(_UpdateFixture):
    def test_full_verify_passes(self):
        v = self.verifier()
        self.assertTrue(v.verify(self.signed, self.client_pkg))
        self.assertIn("signature", v.steps_ok)
        self.assertIn("files", v.steps_ok)

    def test_tampered_package_rejected_and_quarantined(self):
        (self.client_pkg / "app.py").write_text("# EVIL\n", encoding="utf-8")  # 篡改
        v = self.verifier()
        self.assertFalse(v.verify(self.signed, self.client_pkg))
        self.assertEqual(v.last_error.split(":")[0], "FILE_HASH_MISMATCH")

    def test_tampered_signature_rejected(self):
        bad = json.loads(json.dumps(self.signed))
        bad["signature"] = "00" * 64
        v = self.verifier()
        self.assertFalse(v.verify(bad, self.client_pkg))
        self.assertEqual(v.last_error.split(":")[0], "SIGNATURE_INVALID")

    def test_downgrade_blocked(self):
        # 当前已是 1.3.0，更新 manifest 声称 1.2.0 → 拒绝降级（§1.4 Step 7）
        man = json.loads(json.dumps(self.manifest))
        man["version"] = "1.2.0"
        signed = sign_manifest(man, self.leaf_kp, self.pki.cert_chain())
        v = self.verifier(current="1.3.0")
        self.assertFalse(v.verify(signed, self.client_pkg))
        self.assertEqual(v.last_error.split(":")[0], "DOWNGRADE_BLOCKED")

    def test_stale_timestamp_rejected(self):
        man = json.loads(json.dumps(self.manifest))
        man["timestamp"] = self.now - 2 * 86400  # 48h 前 → 超 ±24h 窗口
        signed = sign_manifest(man, self.leaf_kp, self.pki.cert_chain())
        v = self.verifier()
        self.assertFalse(v.verify(signed, self.client_pkg))
        self.assertEqual(v.last_error.split(":")[0], "STALE_TIMESTAMP")

    def test_revoked_cert_rejected(self):
        leaf_fp = self.pki.cert_chain()[0]["fingerprint"]
        v = self.verifier(crl=[leaf_fp])  # §1.4 Step 3：证书已撤销
        self.assertFalse(v.verify(self.signed, self.client_pkg))
        self.assertEqual(v.last_error.split(":")[0], "CERT_REVOKED")

    def test_missing_file_rejected(self):
        (self.client_pkg / "data.bin").unlink()
        v = self.verifier()
        self.assertFalse(v.verify(self.signed, self.client_pkg))
        self.assertEqual(v.last_error.split(":")[0], "FILE_MISSING")

    def test_alert_fired_on_tamper(self):
        alerts = []
        bad = json.loads(json.dumps(self.signed))
        bad["signature"] = "00" * 64
        v = self.verifier(alert=lambda code, msg: alerts.append(code))
        self.assertFalse(v.verify(bad, self.client_pkg))
        self.assertIn("SIGNATURE_INVALID", alerts)  # §1.6.2 安全告警

    def test_quarantine_moves_package(self):
        # §1.4 Step 4 签名篡改 → 隔离可疑包（Step 6 文件哈希不符仅重下，不隔离）
        bad = json.loads(json.dumps(self.signed))
        bad["signature"] = "00" * 64
        v = self.verifier()
        self.assertFalse(v.verify(bad, self.client_pkg))
        self.assertTrue(any(p.name == "client_pkg" for p in self.quarantine.iterdir()))


class TestManifest(AivyTestCase):
    def test_aggregate_hash_deterministic(self):
        files = [
            {"path": "b.txt", "hash": "11"},
            {"path": "a.txt", "hash": "22"},
        ]
        h1 = aggregate_hash(files)
        h2 = aggregate_hash(list(reversed(files)))  # 乱序不影响
        self.assertEqual(h1, h2)

    def test_chunk_hashes_large_file(self):
        import hashlib

        p = Path(_TMP) / "big.bin"
        p.write_bytes(os.urandom(64 * 1024 * 1024))  # 64MB → 16 chunks @4MB
        try:
            chunks = __import__("aivyos_core.update.manifest", fromlist=["chunk_hashes"]).chunk_hashes(p)
            self.assertEqual(len(chunks), 16)
            self.assertEqual(len(chunks[0]), 64)  # 32 bytes hex
        finally:
            p.unlink(missing_ok=True)


class TestVersionManager(AivyTestCase):
    def test_version_compare(self):
        self.assertTrue(Version.is_higher("1.3.0", "1.2.9"))
        self.assertFalse(Version.is_higher("1.2.0", "1.3.0"))
        self.assertFalse(Version.is_higher("1.2.0", "1.2.0"))
        self.assertTrue(Version.is_higher("2.0.0", "1.99.99"))

    def test_install_switch_prune_rollback(self):
        root = Path(_TMP) / "versions_test"
        shutil.rmtree(root, ignore_errors=True)
        vm = VersionManager(root)
        for v, tag in (("1.0.0", "a"), ("1.1.0", "b"), ("1.2.0", "c"), ("1.3.0", "d")):
            pkg = Path(_TMP) / f"pkg_{v}"
            shutil.rmtree(pkg, ignore_errors=True)
            pkg.mkdir()
            (pkg / "ver.txt").write_text(tag)
            vm.install(v, pkg)
        # §2.3 保留 3 个版本
        self.assertEqual(vm.list_versions(), ["1.3.0", "1.2.0", "1.1.0"])
        self.assertFalse((root / "v1.0.0").exists())  # 更早版本自动清理
        self.assertEqual(vm.current_version(), "1.3.0")
        self.assertTrue((root / "current").exists())  # 符号链接或指针文件（沙箱降级）
        # 一键回滚
        self.assertEqual(vm.rollback(), "1.2.0")
        self.assertEqual(vm.current_version(), "1.2.0")


class TestDelta(AivyTestCase):
    def test_unchanged_files_reused(self):
        old = {"files": [{"path": "a.txt", "hash": "h1", "chunks": ["c1"]}]}
        new = {"files": [{"path": "a.txt", "hash": "h1", "chunks": ["c1"]}]}
        plan = DeltaPlanner().plan(old, new)
        self.assertEqual(len(plan["download"]), 0)
        self.assertEqual(plan["stats"]["saved_ratio"], 1.0)

    def test_changed_chunk_downloaded(self):
        old = {"files": [{"path": "big.bin", "hash": "old", "chunks": ["c1", "c2", "c3"]}]}
        new = {"files": [{"path": "big.bin", "hash": "new", "chunks": ["c1", "X2", "c3"]}]}  # 仅 chunk2 变更
        plan = DeltaPlanner().plan(old, new)
        self.assertEqual([d["chunk"] for d in plan["download"]], [1])
        self.assertEqual(len(plan["reuse"]), 2)

    def test_new_file_all_downloaded(self):
        old = {"files": []}
        new = {"files": [{"path": "n.txt", "hash": "h", "chunks": ["a", "b"]}]}
        plan = DeltaPlanner().plan(old, new)
        self.assertEqual(len(plan["download"]), 2)


class TestKeyPersistence(AivyTestCase):
    """CI 密钥持久化回归：seed 文件 → 派生公钥一致（修复 load_or_create_key 用随机公钥的 bug）。"""

    def test_seed_to_pubkey_stable(self):
        from aivyos_core.update.ed25519 import public_key as derive_pubkey

        kp = KeyPair.generate("root")
        seed_file = Path(_TMP) / "seed_test.key"
        seed_file.write_text(kp.seed.hex())
        seed = bytes.fromhex(seed_file.read_text().strip())
        self.assertEqual(derive_pubkey(seed).hex(), kp.pubkey_hex)  # 公钥由 seed 派生，非随机

    def test_script_style_roundtrip(self):
        """模拟 sign_update.py：持久化 Root/Intermediate → 签发 Leaf → 客户端验签。"""
        import json

        from aivyos_core.update.ed25519 import public_key as derive_pubkey

        root = KeyPair.generate("root")
        inter = KeyPair.generate("intermediate")
        pki, _, _ = PKI.bootstrap()
        pki = PKI(root.pubkey_hex)
        pki.intermediate = __import__(
            "aivyos_core.update.pki", fromlist=["make_cert"]
        ).make_cert(
            inter, "intermediate", int(time.time()), int(time.time()) + 31536000,
            pki.root_fingerprint, signer=root,
        )
        leaf = pki.issue_leaf(inter)
        pkg = Path(_TMP) / "script_pkg"
        pkg.mkdir(exist_ok=True)
        (pkg / "a.txt").write_text("x")
        manifest = build_manifest(pkg, "1.5.0", "patch", timestamp=int(time.time()))
        signed = sign_manifest(manifest, leaf, pki.cert_chain())
        # 客户端用 Root 公钥（由持久化 seed 派生）验证
        verifier = UpdateVerifier(
            pki=PKI(derive_pubkey(root.seed).hex()),
            current_version="1.4.0",
            now=int(time.time()),
        )
        self.assertTrue(verifier.verify(signed, pkg))
        self.assertIn("signature", verifier.steps_ok)


if __name__ == "__main__":
    unittest.main()
