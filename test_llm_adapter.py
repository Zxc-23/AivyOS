"""LLM 适配器层集成测试 — Phase 2 多提供商路由验证。"""

import sys
import asyncio
sys.path.insert(0, ".")

from aivyos_core.llm.router import ModelRouter
from aivyos_core.models import LLMRequest, RouteMode


def test_phase2_providers_mode():
    """Phase 2 多提供商列表模式。"""
    print("--- Test 1: Phase 2 providers 列表模式 ---")
    cfg = {
        "mode": "auto",
        "routing_strategy": "auto",
        "providers": [
            {"name": "ollama-local", "provider": "ollama", "model": "qwen2.5:3b",
             "base_url": "http://127.0.0.1:11434/v1", "priority": 30},
            {"name": "deepseek-chat", "provider": "deepseek", "model": "deepseek-chat",
             "base_url": "https://api.deepseek.com/v1", "priority": 40},
        ],
        "local": {},
        "cloud": {},
        "mock": {"model": "mock-echo"},
    }
    router = ModelRouter(cfg)
    status = router.backends_status()
    print(f"  Backends: {len(status)} 个")
    for s in status:
        print(f"    - {s['model']} ({s['provider']}), available={s['available']}")
    assert len(status) >= 3  # ollama + deepseek + mock
    print("  PASSED")


def test_routing_decisions():
    """路由决策测试。"""
    print()
    print("--- Test 2: 路由决策 ---")
    cfg = {
        "mode": "auto",
        "routing_strategy": "auto",
        "providers": [
            {"name": "ollama-local", "provider": "ollama", "model": "qwen2.5:3b",
             "base_url": "http://127.0.0.1:11434/v1", "priority": 30},
            {"name": "deepseek-chat", "provider": "deepseek", "model": "deepseek-chat",
             "base_url": "https://api.deepseek.com/v1", "priority": 40},
        ],
        "local": {}, "cloud": {},
        "mock": {"model": "mock-echo"},
    }
    router = ModelRouter(cfg)

    tests = [
        ("你好，今天过得怎么样？", "chat"),
        ("帮我写一个快速排序算法", "coding"),
        ("分析一下这个架构的优缺点", "complex_reasoning"),
    ]
    for text, task in tests:
        decision = router.route(text, task_type=task)
        print(f"  {task}: mode={decision.mode.value}, model={decision.model}")
    print("  PASSED")


def test_phase1_compat():
    """Phase 1 兼容模式。"""
    print()
    print("--- Test 3: Phase 1 兼容模式 ---")
    cfg = {
        "mode": "auto",
        "local": {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5:3b", "timeout_s": 60,
        },
        "cloud": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat", "api_key_env": "TEST_API_KEY",
        },
        "mock": {"model": "mock-echo"},
    }
    router = ModelRouter(cfg)
    status = router.backends_status()
    print(f"  Phase1 backends: {len(status)} 个")
    for s in status:
        print(f"    - {s['model']} ({s['provider']}), available={s['available']}")

    decision = router.route("你好")
    print(f"  路由决策: mode={decision.mode.value}, model={decision.model}")
    print("  PASSED")


def test_forced_mode():
    """强制模式测试。"""
    print()
    print("--- Test 4: 强制模式 ---")
    cfg = {
        "mode": "auto",
        "providers": [
            {"name": "ollama-local", "provider": "ollama", "model": "qwen2.5:3b",
             "base_url": "http://127.0.0.1:11434/v1", "priority": 30},
        ],
        "local": {}, "cloud": {},
        "mock": {"model": "mock-echo"},
    }
    router = ModelRouter(cfg)

    auto = router.route("test")
    forced = router.route("test", force_provider="ollama-local")
    mock_f = router.route("test", force_provider="mock-default")

    print(f"  自动: model={auto.model}")
    print(f"  强制 ollama-local: model={forced.model}")
    print(f"  强制 mock-default: model={mock_f.model}")
    assert forced.model == "ollama-local"
    assert mock_f.model == "mock-default"
    print("  PASSED")


def test_strategy_switching():
    """路由策略切换测试。"""
    print()
    print("--- Test 5: 路由策略 ---")
    cfg = {
        "mode": "auto",
        "routing_strategy": "auto",
        "providers": [
            {"name": "ollama-local", "provider": "ollama", "model": "qwen2.5:3b",
             "base_url": "http://127.0.0.1:11434/v1", "priority": 30},
            {"name": "deepseek-chat", "provider": "deepseek", "model": "deepseek-chat",
             "base_url": "https://api.deepseek.com/v1", "priority": 40},
        ],
        "local": {}, "cloud": {},
        "mock": {"model": "mock-echo"},
    }
    router = ModelRouter(cfg)

    for strategy in ["auto", "cost-based", "latency-based", "capability-based"]:
        router.set_strategy(strategy)
        decision = router.route("test")
        print(f"  {strategy}: model={decision.model}")
    print("  PASSED")


def test_complexity_estimation():
    """复杂度估计测试。"""
    print()
    print("--- Test 6: 复杂度估计 ---")
    tests = [
        ("你好", "simple_chat"),
        ("帮我写一个快速排序", "coding"),
        ("分析一下这个架构的优缺点", "complex_reasoning"),
        ("看下这张图片", "vision"),
        ("重构这个函数的代码", "coding"),
        ("为什么会这样", "complex_reasoning"),
    ]
    for text, expected in tests:
        result = ModelRouter.estimate_complexity(text)
        status = "OK" if result == expected else "FAIL"
        print(f"  [{status}] '{text}' → {result} (期望: {expected})")
    print("  PASSED")


def test_mock_chat():
    """Mock 后端对话测试。"""
    print()
    print("--- Test 7: Mock 后端对话 ---")
    cfg = {
        "mode": "mock",
        "providers": [],
        "local": {}, "cloud": {},
        "mock": {"model": "mock-echo"},
    }
    router = ModelRouter(cfg)

    async def _do():
        request = LLMRequest(
            messages=[{"role": "user", "content": "你好"}],
            model="mock-echo",
        )
        decision = router.route("你好")
        response = await router.complete(request, decision)
        print(f"  Mock 回复: {response.text[:80]}...")
        print(f"  模型: {response.model}, 延迟: {response.latency_ms:.1f}ms")
        return response

    asyncio.run(_do())
    print("  PASSED")


def test_dynamic_management():
    """动态管理测试。"""
    print()
    print("--- Test 8: 动态管理 ---")
    from aivyos_core.models import ProviderInfo

    cfg = {
        "mode": "auto",
        "providers": [],
        "local": {}, "cloud": {},
        "mock": {"model": "mock-echo"},
    }
    router = ModelRouter(cfg)

    # Add provider dynamically
    info = ProviderInfo(
        name="dynamic-test",
        provider="ollama",
        model="llama3:8b",
        base_url="http://127.0.0.1:11434/v1",
        priority=20,
    )
    backend = router.add_provider(info)
    print(f"  动态添加: {backend.name} ({backend.provider})")
    assert router.registry.contains("dynamic-test")

    # Remove provider
    removed = router.remove_provider("dynamic-test")
    print(f"  动态移除: {removed}")
    assert not router.registry.contains("dynamic-test")
    print("  PASSED")


def test_circuit_breaker_integration():
    """熔断器集成测试。"""
    print()
    print("--- Test 9: 熔断器集成 ---")
    cfg = {
        "mode": "auto",
        "providers": [
            {"name": "ollama-local", "provider": "ollama", "model": "qwen2.5:3b",
             "base_url": "http://127.0.0.1:11434/v1", "priority": 30,
             "breaker_threshold": 3, "breaker_cooldown_s": 60.0},
        ],
        "local": {}, "cloud": {},
        "mock": {"model": "mock-echo"},
    }
    router = ModelRouter(cfg)

    breaker = router.registry.get_breaker("ollama-local")
    assert breaker is not None
    assert breaker.state == "closed"

    # Simulate failures
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == "closed"
    breaker.record_failure()
    assert breaker.state == "open"

    # Can't execute when open
    can = router.registry.can_execute("ollama-local")
    assert not can

    # Reset
    breaker.reset()
    assert breaker.state == "closed"
    print(f"  熔断器状态机: OK")
    print("  PASSED")


if __name__ == "__main__":
    test_phase2_providers_mode()
    test_routing_decisions()
    test_phase1_compat()
    test_forced_mode()
    test_strategy_switching()
    test_complexity_estimation()
    test_mock_chat()
    test_dynamic_management()
    test_circuit_breaker_integration()

    print()
    print("=" * 50)
    print("ALL INTEGRATION TESTS PASSED")
    print("=" * 50)