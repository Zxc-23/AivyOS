"""音频层（文档 §3.1 语音输入 / §6.1 语音输出）：采集、VAD、播放。

全部组件遵循"代码优先 + 优雅降级"：sounddevice / silero-vad 可选安装，
缺失时自动降级（合成音源 / 能量 VAD / 空或 WAV 播放），保证链路可运行可测试。
"""

from aivyos_core.audio.source import AudioSource, MicSource, SyntheticSource, WavSource, create_source
from aivyos_core.audio.vad import EnergyVAD, SileroVAD, VADEngine, create_vad
from aivyos_core.audio.sink import AudioSink, NullSink, PlaybackSink, WavSink, create_sink
from aivyos_core.audio.wav import pcm_to_wav_bytes, read_wav, write_wav

__all__ = [
    "AudioSource", "MicSource", "SyntheticSource", "WavSource", "create_source",
    "VADEngine", "EnergyVAD", "SileroVAD", "create_vad",
    "AudioSink", "NullSink", "PlaybackSink", "WavSink", "create_sink",
    "pcm_to_wav_bytes", "read_wav", "write_wav",
]
