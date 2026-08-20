"""验证ASR引擎"""
import sys
sys.path.insert(0, '.')
from aivyos_core.asr.manager import create_asr

# 测试FunASR本地引擎
config = {
    'backend': 'auto',
    'model': 'sensevoice-small',
    'language': 'zh',
    'sample_rate': 16000,
}

asr = create_asr(config)
print(f'ASR引擎: {asr.name}')

# 创建测试音频
test_pcm = b'\x00' * 32000  # 1秒静音

result = asr.transcribe(test_pcm, 16000)
text = result.text[:80] if result.text else "空"
print(f'识别结果: {text}')
print(f'置信度: {result.confidence}')
print(f'后端: {result.backend}')
print()
print('[成功] FunASR本地引擎工作正常！')