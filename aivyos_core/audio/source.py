"""音频采集源（文档 §3.1：16kHz 单声道 PCM）。

- MicSource：真实麦克风（sounddevice 可选；未安装抛 AudioUnavailable）
- WavSource：WAV 文件回放（测试/离线）
- SyntheticSource：合成信号（正弦音/静音，测试与演示）

`create_source` 按配置自动选择，全部后端输出统一 16-bit PCM 帧。
"""

from __future__ import annotations

import asyncio
import logging
import math
import struct
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from aivyos_core.audio.wav import read_wav

log = logging.getLogger(__name__)


def _apply_gain(data: bytes, gain: float) -> bytes:
    """对 PCM 16-bit 音频帧应用增益（带削波保护）。

    Args:
        data: 16-bit PCM 字节数据
        gain: 增益倍数（>1 放大, <1 衰减）

    Returns:
        放大后的 PCM 数据
    """
    n = len(data) // 2
    if n == 0 or gain == 1.0:
        return data
    out = bytearray(len(data))
    for i in range(n):
        (s,) = struct.unpack_from("<h", data, i * 2)
        v = int(s * gain)
        v = max(-32768, min(32767, v))
        struct.pack_into("<h", out, i * 2, v)
    return bytes(out)


class AudioUnavailable(RuntimeError):
    """音频设备/后端不可用。"""


class AudioSource(ABC):
    sample_rate: int = 16000
    channels: int = 1
    frame_ms: int = 30

    @property
    def frame_bytes(self) -> int:
        return self.sample_rate * self.channels * 2 * self.frame_ms // 1000

    @abstractmethod
    def stream(self) -> AsyncIterator[bytes]:
        """产出 16-bit PCM 帧（每帧 frame_ms）。"""
        raise NotImplementedError

    def close(self) -> None:
        """释放资源。默认实现为空。"""
        pass


class MicSource(AudioSource):
    """真实麦克风（sounddevice 可选依赖）。

    使用 sounddevice 回调模式 + asyncio.Queue，确保采集不阻塞事件循环。
    支持多消费者：多次调用 stream() 共享底层音频流。
    """

    def __init__(self, sample_rate: int = 16000, frame_ms: int = 30, device: Optional[object] = None,
                 gain: float = 1.0) -> None:
        """初始化麦克风源。

        Args:
            sample_rate: 采样率
            frame_ms: 帧长（毫秒）
            device: 设备索引或名称
            gain: 软件增益倍数（1.0=无增益, 10.0=20dB 放大）
        """
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as e:
            raise AudioUnavailable(
                "麦克风采集需要 sounddevice：pip install sounddevice（或设置 AIVYOS_AUDIO_INPUT=wav|synthetic）"
            ) from e
        self.sd = sd
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.gain = gain
        self.device = self._resolve_device(device)
        self._blocksize = max(1, sample_rate * frame_ms // 1000)
        self._stream: Optional[object] = None
        self._queue: Optional[asyncio.Queue[bytes]] = None
        self._started = False
        self._consumers = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @staticmethod
    def _resolve_device(device: Optional[object]) -> Optional[object]:
        """解析设备参数：支持整数索引、字符串索引或设备名。"""
        if device is None:
            return None
        if isinstance(device, int):
            return device
        if isinstance(device, str):
            try:
                return int(device)
            except ValueError:
                return device
        return device

    async def stream(self) -> AsyncIterator[bytes]:
        """通过 sounddevice 回调模式采集音频，不阻塞事件循环。

        多次调用共享底层音频流和队列。
        """
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop

        if not self._started:
            self._queue = asyncio.Queue(maxsize=500)
            self._started = True
            self._consumers = 0
            self._start_stream()

        self._consumers += 1
        queue = self._queue

        try:
            while True:
                frame = await queue.get()
                yield frame
        except asyncio.CancelledError:
            raise
        finally:
            self._consumers -= 1
            if self._consumers <= 0:
                self._consumers = 0
                self._shutdown_stream()

    def _start_stream(self) -> None:
        """启动底层音频流（在主循环中调用一次）。

        Windows WASAPI 下设备刚被其他流释放时立即重开会报
        [Errno 22] Invalid argument → 带重试 + 退避。
        """
        loop = self._loop
        if loop is None:
            return

        queue = self._queue
        gain = self.gain
        sd = self.sd

        def _callback(indata, frames, time_info, status):
            if status:
                log.warning("MicSource callback status: %s", status)
            data = bytes(indata)
            if gain != 1.0:
                data = _apply_gain(data, gain)
            try:
                loop.call_soon_threadsafe(queue.put_nowait, data)
            except Exception as e:
                log.debug("忽略预期内异常: %s", e, exc_info=True)

        import time

        last_err: Optional[Exception] = None
        for attempt in range(3):  # 最多 3 次尝试（设备释放延迟）
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="int16",
                    blocksize=self._blocksize,
                    device=self.device,
                    callback=_callback,
                )
                self._stream.start()
                log.info("MicSource 已启动: sr=%d ch=%d block=%d gain=%.1fx (attempt=%d)",
                         self.sample_rate, self.channels, self._blocksize, self.gain, attempt + 1)
                return
            except Exception as e:
                last_err = e
                log.warning("MicSource 启动失败 (attempt %d/3): %s — 300ms 后重试", attempt + 1, e)
                if self._stream is not None:
                    try:
                        self._stream.close()
                    except Exception as e:
                        log.debug("忽略预期内异常: %s", e, exc_info=True)
                    self._stream = None
                time.sleep(0.3)  # 等待 WASAPI 释放设备

        self._started = False
        self._stream = None
        raise last_err if last_err is not None else AudioUnavailable("麦克风启动失败")

    def _shutdown_stream(self) -> None:
        """关闭底层音频流。"""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                log.debug("忽略预期内异常: %s", e, exc_info=True)
            self._stream = None
        self._started = False
        log.info("MicSource 已关闭")

    def close(self) -> None:
        """释放所有资源。"""
        self._consumers = 0
        self._shutdown_stream()


class WavSource(AudioSource):
    """从 WAV 文件读取（离线/测试）。"""

    def __init__(self, path: str, frame_ms: int = 30) -> None:
        rate, pcm = read_wav(path)
        self.sample_rate = rate
        self.frame_ms = frame_ms
        self._pcm = pcm

    async def stream(self) -> AsyncIterator[bytes]:
        step = self.frame_bytes
        for i in range(0, len(self._pcm), step):
            yield self._pcm[i : i + step]
            await asyncio.sleep(0)


class SyntheticSource(AudioSource):
    """合成信号源：测试与演示（正弦音 / 静音 / 噪声）。"""

    def __init__(
        self,
        duration_s: float = 3.0,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        tone_hz: Optional[float] = None,
        amplitude: int = 4000,
        silence_after_s: float = 0.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.duration_s = duration_s
        self.tone_hz = tone_hz
        self.amplitude = amplitude
        self.silence_after_s = silence_after_s

    async def stream(self) -> AsyncIterator[bytes]:
        n_frames = int(self.duration_s * self.sample_rate)
        step = self.frame_bytes
        for i in range(0, n_frames, self.sample_rate * self.frame_ms // 1000):
            yield self._make_frame(min(step, (n_frames - i) * 2))
            await asyncio.sleep(0)

    def _make_frame(self, nbytes: int) -> bytes:
        n = nbytes // 2
        if self.tone_hz is None:
            return b"\x00\x00" * n
        out = bytearray()
        for i in range(n):
            v = int(self.amplitude * math.sin(2 * math.pi * self.tone_hz * i / self.sample_rate))
            out += struct.pack("<h", max(-32768, min(32767, v)))
        return bytes(out)


def create_source(cfg: dict) -> AudioSource:
    """按配置选择音源：auto → mic（可用）→ synthetic；wav 指定文件路径。"""
    backend = cfg.get("input_backend", "auto")
    rate = int(cfg.get("sample_rate", 16000))
    frame_ms = int(cfg.get("frame_ms", 30))
    device = cfg.get("device")
    gain = float(cfg.get("gain", 1.0))

    if backend == "mic":
        return MicSource(rate, frame_ms, device, gain)
    if backend == "wav":
        path = cfg.get("wav_path")
        if not path:
            raise AudioUnavailable("input_backend=wav 但未配置 audio.wav_path")
        return WavSource(path, frame_ms)
    if backend == "synthetic":
        return SyntheticSource(sample_rate=rate, frame_ms=frame_ms)

    # auto
    try:
        return MicSource(rate, frame_ms, device, gain)
    except AudioUnavailable:
        log.warning("麦克风不可用，回退到合成音源（静音模式）")
        return SyntheticSource(sample_rate=rate, frame_ms=frame_ms)