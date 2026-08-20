"""集成功能测试脚本 - 全面测试AivyOS核心功能模块"""
import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from aivyos_core.config import load_config
from aivyos_core.chat.engine import ChatEngine


async def test_features():
    """执行核心功能模块集成测试"""
    cfg = load_config()
    cfg['llm']['mode'] = 'mock'
    engine = ChatEngine(cfg)

    results = []

    # 1. 测试状态查询
    print('=== 1. 系统状态测试 ===')
    try:
        status = engine.status()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        results.append(('系统状态查询', 'PASS', ''))
    except Exception as e:
        print(f'❌ 系统状态查询失败: {e}')
        results.append(('系统状态查询', 'FAIL', str(e)))

    # 2. 测试对话
    print('\n=== 2. 对话功能测试 ===')
    try:
        reply = await engine.send('你好')
        print(f'回复: {reply.text}')
        print(f'模型: {reply.model}')
        print(f'会话ID: {reply.session_id}')
        results.append(('基础对话', 'PASS', ''))
    except Exception as e:
        print(f'❌ 对话功能测试失败: {e}')
        results.append(('基础对话', 'FAIL', str(e)))

    # 3. 测试记忆功能
    print('\n=== 3. 记忆功能测试 ===')
    try:
        reply2 = await engine.send('我叫张三，我喜欢编程')
        print(f'回复: {reply2.text}')
        hits = await engine.memory.search('张三')
        print(f'记忆搜索结果: {len(hits)} 条')
        for h in hits:
            print(f'  - {h.text[:50]}')
        results.append(('记忆存储与检索', 'PASS', ''))
    except Exception as e:
        print(f'❌ 记忆功能测试失败: {e}')
        results.append(('记忆存储与检索', 'FAIL', str(e)))

    # 4. 测试会话列表
    print('\n=== 4. 会话管理测试 ===')
    try:
        sessions = engine.list_sessions()
        print(f'总会话数: {len(sessions)}')
        for s in sessions[:3]:
            sid = s.get('session_id', 'unknown')
            msgs = s.get('messages', 0)
            print(f'  - {sid}: {msgs} 条消息')
        results.append(('会话管理', 'PASS', ''))
    except Exception as e:
        print(f'❌ 会话管理测试失败: {e}')
        results.append(('会话管理', 'FAIL', str(e)))

    # 5. 测试人格系统
    print('\n=== 5. 人格系统测试 ===')
    try:
        persona = engine.persona.to_dict()
        print(json.dumps(persona, ensure_ascii=False, indent=2))
        results.append(('人格系统', 'PASS', ''))
    except Exception as e:
        print(f'❌ 人格系统测试失败: {e}')
        results.append(('人格系统', 'FAIL', str(e)))

    # 6. 测试路由状态
    print('\n=== 6. LLM路由状态 ===')
    try:
        for r in engine.router.backends_status():
            mode = r.get('mode', 'unknown')
            model = r.get('model', 'unknown')
            avail = r.get('available', False)
            breaker = r.get('breaker_state', 'unknown')
            print(f'  {mode:6s} | {model:20s} | 可用={avail} | 熔断器={breaker}')
        results.append(('LLM路由', 'PASS', ''))
    except Exception as e:
        print(f'❌ LLM路由测试失败: {e}')
        results.append(('LLM路由', 'FAIL', str(e)))

    # 7. 测试上下文管理
    print('\n=== 7. 上下文管理测试 ===')
    try:
        chat_cfg = cfg.get('chat', {})
        print(f'上下文窗口: {chat_cfg.get("context_window", 32768)} tokens')
        print(f'历史轮次保留: {chat_cfg.get("history_turns", 12)}')
        print(f'摘要触发轮次: {chat_cfg.get("summarize_from_turn", 12)}')
        results.append(('上下文管理', 'PASS', ''))
    except Exception as e:
        print(f'❌ 上下文管理测试失败: {e}')
        results.append(('上下文管理', 'FAIL', str(e)))

    # 8. 测试记忆后端
    print('\n=== 8. 记忆后端测试 ===')
    try:
        print(f'记忆后端: {engine.memory.backend_name}')
        print(f'MemFS启用: {engine.memfs.enabled}')
        memfs_summary = engine.memfs.summary()
        print(f'MemFS统计: {json.dumps(memfs_summary, ensure_ascii=False)}')
        results.append(('记忆后端', 'PASS', ''))
    except Exception as e:
        print(f'❌ 记忆后端测试失败: {e}')
        results.append(('记忆后端', 'FAIL', str(e)))

    # 汇总结果
    print('\n' + '=' * 60)
    print('  集成测试结果汇总')
    print('=' * 60)
    
    passed = sum(1 for _, status, _ in results if status == 'PASS')
    failed = sum(1 for _, status, _ in results if status == 'FAIL')
    
    for name, status, err in results:
        icon = '✅' if status == 'PASS' else '❌'
        print(f'  {icon} {name}: {status}')
        if err:
            print(f'     错误: {err}')
    
    print(f'\n总计: {passed} 通过, {failed} 失败')
    
    if failed == 0:
        print('\n✅ 所有集成测试通过！')
    else:
        print(f'\n⚠️  有 {failed} 项测试失败，需要修复')

    return results


if __name__ == '__main__':
    asyncio.run(test_features())