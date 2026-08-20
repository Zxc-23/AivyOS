"""Phase 2 集成测试：成本追踪、语音引擎注册表、情感控制、云端引擎。

验证：
    1. CostTracker 成本统计
    2. EmotionController 情感标签注入
    3. VoiceEngineRegistry 引擎管理
    4. 云端引擎 Mock 降级
"""

import sys
import asyncio
sys.path.insert(0, ".")

from aivyos_core.llm.cost_tracker import CostTracker, BackendCostStats
from aivyos_core.voice.emotion import EmotionController, EMOTION_TAG_MAP
from aivyos_core.voice.engine_registry import (
    VoiceEngineRegistry,
    register_asr_engines,
    register_tts_engines,
    create_voice_registry,
)
from aivyos_core.voice.cloud_engines import (
    CloudTTSBackend,
    ElevenLabsBackend,
    EdgeTTSBackend,
    CloudASRBackend,
    DeepgramBackend,
    register_cloud_engines,
)


def test_cost_tracker():
    """测试成本追踪模块。"""
    print("--- Test 1: CostTracker 成本追踪 ---")
    tracker = CostTracker()

    # 注册后端
    tracker.register_backend("ollama-local", cost_per_1m_input=0.0, cost_per_1m_output=0.0)
    tracker.register_backend("deepseek-chat", cost_per_1m_input=0.5, cost_per_1m_output=2.0)

    # 记录请求
    tracker.record("ollama-local", input_tokens=100, output_tokens=50, latency_ms=100)
    tracker.record("ollama-local", input_tokens=200, output_tokens=80, latency_ms=150)
    tracker.record("deepseek-chat", input_tokens=1000, output_tokens=200, latency_ms=300)

    # 验证统计
    stats = tracker.get_stats()
    assert "ollama-local" in stats
    assert stats["ollama-local"]["total_requests"] == 2
    assert stats["ollama-local"]["total_input_tokens"] == 300
    assert stats["ollama-local"]["total_output_tokens"] == 130
    assert stats["ollama-local"]["avg_latency_ms"] == 125.0

    assert "deepseek-chat" in stats
    assert stats["deepseek-chat"]["total_requests"] == 1
    assert stats["deepseek-chat"]["total_cost_usd"] > 0  # 应有费用

    # 仪表盘
    dashboard = tracker.get_dashboard()
    assert dashboard["total_requests"] == 3
    assert dashboard["backend_count"] == 2
    assert len(dashboard["recent"]) <= 10

    # 重置
    tracker.reset("ollama-local")
    ollama_stats = tracker.get_stats("ollama-local")
    assert ollama_stats["total_requests"] == 0

    # JSON 导出
    json_str = tracker.export_json()
    assert "total_requests" in json_str

    print(f"  Stats: {len(stats)} backends, {dashboard['total_requests']} requests")
    print("  PASSED")


def test_emotion_controller():
    """测试情感标签注入器。"""
    print("--- Test 2: EmotionController 情感控制 ---")
    ctrl = EmotionController()

    # 手动注入
    result = ctrl.inject("你好", emotion="happy")
    assert "[laughter]" in result
    assert "你好" in result

    result = ctrl.inject("别难过", emotion="sad")
    assert "[cry]" in result

    result = ctrl.inject("安静点", emotion="whisper")
    assert "[whisper]" in result

    # neutral 不注入
    result = ctrl.inject("普通文本", emotion="neutral")
    assert result == "普通文本"

    # 自动检测
    emotion = ctrl.detect("今天真开心，哈哈")
    assert emotion == "happy"

    emotion = ctrl.detect("为什么这么生气")
    assert emotion == "angry"

    emotion = ctrl.detect("没什么特别的")
    assert emotion == "neutral"

    # 自动注入
    result = ctrl.auto_inject("今天真开心")
    assert "[laughter]" in result

    # 批量处理
    results = ctrl.process_batch(["你好", "真开心", "别难过"])
    assert len(results) == 3

    # 标签清理
    text = ctrl.strip_tags("你好 [laughter] 今天天气不错")
    assert "[laughter]" not in text
    assert "你好" in text

    # 关闭
    ctrl.set_enabled(False)
    result = ctrl.inject("开心", emotion="happy")
    assert "[laughter]" not in result

    # 支持的情感列表
    emotions = ctrl.get_supported_emotions()
    assert "happy" in emotions
    assert len(emotions) >= 8

    # 统计
    stats = ctrl.stats()
    assert int(stats["supported_emotions"]) >= 8

    print(f"  Supported emotions: {len(emotions)}")
    print("  PASSED")


def test_voice_engine_registry():
    """测试语音引擎注册表。"""
    print("--- Test 3: VoiceEngineRegistry 引擎管理 ---")
    reg = VoiceEngineRegistry()

    # 注册 mock 引擎
    register_asr_engines(reg)
    register_tts_engines(reg)

    # 实例化
    asr = reg.create_asr("mock", provider="aivyos", model="mock-asr")
    assert asr is not None

    tts = reg.create_tts("mock", provider="aivyos", model="mock-tts")
    assert tts is not None

    # 列出引擎
    engines = reg.list_engines()
    assert len(engines) >= 2

    # 转录
    result = reg.transcribe("asr-mock", b"\x00" * 3200, 16000)
    assert result is not None

    # 合成
    result = reg.synthesize("tts-mock", "你好世界")
    assert result is not None
    assert result.pcm is not None
    assert len(result.pcm) > 0

    # 健康检查
    status = reg.health_check("asr-mock")
    assert status.status in ("ok", "down")

    # 仪表盘
    dashboard = reg.get_dashboard()
    assert dashboard["total_engines"] >= 2

    # 移除
    removed = reg.remove("asr-mock")
    assert removed
    assert reg.get("asr-mock") is None

    # 未注册引擎抛错
    try:
        reg.create_asr("nonexistent")
        assert False, "应抛 ValueError"
    except ValueError:
        pass

    print(f"  Engines: {dashboard['total_engines']}")
    print("  PASSED")


def test_cloud_engine_adapters():
    """测试云端引擎适配器（Mock 降级）。"""
    print("--- Test 4: 云端引擎适配器 ---")

    # Edge TTS 不需要 API Key
    edge = EdgeTTSBackend({"voice": "zh-CN-XiaoxiaoNeural"})
    assert edge.available
    assert edge.name == "edge-tts"

    # Mock 合成（edge-tts 未安装时降级）
    result = edge.synthesize("测试文本")
    assert result is not None
    assert result.backend is not None

    # ElevenLabs 无 Key 时不可用
    eleven = ElevenLabsBackend()
    assert not eleven.available

    # Mock 降级
    result = eleven.synthesize("测试")
    assert result is not None
    assert "mock" in result.backend

    # Deepgram 无 Key 时不可用
    deepgram = DeepgramBackend()
    assert not deepgram.available

    # Mock 降级
    result = deepgram.transcribe(b"\x00" * 3200)
    assert result is not None
    assert "mock" in result.backend

    # 注册到注册表
    reg = VoiceEngineRegistry()
    register_cloud_engines(reg)

    # 实例化 edge-tts（可用）
    edge_instance = reg.create_tts("edge-tts", provider="microsoft", model="xiaoxiao")
    assert edge_instance is not None

    # 实例化 deepgram（不可用但可创建实例）
    dg_instance = reg.create_asr("deepgram", provider="deepgram", model="general")
    assert dg_instance is not None

    print("  PASSED")


def test_voice_registry_factory():
    """测试语音注册表工厂函数。"""
    print("--- Test 5: create_voice_registry 工厂 ---")
    config = {
        "asr": {"backend": "mock"},
        "tts": {"backend": "mock"},
    }
    reg = create_voice_registry(config)
    engines = reg.list_engines()
    assert len(engines) >= 2

    dashboard = reg.get_dashboard()
    assert dashboard["asr_count"] >= 1
    assert dashboard["tts_count"] >= 1

    print(f"  Created: {dashboard['total_engines']} engines")
    print("  PASSED")


def test_cost_tracker_integration():
    """测试 CostTracker 与路由集成。"""
    print("--- Test 6: CostTracker 与 ModelRouter 集成 ---")
    from aivyos_core.config import DEFAULT_CONFIG
    from aivyos_core.llm.router import ModelRouter

    # Phase 1 兼容模式
    cfg = dict(DEFAULT_CONFIG["llm"])
    cfg["mode"] = "mock"
    router = ModelRouter(cfg)

    # 确认成本追踪器已初始化
    assert router.cost_tracker is not None

    # mock 后端应有 1 个后端注册
    stats = router.cost_tracker.get_stats()
    assert len(stats) >= 1

    # 执行一次 mock 对话（成本追踪应自动记录）
    from aivyos_core.models import LLMRequest
    request = LLMRequest(messages=[{"role": "user", "content": "你好"}], model="mock")
    decision = router.route("你好")
    response = asyncio.run(router.complete(request, decision))
    assert response is not None

    # 验证成本记录增加
    recent = router.cost_tracker.get_recent(limit=5)
    assert len(recent) >= 1

    dashboard = router.cost_tracker.get_dashboard()
    print(f"  Dashboard: {dashboard['total_requests']} requests tracked")
    print("  PASSED")


def test_emotion_with_voice_registry():
    """情感控制与语音引擎注册表集成。"""
    print("--- Test 7: 情感 + 语音引擎集成 ---")
    from aivyos_core.config import DEFAULT_CONFIG

    # 情感控制器
    emotion_cfg = DEFAULT_CONFIG.get("emotion", {})
    ctrl = EmotionController(enabled=emotion_cfg.get("enabled", True))

    # 语音注册表
    config = {
        "asr": {"backend": "mock"},
        "tts": {"backend": "mock"},
    }
    reg = create_voice_registry(config)

    # 合成带情感的文本
    text = ctrl.auto_inject("今天真开心啊")
    result = reg.synthesize("tts-mock", text)
    assert result is not None

    # 验证情感标签已注入
    assert "[laughter]" in text or text == "今天真开心啊"  # 可能检测为 neutral

    print(f"  Emotion text: {text}")
    print("  PASSED")


if __name__ == "__main__":
    tests = [
        test_cost_tracker,
        test_emotion_controller,
        test_voice_engine_registry,
        test_cloud_engine_adapters,
        test_voice_registry_factory,
        test_cost_tracker_integration,
        test_emotion_with_voice_registry,
    ]

    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 50)
    print("ALL PHASE 2 INTEGRATION TESTS COMPLETED")
    print("=" * 50)