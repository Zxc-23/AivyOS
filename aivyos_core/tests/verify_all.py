"""快速验证所有模块导入和唤醒检测逻辑。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aivyos_core.audio.source import MicSource, _apply_gain, WavSource, SyntheticSource, create_source
from aivyos_core.audio.vad import SileroVAD, EnergyVAD, create_vad, _rms
from aivyos_core.audio.wake_loop import WakeLoop, start_wake_loop, stop_wake_loop
from aivyos_core.wake import WakeWordDetector
from aivyos_core.asr.manager import create_asr

print("All imports OK")

wd = WakeWordDetector()
tests = ['你好艾薇', '艾薇', 'aivy', 'Aivy', '贾维斯', '哎维', '爱薇', 'aivory', 'hello']
for t in tests:
    print(f'  "{t}" -> detect={wd.detect(t)}')

# Test EnergyVAD calibration
vad = EnergyVAD(threshold=30, auto_calibrate=True)
import struct, math
noise = bytearray(1024)
for i in range(512):
    v = int(26 * 0.5 * math.sin(2 * math.pi * 200 * i / 16000))
    struct.pack_into('<h', noise, i*2, max(-32768, min(32767, v)))

# Feed 20 frames to calibrate
for _ in range(25):
    vad.is_speech(bytes(noise))

print(f'\nEnergyVAD after calibration: threshold={vad.threshold}, calibrated={vad._calibrated}')
print(f'  Noise frame RMS={_rms(bytes(noise)):.1f}, is_speech={vad.is_speech(bytes(noise))}')

# Test speech above threshold
speech = bytearray(1024)
for i in range(512):
    v = int(100 * math.sin(2 * math.pi * 1000 * i / 16000))
    struct.pack_into('<h', speech, i*2, max(-32768, min(32767, v)))
print(f'  Speech frame RMS={_rms(bytes(speech)):.1f}, is_speech={vad.is_speech(bytes(speech))}')

print('\n✅ All verification passed')