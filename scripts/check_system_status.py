"""系统状态检查脚本 - 分析当前Mock模式和依赖状态"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from aivyos_core.config import load_config

def main():
    cfg = load_config()
    
    print("=" * 60)
    print("  AivyOS 系统状态分析报告")
    print("=" * 60)
    
    # LLM模式
    llm_mode = cfg['llm']['mode']
    print(f"\n【LLM路由模式】{llm_mode}")
    print(f"  本地后端: Ollama @ {cfg['llm']['local']['base_url']}")
    print(f"  云端后端: {cfg['llm']['cloud']['base_url']}")
    
    # 检查API Key
    api_key = os.environ.get('AIVYOS_CLOUD_API_KEY', '')
    print(f"  云端API Key: {'✅ 已配置' if api_key else '❌ 未配置'}")
    
    # 语音配置
    print(f"\n【语音链路配置】")
    print(f"  ASR后端: {cfg['asr']['backend']}")
    print(f"  TTS后端: {cfg['tts']['backend']}")
    print(f"  VAD后端: {cfg['audio']['vad_backend']}")
    print(f"  音频输入: {cfg['audio']['input_backend']}")
    
    # 记忆配置
    print(f"\n【记忆系统】")
    print(f"  记忆后端: {cfg['memory']['backend']}")
    print(f"  抽取后端: {cfg['memory']['extract_backend']}")
    print(f"  MemFS启用: {cfg['memfs']['enabled']}")
    
    # 工作流
    print(f"\n【工作流引擎】")
    print(f"  执行器: {cfg['workflow']['executor']}")
    print(f"  自动预览: {cfg['workflow']['preview']}")
    
    # 认证
    print(f"\n【认证系统】")
    print(f"  认证开启: {cfg['auth']['enabled']}")
    print(f"  面部后端: {cfg['auth']['face_backend']}")
    print(f"  语音后端: {cfg['auth']['voice_backend']}")
    
    # Mock模式判断
    print("\n" + "=" * 60)
    print("  Mock模式状态判断")
    print("=" * 60)
    
    if llm_mode == 'mock':
        print("\n⚠️  系统处于【强制MOCK模式】")
        print("    - 所有对话使用模拟回复")
        print("    - 无法进行真实LLM推理")
        print("    - 仅用于演示和测试")
    elif llm_mode == 'auto' and not api_key:
        print("\n⚠️  系统处于【AUTO模式，但将回退到MOCK】")
        print("    - 未配置云端API Key")
        print("    - 本地Ollama可能未运行")
        print("    - 实际运行时将自动降级到Mock后端")
    elif llm_mode == 'local':
        print("\n✅ 系统强制使用【本地模式】")
        print("    - 需要Ollama运行在本地")
    elif llm_mode == 'cloud':
        if api_key:
            print("\n✅ 系统强制使用【云端模式】")
        else:
            print("\n⚠️  系统强制云端模式，但无API Key，将失败")
    
    # 依赖检查
    print("\n" + "=" * 60)
    print("  Python依赖检查")
    print("=" * 60)
    
    deps = {
        'yaml': 'PyYAML (配置加载)',
        'sounddevice': 'sounddevice (音频采集)',
        'numpy': 'numpy (数值计算)',
        'silero_vad': 'silero-vad (VAD语音活动检测)',
        'funasr': 'funasr (ASR语音识别)',
        'cosyvoice': 'cosyvoice (TTS语音合成)',
        'mem0': 'mem0 (向量记忆)',
        'langgraph': 'langgraph (工作流)',
    }
    
    mock_components = []
    degraded_components = []
    
    for dep, desc in deps.items():
        try:
            __import__(dep)
            print(f"  ✅ {dep}: {desc}")
        except ImportError:
            print(f"  ❌ {dep}: {desc} (将使用Mock/降级模式)")
            degraded_components.append(desc)
    
    # 总结
    print("\n" + "=" * 60)
    print("  系统降级状态总结")
    print("=" * 60)
    
    print(f"\n  当前模式: {llm_mode}")
    print(f"  缺失组件数: {len(degraded_components)}")
    
    if degraded_components:
        print(f"  将降级的功能:")
        for comp in degraded_components:
            print(f"    - {comp} → 使用Mock后端")
    
    print(f"\n  结论: 系统{'处于' if llm_mode == 'mock' else '将回退到'}Mock模拟数据模式")

if __name__ == '__main__':
    main()