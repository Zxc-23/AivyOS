"""测试语音模块：ASR + TTS + 唤醒词"""
import sys
sys.path.insert(0, '.')
import time

def test_tts():
    """测试TTS功能"""
    print("=" * 60)
    print("测试1: TTS语音合成")
    print("=" * 60)
    
    from aivyos_core.tts.manager import create_tts
    
    config = {
        'backend': 'edge-tts',
        'voice': 'zh-CN-XiaoxiaoNeural',
        'speed': 1.0,
        'sample_rate': 24000,
    }
    
    print(f"配置: {config}")
    
    try:
        tts = create_tts(config)
        print(f"TTS引擎: {tts.name}")
        
        test_text = "您好，我是Aivy，很高兴为您服务！"
        print(f"合成文本: {test_text}")
        
        t0 = time.time()
        result = tts.synthesize(test_text)
        elapsed = time.time() - t0
        
        print(f"合成耗时: {elapsed:.2f}s")
        print(f"音频长度: {len(result.pcm)} bytes")
        print(f"采样率: {result.sample_rate}")
        print(f"后端: {result.backend}")
        
        if result.pcm:
            print("\n[成功] TTS语音合成正常！")
            return True
        else:
            print("\n[失败] 合成结果为空")
            return False
            
    except Exception as e:
        print(f"\n[错误] TTS测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_asr():
    """测试ASR功能"""
    print("\n" + "=" * 60)
    print("测试2: ASR语音识别")
    print("=" * 60)
    
    from aivyos_core.asr.manager import create_asr
    
    config = {
        'backend': 'auto',
        'model': 'sensevoice-small',
        'language': 'zh',
        'sample_rate': 16000,
        'silence_threshold': 15.0,
    }
    
    print(f"配置: backend={config['backend']}, model={config['model']}")
    
    try:
        asr = create_asr(config)
        print(f"ASR引擎: {asr.name}")
        
        # 创建测试音频（1秒静音）
        test_pcm = b'\x00' * 32000
        
        print("\n首次识别（会触发模型加载+预热）...")
        t0 = time.time()
        result = asr.transcribe(test_pcm, 16000)
        elapsed1 = time.time() - t0
        print(f"首次识别耗时: {elapsed1:.2f}s")
        
        print("\n第二次识别（模型已缓存）...")
        t0 = time.time()
        result2 = asr.transcribe(test_pcm, 16000)
        elapsed2 = time.time() - t0
        print(f"第二次识别耗时: {elapsed2:.2f}s")
        
        print(f"\n识别结果: text='{result2.text}', backend={result2.backend}")
        
        # 检查是否有预热日志
        if elapsed2 < elapsed1:
            print("[成功] 模型缓存生效，第二次调用更快！")
        else:
            print("[提示] 第二次调用速度未明显提升（可能是首次识别已完成预热）")
        
        return True
        
    except Exception as e:
        print(f"\n[错误] ASR测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_wake_word():
    """测试唤醒词检测"""
    print("\n" + "=" * 60)
    print("测试3: 唤醒词检测")
    print("=" * 60)
    
    from aivyos_core.wake import WakeWordDetector
    
    detector = WakeWordDetector(["Aivy", "艾薇", "贾维斯"])
    print(f"唤醒词: {detector.words}")
    
    test_cases = [
        ("你好，Aivy", True, "英文唤醒词"),
        ("你好，艾薇", True, "中文唤醒词"),
        ("艾薇儿", True, "包含唤醒词"),
        ("贾维斯，启动系统", True, "唤醒词在前"),
        ("今天天气怎么样", False, "无唤醒词"),
        ("aivory", False, "相似但不是唤醒词"),
        ("帮我打开电脑", False, "普通指令"),
    ]
    
    all_passed = True
    for text, expected, desc in test_cases:
        result = detector.detect(text)
        passed = result == expected
        status = "✅" if passed else "❌"
        print(f"  {status} {desc}: '{text}' -> 检测={result}, 期望={expected}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n[成功] 唤醒词检测正常！")
    else:
        print("\n[失败] 部分唤醒词检测异常")
    
    return all_passed

def test_voice_session():
    """测试语音会话"""
    print("\n" + "=" * 60)
    print("测试4: 语音会话（文本模式）")
    print("=" * 60)
    
    from aivyos_core.voice.session import VoiceSession
    from aivyos_core.config import load_config
    
    config = load_config()
    print(f"配置已加载")
    
    try:
        session = VoiceSession(config)
        print(f"语音会话已创建")
        print(f"ASR: {session.asr.name}")
        print(f"TTS: {session.tts.name}")
        print(f"唤醒词: {session.wake.words}")
        print(f"唤醒词检测: {'启用' if session.wake_required else '禁用'}")
        
        # 测试文本模式
        test_text = "Aivy，你好吗"
        print(f"\n测试文本: '{test_text}'")
        
        import asyncio
        result = asyncio.run(session.run_turn(text_override=test_text))
        
        print(f"\n会话结果:")
        print(f"  文本: {result.get('text')}")
        print(f"  回复: {result.get('reply')}")
        print(f"  唤醒词命中: {result.get('wake')}")
        print(f"  ASR后端: {result.get('asr_backend')}")
        print(f"  TTS后端: {result.get('tts_backend')}")
        print(f"  总耗时: {result.get('latency_ms', 0):.0f}ms")
        
        if result.get('reply'):
            print("\n[成功] 语音会话正常！")
            return True
        else:
            print("\n[提示] 会话无回复（可能是唤醒词未命中或LLM问题）")
            return False
            
    except Exception as e:
        print(f"\n[错误] 语音会话测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("AivyOS 语音模块测试")
    print("=" * 60)
    
    results = {
        'TTS': test_tts(),
        'ASR': test_asr(),
        '唤醒词': test_wake_word(),
        '语音会话': test_voice_session(),
    }
    
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")
    
    print(f"\n通过率: {passed}/{total} ({passed*100//total}%)")
