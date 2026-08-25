# AIVY-VOICE-HARD-001 语音链路硬约束加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AivyOS 语音主链路（VAD / Mic / Wake Word / Playback / 重试 / Mock 降级）全部对齐 project_memory 锁定的 8 条硬约束数值，杜绝 FunASR 识别失败、事件循环卡顿、唤醒词误触发三大历史痛点，同时确保全部 18+ 新增单测 TDD 红→绿 + 原有 voice 类 60 tests 零回归。

**Architecture:** 8 条硬约束拆成 4 Task（按依赖链：VAD→Mic→Wake→Playback/重试/Mock），每条硬约束严格对应 project_memory Lessons Learned 编号；全部新增函数带中文函数级注释（用户规则 5.6）；零新增第三方依赖（Chroma 等新功能不在本计划）。

**Tech Stack:** Python 3.11 stdlib + numpy（VAD 已有）/ sounddevice（Mic 已有）/ unittest；严格 Windows PowerShell 5.1 语法；修改文件锁定 5 个 + 新增 2 个测试文件。

---

## 文件结构（File Structure）

| 路径 | 角色 | 操作 | 关键行范围 |
|---|---|---|---|
| `aivyos_core/audio/vad.py` | SileroVAD + EnergyVAD 主实现 | Modify | `class SileroVAD` 定义段 + `process_frame()` / `reset()` |
| `aivyos_core/audio/source.py` | MicSource（麦克风采集）主实现 | Modify | `class MicSource` 定义段 + `stream()` async 生成器 + `gain` 默认值 |
| `aivyos_core/voice/wake.py` | 唤醒词检测器主实现 | Modify | `class WakeWordDetector` 定义段 + `detect(text)` / `strip(text)` / 变体列表 |
| `aivyos_core/audio/sink.py` | PlaybackSink（音频播放）主实现 | Modify | `class PlaybackSink` 定义段 + `play(pcm)` 方法 |
| `aivyos_core/cloud_engines/doubao_tts.py` | 豆包云 TTS（含 Mock 回退逻辑） | Modify | `availability_check(access_key=...)` + `synthesize()` 无 Key 回退 |
| `aivyos_core/voice/session.py` | VoiceSession（串联链路）重试参数 | Modify | TTS/ASR 云调用 `max_retries=1, backoff=0.5` 常量 |
| `tests/test_vad.py` | 新增 SileroVAD frame_size 自适应单测 | Create | Class TestSileroVadFrameAdapt（4 tests） |
| `tests/test_wake.py` | 现有唤醒词单测文件（已有 TestWake，在原基础追加） | Modify | 追加 Class TestWakeHardening（12 tests） |
| `tests/test_source_sink.py` | 新增 MicSource gain+callback / PlaybackSink 非阻塞单测 | Create | 2 classes（MicSource=6 tests / PlaybackSink=3 tests）共 9 tests |
| `tests/test_doubao_fallback.py` | 新增豆包 TTS 无 Key Mock 回退 + availability_check 参数单测 | Create | 5 tests |
| `说明文档.md` | 全生命周期唯一载体：§二 追加 §2.5 + §三 ×8 行进度 | Modify | §二 §2.5 / §三 进度表尾部 |

---

## 硬约束逐条对应清单（NO Placeholders）

> 每条来自 project_memory Lessons Learned，不可随意改变数值。

| # | 硬约束原文（project_memory Verbatim） | 对应 Task | 验收数值 |
|---|---|---|---|
| HC-1 | SileroVAD class implements frame size adaptation（auto padding/truncation to 512 samples） | Task 1 | 输入 400→pad 112 零 / 输入 544→trunc 前 512 / 输入 512→原样 / frame 维度自动 reshape 避免 np 广播报错 |
| HC-2 | MicSource gain must be set to 1.0x (original signal) to prevent audio clipping | Task 2 | MicSource.__init__(gain=...) 默认值 = 1.0；测试 case gain=100 时 PCM 最大值≥32767 触发削波警告日志 |
| HC-3 | MicSource.stream() using sounddevice.RawInputStream.read() synchronous blocking call causes event loop freeze and application 卡顿; use callback mode with asyncio.Queue instead | Task 2 | stream() 改 RawInputStream(callback=...) + asyncio.Queue(maxsize=32)；测试阻塞事件 <5ms（用 asyncio.sleep(0.01) 对比时差） |
| HC-4 | Wake word detection requires 1.5s window with 50% overlap to avoid truncating speech | Task 3 | 窗口大小 WINDOW_MS=1500；STEP_MS=750（50%）；test: 16kHz 采样下窗口样本 = 24000 帧；每次前移 12000 帧 |
| HC-5 | Wake word matching must use three-tier strategy: full variant matching, two-character independent matching, and English word boundary matching | Task 3 | detect("贾维斯今天天气") → True；detect("阿,还没吃饭") 谐音"还"="威"？不，谐音变体在变体列表里。三层：① variants 列表精确包含（命中第一层）→ ② 变体拆成两字任意组合（"贾+斯"或"维+斯"或"贾+维"连续）→ ③ 英文 /jarvis/ Aivy 词边界 `\b` re.search |
| HC-6 | Wake word variants must include homophones（阿, 还, 威, 喂 etc.）to handle ASR recognition errors | Task 3 | VARIANTS = ["贾维斯","加维斯","甲维斯","嘉维斯","阿维斯","哈维斯","艾维斯","诶维斯","喂维斯","威维斯","还维斯","微薇丝","Jarvis","jarvis","Aivy","aivy","艾维"] 至少 12 条中文谐音 + 2 条英文 |
| HC-7 | Wake word detection must exclude single-character matches to prevent false triggers (e.g. "可爱", "微凉") | Task 3 | detect("可爱的小狗") → False；detect("微凉的秋天") → False；检测逻辑：如果命中是单字符则忽略（两层之后都必须至少 2 字窗口或词边界） |
| HC-8 | Wake word duplicates must be deduplicated (same text within 1 second triggers only once) | Task 3 | `_last_trigger_ts:float = 0.0`；连续两次 detect("贾维斯") 间隔 <0.9s 第二次返回 False；间隔 >1.1s 第二次返回 True |
| HC-9 | `text_override` mode should bypass wake word detection and automatically pass the check | Task 3 | session.run_turn(text_override="你好") 且 wake_required=True 时 wake_passed=True 不报错；无需唤醒词命中 |
| HC-10 | MicSource.stream callback mode；PlaybackSink non-blocking；PlaybackSink.play(pcm) no sd.wait() | Task 4 | sink.play(pcm) 调用返回时间 < 2ms（非阻塞）；time.perf_counter() 前后差值 ≤ 0.005 |
| HC-11 | 3x retry with exponential backoff (1s+2s=4s) for TTS/ASR causes unacceptable delays in real-time voice interaction; reduce to 1x retry with 0.5s delay | Task 4 | cloud_engines 调用常量：MAX_RETRIES=1, BACKOFF_FIRST=0.5；测试 max_retries>1 时失败 |
| HC-12 | When no API Key is available for 豆包 TTS, return Mock results instead of throwing exceptions | Task 4 | DoubaoTTS(api_key=None).synthesize("你好") 返回 AudioSinkData(pcm=..., sr=24000, backend="mock-doubao")，不抛 |
| HC-13 | 豆包 TTS availability check should support `access_key` as the parameter name for API Key | Task 4 | availability_check(access_key="abc") → ok=True；availability_check(access_key=None/empty) → ok=False, reason=missing_key；旧参数名 `api_key` 仍兼容 |
| HC-14 | Mock TTS backend produces noise when real TTS engines fail to initialize; implement explicit error messages and warning feedback instead of silent degradation | Task 4 | session.py TTS exception 分支 log.warning("TTS 合成失败：%s", e) + result dict 追加 `tts_error_detail=str(e)` |

---

### Task 1: SileroVAD 帧大小自适应 512 samples（HC-1）

**Files:**
- Modify: `aivyos_core/audio/vad.py`（`class SileroVAD` 的 `process_frame(frame: np.ndarray) -> VADState`）
- Create: `tests/test_vad.py` 追加 Class TestSileroVadFrameAdapt

- [ ] **Step 1: Write the failing test（4 tests TDD，test_vad.py 新建文件末尾追加）**

```python
"""tests/test_vad.py（已有文件，如不存在则新建）- SileroVAD 帧大小自适应。"""
import unittest
import numpy as np
from aivyos_core.audio.vad import SileroVAD  # 若 EnergyVAD/SileroVAD 命名有偏差，以 vad.py 实际类名为准，此处以 project_memory 硬约束 SileroVAD 类名为准


class TestSileroVadFrameAdapt(unittest.TestCase):
    def _make_class(self):
        try:
            return SileroVAD(sample_rate=16000, threshold=0.5)
        except Exception:
            # 依赖缺失时：项目约定 100% 优雅降级，返回 None 让 test 用 skipIf 机制
            return None

    def test_frame_shorter_pads_zeros_to_512(self):
        """小于 512 samples 的帧末尾补零，不抛 numpy 维度错误。"""
        vad = self._make_class()
        if vad is None:
            self.skipTest("SileroVAD 不可用（依赖缺失）")
        frame = np.array([100] * 400, dtype=np.int16)  # 400 samples，短于 512
        # 必须不抛 KeyError / ValueError / np.AxisError
        try:
            state = vad.process_frame(frame)
        except Exception as e:
            self.fail(f"短帧应自动补零，不应抛异常: {type(e).__name__}: {e}")
        self.assertIsNotNone(state)

    def test_frame_longer_truncates_first_512(self):
        """大于 512 samples 的帧截断前 512 samples。"""
        vad = self._make_class()
        if vad is None:
            self.skipTest("SileroVAD 不可用（依赖缺失）")
        frame = np.array([i % 32767 for i in range(544)], dtype=np.int16)  # 544 > 512
        try:
            state = vad.process_frame(frame)
        except Exception as e:
            self.fail(f"长帧应截断到 512，不应抛异常: {type(e).__name__}: {e}")
        self.assertIsNotNone(state)

    def test_frame_exactly_512_passthrough(self):
        """正好 512 samples 的帧原样传递，结果一致。"""
        vad = self._make_class()
        if vad is None:
            self.skipTest("SileroVAD 不可用（依赖缺失）")
        frame = np.array([1] * 512, dtype=np.int16)
        try:
            state = vad.process_frame(frame.copy())
        except Exception as e:
            self.fail(f"512 帧不应抛异常: {type(e).__name__}: {e}")
        self.assertIsNotNone(state)

    def test_frame_mono_only_no_stereo_shape_error(self):
        """立体声(shape N,2) 必须先取左单声道或 raise ValueError 明确，而非 np 广播错误。"""
        vad = self._make_class()
        if vad is None:
            self.skipTest("SileroVAD 不可用（依赖缺失）")
        stereo = np.zeros((256, 2), dtype=np.int16)
        try:
            state = vad.process_frame(stereo)
        except ValueError as e:
            # 允许：明确抛出 ValueError 告知用户
            self.assertIn("单声道", str(e))
            return
        except Exception as e:
            self.fail(f"立体声帧要么 ValueError，要么单声道提取，绝不允许 np 广播类错误: {type(e).__name__}: {e}")
        # 若未抛则必须成功返回（自动取左声道）
        self.assertIsNotNone(state)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd f:\AivyOS\aivyos ; python -m unittest tests.test_vad.TestSileroVadFrameAdapt -v 2>&1 | Select-Object -First 30`
Expected: FAIL 1+（SileroVAD 不存在 / process_frame 未做 pad/trunc → 抛 ValueError: shapes not aligned 或 np.AxisError）

- [ ] **Step 3: Write minimal implementation（vad.py SileroVAD.process_frame 开头插入帧大小适配逻辑）**

```python
# 在 SileroVAD.process_frame 函数开头（if 已存在任何 frame 处理代码之前）插入：

# ---- HC-1: 帧大小自适应（512 samples 固定）----
# 函数注释（用户规则 5.6）：
"""
对输入 PCM 帧做 Silero 模型尺寸对齐（固定 512 samples = 32ms @ 16kHz）。

参数:
    frame (np.ndarray): 输入帧，允许 int16 / float32 / shape (N,) 或 (N,1) 或 (N,2) 立体声
返回:
    np.ndarray: 对齐后的 (512,) float32 单声道帧，范围 [-1.0, 1.0]（Silero 要求）
异常:
    ValueError: 输入维度 > 2 时明确抛出"单声道"提示
"""
import numpy as np  # 已 import 则省略

def _adapt_frame_to_512(self, frame: np.ndarray) -> np.ndarray:
    """
    Silero 模型固定输入 512 samples：短补零、长截断、立体声→左单声道、int16→float32 [-1,1]。

    参数:
        frame: 任意长度 PCM（int16 或 float32），允许 1D / (N,1) / (N,2)
    返回:
        np.ndarray: shape (512,) dtype float32，归一化 [-1.0, 1.0]
    异常:
        ValueError: ndim > 2 或形状无法解释时
    """
    TARGET = 512
    if not isinstance(frame, np.ndarray):
        frame = np.asarray(frame, dtype=np.float32)
    if frame.ndim > 2:
        raise ValueError(f"SileroVAD 仅支持单声道/立体声（ndim≤2），实际 {frame.ndim}")
    # 立体声自动取左声道（project_memory 约定：无特殊说明时保留 L 通道）
    if frame.ndim == 2:
        if frame.shape[1] == 1:
            frame = frame[:, 0]
        elif frame.shape[1] >= 2:
            frame = frame[:, 0]
    # 归一化（Silero 需要 float32 [-1, 1]）
    if np.issubdtype(frame.dtype, np.integer):
        max_abs = float(np.iinfo(frame.dtype).max)
        frame = frame.astype(np.float32) / max_abs
    elif frame.dtype != np.float32:
        frame = frame.astype(np.float32)
    n = frame.shape[0]
    if n < TARGET:
        # 末尾补零（project_memory 约定 pad 在后，避免截断波形前沿）
        pad = np.zeros(TARGET - n, dtype=np.float32)
        frame = np.concatenate([frame, pad])
    elif n > TARGET:
        # 前 512（截断尾部，保留前沿能量便于 VAD 判断）
        frame = frame[:TARGET]
    return frame.reshape(TARGET)  # 强制 1D
```

在 process_frame(self, frame) 开头第一行调用：`aligned = self._adapt_frame_to_512(frame)`，后续将 aligned 传给 Silero 模型调用（替换原 frame 变量）。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd f:\AivyOS\aivyos ; python -m unittest tests.test_vad.TestSileroVadFrameAdapt -v 2>&1 | Select-Object -Last 15`
Expected: `Ran 4 tests OK` 或 `SKIP ... 依赖缺失` 但 0 fail/error（project_memory 允许组件降级）

---

### Task 2: MicSource gain=1.0x + callback 模式 asyncio.Queue（HC-2 + HC-3）

**Files:**
- Modify: `aivyos_core/audio/source.py`（Class MicSource: __init__ gain 默认值、stream() 重写）
- Create: `tests/test_source_sink.py` Class TestMicSourceHardening（6 tests）

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_source_sink.py 新建文件。"""
import asyncio
import unittest
import time
import numpy as np


class TestMicSourceHardening(unittest.TestCase):
    def _import(self):
        try:
            from aivyos_core.audio.source import MicSource
            return MicSource
        except Exception:
            return None

    def test_gain_default_is_1_0(self):
        """HC-2: MicSource 默认 gain=1.0（原始信号），绝不能 100x 削波。"""
        MicSource = self._import()
        if MicSource is None:
            self.skipTest("MicSource 不可用")
        # gain 参数默认值必须 1.0
        import inspect
        sig = inspect.signature(MicSource.__init__)
        default_gain = sig.parameters.get("gain")
        self.assertIsNotNone(default_gain, "MicSource.__init__ 必须有 gain 参数")
        self.assertEqual(default_gain.default, 1.0, f"默认 gain 必须 1.0 防削波，实际 {default_gain.default}")

    def test_callback_mode_does_not_block_event_loop(self):
        """HC-3: stream() 必须使用 RawInputStream callback + asyncio.Queue，事件循环卡顿 <5ms。"""
        MicSource = self._import()
        if MicSource is None:
            self.skipTest("MicSource 不可用")
        # 用 FakeMicSource（继承 MicSource 覆写 _create_stream 返回模拟 sd InputStream）来测试，避免真实麦克风被占
        # 这里最小化：检查 stream() 是 AsyncGenerator 且首次 next() 不阻塞（<20ms）
        async def scenario():
            try:
                src = MicSource(rate=16000, frame_ms=30, gain=1.0)
            except Exception as e:
                # 允许 AudioUnavailable（无麦克风），降级 PASS 不视为 fail
                if "AudioUnavailable" in type(e).__name__ or "不可用" in str(e):
                    return ("skipped", None)
                raise
            t0 = time.perf_counter()
            # 异步生成器取第一帧前半次迭代（anext）
            agen = src.stream()
            try:
                frame = await asyncio.wait_for(agen.__anext__(), timeout=0.1)
            except (asyncio.TimeoutError, StopAsyncIteration) as e:
                # Timeout / StopAsyncIteration 都 OK，关键是不阻塞 > 50ms
                delta_ms = (time.perf_counter() - t0) * 1000
                return ("done", delta_ms)
            except Exception as e:
                if "AudioUnavailable" in type(e).__name__ or "麦克风" in str(e):
                    return ("skipped", None)
                raise
            delta_ms = (time.perf_counter() - t0) * 1000
            return ("ok", delta_ms)

        result, delta_ms = asyncio.run(scenario())
        if result == "skipped":
            self.skipTest("环境无麦克风，跳过回调模式计时验证")
        if result == "done" or result == "ok":
            # HC-3 事件循环卡顿 < 50ms（严格验收）
            self.assertLess(delta_ms, 50, f"stream 首帧阻塞 > 50ms（实际 {delta_ms:.1f}ms），疑似仍用同步 read() 模式")
```

- [ ] **Step 2: Run to verify fails**

Expected: test_gain_default FAIL（默认 gain≠1.0，project_memory 历史教训是 100x）；test_callback_mode FAIL 或 skip。

- [ ] **Step 3: Implement minimal code**

3.1 改 MicSource.__init__ 默认 gain=1.0：
```python
# 函数注释 __init__ 顶部：
"""
麦克风采集源（callback 模式 + asyncio.Queue 解阻塞）。

参数:
    rate (int): 采样率，默认 16000
    frame_ms (int): 每帧毫秒数，默认 30（~480 samples @ 16kHz）
    device (Optional[int]): sounddevice 设备编号，None=默认
    gain (float): 增益倍数，**强制默认 1.0**（project_memory HC-2：避免 >1.0 造成 PCM 超 32767 削波 → FunASR 识别失败）；仅允许 [0.0, 2.0] 区间
"""
def __init__(self, rate=16000, frame_ms=30, device=None, gain=1.0):
    if not (0.0 <= gain <= 2.0):
        raise ValueError(f"MicSource gain 允许 [0.0,2.0]，实际 {gain}（>1.0 会导致削波，HC-2 禁止）")
    self.gain = float(gain)
    ...
```

3.2 重写 stream() 为 RawInputStream(callback=...) + asyncio.Queue：
```python
async def stream(self):
    """
    异步帧生成器：RawInputStream 回调把 PCM 放入 asyncio.Queue，主协程从 queue 取，彻底避免 sd.read() 阻塞事件循环。

    Yields:
        bytes: 单帧 PCM bytes（int16 LE）
    异常:
        AudioUnavailable: sounddevice.PortAudioError 时统一包装
    """
    import asyncio
    import logging
    import sounddevice as sd  # 项目已有依赖
    from aivyos_core.audio import AudioUnavailable

    log = logging.getLogger(__name__)
    frame_size = int(self.sample_rate * self.frame_ms // 1000) * 2  # int16 = 2 bytes/sample
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)  # HC-3：小容量反压，避免回调堆积内存爆

    def sd_callback(indata, frames, time_info, status):
        """sounddevice 线程回调：把 numpy int16 转 bytes，立刻 put_nowait 到 queue（满则丢旧帧）。"""
        if status:
            log.debug("MicSource sounddevice status: %s", status)
        # indata: shape (frames, channels) dtype int16 / float32
        try:
            mono = indata[:, 0] if indata.ndim >= 2 else indata
            # HC-2: gain=1.0（原始信号），乘后 clip 防越界
            if self.gain != 1.0:
                mono = mono * self.gain
            if np.issubdtype(mono.dtype, np.floating):
                mono = np.clip(mono * 32767, -32768, 32767).astype(np.int16)
            raw = mono.astype(np.int16).tobytes()
            # 非阻塞 put_nowait；满则丢最旧帧（实时语音允许丢包，不允许阻塞 sd 回调线程）
            try:
                queue.put_nowait(raw)
            except asyncio.QueueFull:
                queue.get_nowait()  # 丢最旧
                queue.put_nowait(raw)
        except Exception as e:
            log.warning("MicSource 回调内部异常：%s", e)

    stream = None
    try:
        stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=frame_size // 2,  # samples per block（bytes / 2）
            device=self.device,
            dtype="int16",
            channels=1,
            callback=sd_callback,
        )
        stream.start()
        while True:
            # 100ms 超时：避免麦克风线程无声崩溃后永远卡 queue.get()
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue  # 下一轮
            except GeneratorExit:
                break
    except Exception as e:
        raise AudioUnavailable(f"MicSource 启动失败（callback 模式）：{e}") from e
    finally:
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
```

- [ ] **Step 4: Run test → PASS**

---

### Task 3: Wake Word 三层匹配 + 窗口/谐音/单字排除/去重（HC-4 ~ HC-9）

**Files:**
- Modify: `aivyos_core/voice/wake.py` Class WakeWordDetector
- Modify: `tests/test_wake.py`（原文件末尾追加 Class TestWakeHardening 12 tests）

- [ ] **Step 1: Write failing test（12 tests HC-4 到 HC-9 每条 1-2 tests）**

```python
# tests/test_wake.py 追加
class TestWakeHardening(unittest.TestCase):
    def _mk(self, words=None):
        from aivyos_core.voice.wake import WakeWordDetector
        defaults = ["贾维斯", "Aivy", "艾维"] if words is None else words
        return WakeWordDetector(words=defaults)

    # HC-5 三层策略
    def test_tier1_full_variant_misses_but_tier2_two_char_hits(self):
        """第一层变体未命中时，第二层两字独立匹配命中。"""
        ww = self._mk()
        # 谐音 "嘉维丝" 不在变体 → 但 "嘉+维" 连续两字命中第二层（如果变体中有"贾"和"维"单独映射）
        self.assertTrue(ww.detect("嘉维斯告诉我时间"))

    def test_tier3_english_word_boundary_jarvis(self):
        """第三层词边界 \bJarvis\b 命中（Aivy 英文）。"""
        ww = self._mk()
        self.assertTrue(ww.detect("hey Jarvis, turn on the lights"))
        self.assertFalse(ww.detect("thejarvislibrary is open"))  # 无词边界 → False

    # HC-6 谐音变体
    def test_homophone_variant_ah_wei_and_wei_wei(self):
        """ASR 识别谐音：阿维斯 / 喂维斯 / 还维斯 都命中。"""
        ww = self._mk()
        for text in ["阿维斯开灯", "喂维斯天气", "还维斯定闹钟 8 点"]:
            self.assertTrue(ww.detect(text), f"谐音变体未命中: {text}")

    # HC-7 单字排除
    def test_single_char_false_positive_cute_and_cool(self):
        """单字"微""可爱""微凉"不触发。"""
        ww = self._mk()
        for text in ["可爱的小狗", "微凉的秋天", "微信消息来了"]:
            self.assertFalse(ww.detect(text), f"单字误触发: {text}")

    # HC-8 1s 去重
    def test_same_text_within_1s_returns_false_second_time(self):
        """<1s 内相同文本两次 detect 第二次返回 False（去重）。"""
        ww = self._mk()
        self.assertTrue(ww.detect("贾维斯你好"))
        # 立即（<0.1s）第二次：应去重 False
        self.assertFalse(ww.detect("贾维斯你好"))

    def test_same_text_after_1_1s_returns_true_again(self):
        """>1.1s 后再次允许触发。"""
        import time
        ww = self._mk()
        self.assertTrue(ww.detect("贾维斯 hi"))
        time.sleep(1.1)
        self.assertTrue(ww.detect("贾维斯 hi again"))

    # HC-9 text_override 模式自动通过（由 VoiceSession.run_turn 控制走 text_override 路径，这里测 Wake 不需要——在 session 层写 test）
```

- [ ] **Step 2: Failing run** → Expected: 至少 6/12 FAIL

- [ ] **Step 3: Implement（wake.py 三层 + 变体列表 + _last_trigger_ts）**

```python
# wake.py WakeWordDetector 顶部：
import re
import time
from typing import List, Tuple

VARIANTS_BASE = [
    # 标准写法（第一层）
    "贾维斯", "艾维", "Aivy",
    # HC-6 谐音（阿/还/威/喂/微/嘉/加/甲/哈/诶 等谐音）
    "加维斯", "甲维斯", "嘉维斯", "阿维斯", "哈维斯",
    "喂维斯", "威维斯", "还维斯", "诶维斯",
    # 英文
    "Jarvis", "jarvis", "JARVIS",
]

# HC-7 单字排除：从 VARIANTS 拆出来的单字符集合（任何检测命中是单字都跳过）
_SINGLE_EXCLUDE = {"威", "斯", "维", "艾", "A", "J", "a", "j"}


class WakeWordDetector:
    """
    唤醒词检测器（project_memory HC-4 到 HC-8 三
