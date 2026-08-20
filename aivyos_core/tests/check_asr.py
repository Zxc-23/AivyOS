"""检查 ASR 后端可用性。"""
import sys
sys.path.insert(0, 'F:/AivyOS/aivyos')

try:
    import funasr
    print(f"funasr: {funasr.__version__}")
except ImportError:
    print("funasr: NOT installed")

try:
    import whisper
    print("whisper: available")
except ImportError:
    print("whisper: NOT installed")

try:
    import faster_whisper
    print("faster_whisper: available")
except ImportError:
    print("faster_whisper: NOT installed")

# Test the ASR manager
from aivyos_core.asr.manager import create_asr
asr = create_asr({"backend": "auto"})
print(f"\nDefault ASR: {asr.__class__.__name__}")
print(f"ASR name: {asr.name}")

# Test with pre-configured text
from aivyos_core.asr.mock_backend import MockASR
mock = MockASR(text="你好艾薇")
result = mock.transcribe(b"dummy", 16000)
print(f"\nMock ASR test: text={result.text}, backend={result.backend}")

# Verify wake detector works
from aivyos_core.wake import WakeWordDetector
wd = WakeWordDetector()
print(f"\nWake detector: detect('你好艾薇') = {wd.detect('你好艾薇')}")
print(f"Wake detector: detect('今天天气不错') = {wd.detect('今天天气不错')}")
print(f"Wake detector: detect('艾薇早上好') = {wd.detect('艾薇早上好')}")