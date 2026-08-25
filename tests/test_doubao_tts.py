"""豆包 TTS 后端可用性检查测试。"""

import os
import unittest

try:
    from aivyos_core.tts.doubao_backend import DoubaoTTSBackend
    _DOUBAO_AVAILABLE = True
except Exception:
    _DOUBAO_AVAILABLE = False

from tests import AivyTestCase


@unittest.skipIf(not _DOUBAO_AVAILABLE, "DoubaoTTSBackend 导入失败，跳过豆包 TTS 测试")
class TestDoubaoAvailability(AivyTestCase):
    def test_availability_ok_with_access_key(self):
        """传入 access_key='abc' 时，ok=True、reason=has_key。"""
        result = DoubaoTTSBackend.availability_check(access_key="abc")
        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "has_key")

    def test_availability_missing_both(self):
        """无 api_key、无 access_key、环境变量也缺失时，ok=False、reason=missing_key。"""
        saved = os.environ.pop("VOLCENGINE_API_KEY", None)
        try:
            result = DoubaoTTSBackend.availability_check()
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "missing_key")
        finally:
            if saved is not None:
                os.environ["VOLCENGINE_API_KEY"] = saved

    def test_supports_access_key_param_true(self):
        """supports_access_key_param 恒为 True，同时 sample_rate/default_voice 字段存在。"""
        result = DoubaoTTSBackend.availability_check(access_key="x")
        self.assertTrue(result["supports_access_key_param"])
        self.assertEqual(result["sample_rate"], 24000)
        self.assertEqual(result["default_voice"], "zh_female_xiaohe_uranus_bigtts")


if __name__ == "__main__":
    unittest.main()
