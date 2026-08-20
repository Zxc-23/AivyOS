"""快速测试 FunASR 是否可用于真实语音转写。"""
import sys
sys.path.insert(0, 'F:/AivyOS/aivyos')

try:
    from aivyos_core.asr.manager import create_asr
    asr = create_asr({"backend": "funasr"})
    print(f"ASR 后端: {asr.__class__.__name__}")
    print(f"ASR 名称: {asr.name}")
    print("✅ FunASR 加载成功！")
except Exception as e:
    print(f"❌ FunASR 加载失败: {e}")
    print("将使用 Mock ASR 进行测试")