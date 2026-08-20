"""调试 FunASR 初始化。"""
import sys, traceback
sys.path.insert(0, 'F:/AivyOS/aivyos')

try:
    from funasr import AutoModel
    print("1. import AutoModel OK")
    
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        device="cpu",
        disable_update=True,
    )
    print("2. AutoModel 加载成功！")
    print(f"   模型类型: {type(model)}")
except Exception as e:
    print(f"❌ 错误: {type(e).__name__}: {e}")
    traceback.print_exc()