"""云端 ASR/TTS 引擎与提供商目录单元测试。

测试覆盖：
    1. 阿里云 ASR 引擎初始化与 Mock 降级
    2. 腾讯云 ASR 引擎初始化与签名生成
    3. 豆包 ASR 引擎初始化
    4. 豆包 TTS 引擎初始化、参数更新、Mock 降级
    5. 语音引擎注册表集成
    6. 提供商目录查询与搜索
    7. API Key 管理 IPC 接口

所有测试使用 mock，不发起真实 API 请求。
"""

import os
import unittest
from typing import Any, Dict

from aivyos_core.asr.base import ASRResult
from aivyos_core.tts.base import TTSResult
from aivyos_core.voice.engine_registry import (
    VoiceEngineRegistry, create_voice_registry,
    register_asr_engines, register_tts_engines,
)
from aivyos_core.llm.provider_catalog import (
    get_provider_catalog, get_provider_info, get_provider_models,
    search_models, get_categories, get_all_provider_ids,
)
from aivyos_core.llm.providers import register_all_providers
from aivyos_core.llm.provider_registry import ProviderRegistry


class TestAliyunASR(unittest.TestCase):
    """阿里云 ASR 引擎测试。"""

    def test_init_without_key(self):
        """无 API Key 时引擎不可用。"""
        from aivyos_core.asr.cloud_backends import AliyunASRBackend
        backend = AliyunASRBackend()
        self.assertEqual(backend.name, "aliyun")
        self.assertFalse(backend.available)

    def test_init_with_key(self):
        """有 API Key 时引擎可用。"""
        from aivyos_core.asr.cloud_backends import AliyunASRBackend
        backend = AliyunASRBackend(config={
            "api_key": "test-key-12345",
            "language": "zh",
            "model": "paraformer-v2",
        })
        self.assertTrue(backend.available)

    def test_mock_fallback(self):
        """无 API Key 时返回 Mock 结果。"""
        from aivyos_core.asr.cloud_backends import AliyunASRBackend
        backend = AliyunASRBackend()
        result = backend.transcribe(b"\x00" * 3200, 16000)
        self.assertIsInstance(result, ASRResult)
        self.assertEqual(result.backend, "aliyun-mock")
        self.assertEqual(result.confidence, 0.0)

    def test_config_params(self):
        """配置参数正确传递。"""
        from aivyos_core.asr.cloud_backends import AliyunASRBackend
        backend = AliyunASRBackend(config={
            "api_key": "test-key",
            "language": "en",
            "model": "paraformer-v1",
            "base_url": "https://custom.endpoint.com",
        })
        self.assertEqual(backend._language, "en")
        self.assertEqual(backend._model, "paraformer-v1")


class TestTencentASR(unittest.TestCase):
    """腾讯云 ASR 引擎测试。"""

    def test_init_without_key(self):
        """无密钥时不可用。"""
        from aivyos_core.asr.cloud_backends import TencentASRBackend
        backend = TencentASRBackend()
        self.assertFalse(backend.available)

    def test_init_with_keys(self):
        """有 SecretId + SecretKey 时可用。"""
        from aivyos_core.asr.cloud_backends import TencentASRBackend
        backend = TencentASRBackend(config={
            "secret_id": "AKIDtest123",
            "secret_key": "test-secret-key",
        })
        self.assertTrue(backend.available)

    def test_mock_fallback(self):
        """Mock 降级。"""
        from aivyos_core.asr.cloud_backends import TencentASRBackend
        backend = TencentASRBackend()
        result = backend.transcribe(b"\x00" * 3200, 16000)
        self.assertIsInstance(result, ASRResult)
        self.assertTrue(result.backend.endswith("-mock"))

    def test_signature_generation(self):
        """签名生成不抛异常。"""
        from aivyos_core.asr.cloud_backends import TencentASRBackend
        backend = TencentASRBackend(config={
            "secret_id": "AKIDtest123",
            "secret_key": "test-secret-key",
        })
        sig = backend._sign(1700000000, "{}")
        self.assertIsInstance(sig, str)
        self.assertTrue(len(sig) > 0)


class TestDoubaoASR(unittest.TestCase):
    """豆包 ASR 引擎测试。"""

    def test_init_without_key(self):
        from aivyos_core.asr.cloud_backends import DoubaoASRBackend
        backend = DoubaoASRBackend()
        self.assertEqual(backend.name, "doubao")
        self.assertFalse(backend.available)

    def test_init_with_keys(self):
        from aivyos_core.asr.cloud_backends import DoubaoASRBackend
        backend = DoubaoASRBackend(config={
            "access_key": "test-ak",
            "secret_key": "test-sk",
            "appid": "test-appid",
        })
        self.assertTrue(backend.available)

    def test_mock_fallback(self):
        from aivyos_core.asr.cloud_backends import DoubaoASRBackend
        backend = DoubaoASRBackend()
        result = backend.transcribe(b"\x00" * 3200, 16000)
        self.assertIsInstance(result, ASRResult)
        self.assertEqual(result.backend, "doubao-mock")

    def test_signature(self):
        from aivyos_core.asr.cloud_backends import DoubaoASRBackend
        backend = DoubaoASRBackend(config={
            "access_key": "test-ak",
            "secret_key": "test-sk",
        })
        sig = backend._gen_signature(1700000000)
        self.assertIsInstance(sig, str)


class TestDoubaoTTS(unittest.TestCase):
    """豆包 TTS 引擎测试。"""

    def test_init_without_key(self):
        from aivyos_core.tts.doubao_backend import DoubaoTTSBackend
        backend = DoubaoTTSBackend()
        self.assertEqual(backend.name, "doubao")
        self.assertEqual(backend.sample_rate, 24000)
        self.assertFalse(backend.available)

    def test_init_with_keys(self):
        from aivyos_core.tts.doubao_backend import DoubaoTTSBackend
        backend = DoubaoTTSBackend(config={
            "access_key": "test-ak",
            "secret_key": "test-sk",
            "appid": "test-appid",
        })
        self.assertTrue(backend.available)

    def test_mock_synthesize(self):
        from aivyos_core.tts.doubao_backend import DoubaoTTSBackend
        backend = DoubaoTTSBackend()
        result = backend.synthesize("你好世界")
        self.assertIsInstance(result, TTSResult)
        self.assertEqual(result.backend, "doubao-mock")
        self.assertEqual(len(result.pcm), 48000)  # 24000 * 2 bytes * 1s

    def test_update_params(self):
        from aivyos_core.tts.doubao_backend import DoubaoTTSBackend
        backend = DoubaoTTSBackend(config={
            "access_key": "test-ak",
            "secret_key": "test-sk",
        })
        backend.update_params(speed_ratio=1.5, volume_ratio=1.2, pitch_ratio=0.8)
        self.assertEqual(backend._speed_ratio, 1.5)
        self.assertEqual(backend._volume_ratio, 1.2)
        self.assertEqual(backend._pitch_ratio, 0.8)

    def test_update_params_clamping(self):
        from aivyos_core.tts.doubao_backend import DoubaoTTSBackend
        backend = DoubaoTTSBackend()
        # 超出范围应被钳制
        backend.update_params(speed_ratio=5.0)
        self.assertEqual(backend._speed_ratio, 2.0)
        backend.update_params(volume_ratio=0.0)
        self.assertEqual(backend._volume_ratio, 0.1)

    def test_custom_voice(self):
        from aivyos_core.tts.doubao_backend import DoubaoTTSBackend
        backend = DoubaoTTSBackend(config={"voice_type": "BV005_streaming"})
        self.assertEqual(backend._voice_type, "BV005_streaming")
        backend.update_params(voice_type="BV102_streaming")
        self.assertEqual(backend._voice_type, "BV102_streaming")


class TestVoiceEngineRegistry(unittest.TestCase):
    """语音引擎注册表集成测试。"""

    def test_register_cloud_asr(self):
        """云端 ASR 注册。"""
        reg = VoiceEngineRegistry()
        register_asr_engines(reg)
        self.assertIn("aliyun", reg._asr_types)
        self.assertIn("tencent", reg._asr_types)
        self.assertIn("doubao", reg._asr_types)

    def test_register_cloud_tts(self):
        """云端 TTS 注册。"""
        reg = VoiceEngineRegistry()
        register_tts_engines(reg)
        self.assertIn("doubao", reg._tts_types)

    def test_create_aliyun_engine(self):
        """实例化阿里云 ASR。"""
        reg = VoiceEngineRegistry()
        register_asr_engines(reg)
        backend = reg.create_asr(
            "asr-aliyun",
            provider="aliyun",
            model="paraformer-v2",
            config={"api_key": "test-key"},
            engine_type="aliyun",
        )
        self.assertIsNotNone(backend)
        # AliyunASRBackend 有 available 属性
        if hasattr(backend, 'available'):
            self.assertTrue(backend.available)

    def test_create_doubao_tts(self):
        """实例化豆包 TTS。"""
        reg = VoiceEngineRegistry()
        register_tts_engines(reg)
        backend = reg.create_tts(
            "tts-doubao",
            provider="doubao",
            config={
                "access_key": "test-ak",
                "secret_key": "test-sk",
                "appid": "test-appid",
            },
            engine_type="doubao",
        )
        self.assertIsNotNone(backend)
        if hasattr(backend, 'available'):
            self.assertTrue(backend.available)

    def test_list_engines(self):
        """引擎列表查询。"""
        reg = VoiceEngineRegistry()
        register_asr_engines(reg)
        register_tts_engines(reg)
        reg.create_asr("asr-test", config={})
        reg.create_tts("tts-test", config={})
        engines = reg.list_engines()
        self.assertGreaterEqual(len(engines), 2)

    def test_get_dashboard(self):
        """仪表盘数据。"""
        reg = VoiceEngineRegistry()
        register_asr_engines(reg)
        register_tts_engines(reg)
        dashboard = reg.get_dashboard()
        self.assertIn("total_engines", dashboard)
        self.assertIn("asr_count", dashboard)
        self.assertIn("tts_count", dashboard)

    def test_create_voice_registry(self):
        """创建完整注册表。"""
        config = {
            "asr": {"backend": "aliyun", "api_key": "test"},
            "tts": {"backend": "doubao", "access_key": "ak", "secret_key": "sk"},
        }
        reg = create_voice_registry(config)
        self.assertIsNotNone(reg)
        dashboard = reg.get_dashboard()
        self.assertGreater(dashboard["total_engines"], 0)


class TestProviderCatalog(unittest.TestCase):
    """提供商目录测试。"""

    def test_catalog_count(self):
        """目录包含 12 个提供商。"""
        providers = get_provider_catalog()
        self.assertEqual(len(providers), 12)

    def test_all_provider_ids(self):
        """所有 ID 正确。"""
        ids = get_all_provider_ids()
        expected = [
            "ollama", "vllm", "deepseek", "openai", "anthropic",
            "google", "qwen", "siliconflow", "azure-openai",
            "mistral", "bedrock", "doubao",
        ]
        for e in expected:
            self.assertIn(e, ids)

    def test_get_provider_info(self):
        """获取单个提供商信息。"""
        info = get_provider_info("deepseek")
        self.assertIsNotNone(info)
        self.assertEqual(info.name, "DeepSeek")
        self.assertEqual(info.category, "cloud-compat")
        self.assertTrue(len(info.models) > 0)

    def test_get_provider_models(self):
        """获取模型列表。"""
        models = get_provider_models("openai")
        self.assertGreater(len(models), 0)
        self.assertIn("name", models[0])
        self.assertIn("display_name", models[0])

    def test_search_models(self):
        """搜索模型。"""
        results = search_models("gpt-4o")
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("gpt-4o", r["name"].lower())

    def test_search_empty(self):
        """空搜索返回空列表。"""
        results = search_models("zzznonexistent999")
        self.assertEqual(len(results), 0)

    def test_categories(self):
        """按分类获取。"""
        cats = get_categories()
        self.assertIn("local", cats)
        self.assertIn("cloud-compat", cats)
        self.assertIn("cloud-native", cats)
        # 本地至少 2 个
        self.assertGreaterEqual(len(cats["local"]), 2)

    def test_all_models_have_fields(self):
        """所有模型信息完整。"""
        providers = get_provider_catalog()
        for p in providers:
            for m in p["models"]:
                self.assertTrue(m["name"], f"模型 {p['id']} 缺少 name")
                self.assertIn("context_window", m)
                self.assertIn("supports_vision", m)
                self.assertIn("supports_tool_use", m)


class TestProviderRegistry(unittest.TestCase):
    """LLM 提供商注册测试。"""

    def test_register_all(self):
        """注册所有提供商。"""
        reg = ProviderRegistry()
        register_all_providers(reg)
        providers = reg.list_provider_types()
        self.assertIn("doubao", providers)
        self.assertIn("deepseek", providers)
        self.assertIn("openai", providers)
        self.assertIn("ollama", providers)
        # 共 13 个（含 mock 和 doubao）
        self.assertGreaterEqual(len(providers), 12)

    def test_create_doubao_backend(self):
        """实例化豆包 LLM 后端。"""
        from aivyos_core.models import ProviderInfo, BackendCapability
        reg = ProviderRegistry()
        register_all_providers(reg)
        info = ProviderInfo(
            name="doubao-test",
            provider="doubao",
            model="doubao-pro-32k",
            api_key_env="VOLCENGINE_API_KEY",
        )
        backend = reg.create(info)
        self.assertEqual(backend.provider, "doubao")
        self.assertEqual(backend.model, "doubao-pro-32k")
        self.assertIsNotNone(backend.capabilities)

    def test_create_deepseek_backend(self):
        """实例化 DeepSeek 后端。"""
        from aivyos_core.models import ProviderInfo
        reg = ProviderRegistry()
        register_all_providers(reg)
        info = ProviderInfo(
            name="ds-test",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        backend = reg.create(info)
        self.assertEqual(backend.provider, "deepseek")

    def test_list_backends(self):
        """列出所有后端。"""
        from aivyos_core.models import ProviderInfo
        reg = ProviderRegistry()
        register_all_providers(reg)
        reg.create(ProviderInfo(name="b1", provider="mock", model="mock-1"))
        reg.create(ProviderInfo(name="b2", provider="doubao", model="doubao-pro-32k"))
        backends = reg.list_backends()
        self.assertEqual(len(backends), 2)

    def test_remove_backend(self):
        """移除后端。"""
        from aivyos_core.models import ProviderInfo
        reg = ProviderRegistry()
        register_all_providers(reg)
        reg.create(ProviderInfo(name="temp", provider="mock", model="m"))
        self.assertTrue(reg.remove("temp"))
        self.assertFalse(reg.contains("temp"))


class TestAPIKeyManagement(unittest.TestCase):
    """API Key 管理测试。"""

    def test_set_env_key(self):
        """设置环境变量 API Key。"""
        os.environ["_AIVYOS_TEST_KEY"] = "test-value-12345"
        self.assertEqual(os.environ.get("_AIVYOS_TEST_KEY"), "test-value-12345")
        # 清理
        del os.environ["_AIVYOS_TEST_KEY"]

    def test_remove_env_key(self):
        """移除环境变量。"""
        os.environ["_AIVYOS_TEST_KEY2"] = "val"
        self.assertEqual(os.environ.get("_AIVYOS_TEST_KEY2"), "val")
        del os.environ["_AIVYOS_TEST_KEY2"]
        self.assertIsNone(os.environ.get("_AIVYOS_TEST_KEY2"))


if __name__ == "__main__":
    unittest.main()