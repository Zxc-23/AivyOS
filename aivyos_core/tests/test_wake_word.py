"""语音唤醒功能全面测试脚本。

测试范围：
1. 不同环境噪音下的 VAD 检测成功率
2. 不同距离（音量衰减）下的唤醒效果
3. 不同语速/清晰度下的唤醒词识别
4. 系统响应时间（应 < 1s）
5. 误唤醒率测试

运行：python -m aivyos_core.tests.test_wake_word
"""

from __future__ import annotations

import json
import math
import os
import random
import struct
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aivyos_core.wake import WakeWordDetector
from aivyos_core.audio.vad import EnergyVAD, SileroVAD, _rms

def create_test_vad():
    """创建测试用 VAD 实例（优先 Silero，降级 Energy）。"""
    if SILERO_AVAILABLE:
        try:
            return SileroVAD(sample_rate=SAMPLE_RATE, threshold=0.5)
        except Exception:
            pass
    return EnergyVAD(threshold=200, auto_calibrate=True)

SILERO_AVAILABLE = True
try:
    _test_silero = SileroVAD()
    del _test_silero
except Exception:
    SILERO_AVAILABLE = False
    print("[WARN] Silero VAD 不可用，仅测试 EnergyVAD")

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000  # 960 bytes
NOISE_PRE_SECONDS = 2.0  # 预校准噪音时长
SPEECH_SECONDS = 1.0     # 语音段时长
NOISE_POST_SECONDS = 1.0  # 尾部噪音时长


@dataclass
class TestResult:
    category: str
    scenario: str
    metric: str
    value: float
    unit: str
    passed: bool
    detail: str = ""


@dataclass
class TestReport:
    started_at: str = ""
    completed_at: str = ""
    results: List[TestResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def add(self, category: str, scenario: str, metric: str, value: float,
            unit: str, passed: bool, detail: str = ""):
        self.results.append(TestResult(
            category=category, scenario=scenario, metric=metric,
            value=value, unit=unit, passed=passed, detail=detail,
        ))


# ================================================================
# 合成音频生成工具
# ================================================================

def generate_sine_wave(freq: float, duration_s: float,
                       amplitude: int = 16000) -> bytes:
    n = int(duration_s * SAMPLE_RATE)
    out = bytearray()
    for i in range(n):
        v = int(amplitude * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
        out += struct.pack("<h", max(-32768, min(32767, v)))
    return bytes(out)


def generate_noise(duration_s: float, amplitude: int = 500) -> bytes:
    n = int(duration_s * SAMPLE_RATE)
    out = bytearray()
    for _ in range(n):
        out += struct.pack("<h", random.randint(-amplitude, amplitude))
    return bytes(out)


def generate_speech_like(duration_s: float, amplitude: int = 8000,
                         pitch_hz: float = 200.0) -> bytes:
    n = int(duration_s * SAMPLE_RATE)
    out = bytearray()
    for i in range(n):
        t = i / SAMPLE_RATE
        envelope = 0.5 + 0.5 * math.sin(2 * math.pi * 3.0 * t)
        v = amplitude * envelope * (
            0.6 * math.sin(2 * math.pi * pitch_hz * t) +
            0.3 * math.sin(2 * math.pi * pitch_hz * 2 * t) +
            0.1 * math.sin(2 * math.pi * pitch_hz * 3 * t)
        )
        out += struct.pack("<h", int(max(-32768, min(32767, v))))
    return bytes(out)


def concatenate_audio(*segments: bytes) -> bytes:
    """拼接多个音频段。"""
    return b"".join(segments)


def split_frames(audio: bytes) -> List[bytes]:
    """将音频分割为 30ms 帧。"""
    frames = []
    for i in range(0, len(audio), FRAME_BYTES):
        chunk = audio[i:i + FRAME_BYTES]
        if len(chunk) == FRAME_BYTES:
            frames.append(chunk)
    return frames


def analyze_vad_frames(frames: List[bytes], vad: EnergyVAD,
                       pre_speech_frames: int, speech_frames: int) -> Dict[str, Any]:
    """分析 VAD 检测结果（帧级 + 话语级）。

    话语级评估：模拟 _capture_utterance 的行为——
    一旦 VAD 触发，持续捕获直到语音结束（静默超时）。
    """
    tp = fp = fn = tn = 0
    in_speech = False
    silence_count = 0
    captured_frames = 0
    speech_start_frame = -1
    speech_end_frame = -1
    consecutive_speech = 0

    for i, frame in enumerate(frames):
        is_speech = vad.is_speech(frame)
        in_speech_segment = pre_speech_frames <= i < pre_speech_frames + speech_frames

        # 帧级统计
        if is_speech and in_speech_segment:
            tp += 1
        elif is_speech and not in_speech_segment:
            fp += 1
        elif not is_speech and in_speech_segment:
            fn += 1
        else:
            tn += 1

        # 话语级模拟（3 帧连续判定 + 300ms 静默超时）
        if is_speech:
            consecutive_speech += 1
            silence_count = 0
            if not in_speech and consecutive_speech >= 2:
                in_speech = True
                speech_start_frame = i
            if in_speech:
                captured_frames += 1
                speech_end_frame = i
        else:
            consecutive_speech = 0
            if in_speech:
                silence_count += 1
                if silence_count >= 10:  # 300ms 静默超时
                    in_speech = False

    total_speech = max(1, speech_frames)
    total_silence = max(1, len(frames) - speech_frames)

    # 话语级：是否成功捕获语音段
    utterance_detected = speech_start_frame >= pre_speech_frames
    utterance_captured_frames = max(0, speech_end_frame - speech_start_frame + 1) if speech_start_frame >= 0 else 0

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "speech_detection_rate": tp / total_speech * 100,
        "false_alarm_rate": fp / total_silence * 100,
        "utterance_detected": utterance_detected,
        "utterance_captured_frames": utterance_captured_frames,
        "speech_start_frame": speech_start_frame,
        "threshold": vad.threshold,
    }


# ================================================================
# 测试 1：环境噪音 VAD 检测
# ================================================================

def test_vad_noise_environments(report: TestReport):
    """测试不同环境噪音下的 VAD 检测能力。"""
    print("\n" + "=" * 60)
    print("测试 1：环境噪音对 VAD 检测的影响")
    print("=" * 60)

    scenarios = [
        ("安静环境", 30),
        ("低噪音(办公室)", 150),
        ("中噪音(街道)", 400),
        ("高噪音(咖啡馆)", 800),
        ("极高噪音(工地)", 1500),
    ]

    for name, noise_amp in scenarios:
        # 生成 5 秒音频：2s 噪音 + 1s 语音 + 2s 噪音
        pre_noise = generate_noise(NOISE_PRE_SECONDS, amplitude=noise_amp)
        speech = generate_speech_like(SPEECH_SECONDS, amplitude=8000)
        post_noise = generate_noise(NOISE_POST_SECONDS, amplitude=noise_amp)
        audio = concatenate_audio(pre_noise, speech, post_noise)
        frames = split_frames(audio)

        vad = create_test_vad()
        pre_frames = int(NOISE_PRE_SECONDS * 1000 / FRAME_MS)
        sp_frames = int(SPEECH_SECONDS * 1000 / FRAME_MS)
        stats = analyze_vad_frames(frames, vad, pre_frames, sp_frames)

        label = vad.__class__.__name__
        print(f"\n  [{name}] (噪音幅度={noise_amp}, VAD={label}):")
        print(f"    校准后阈值: {stats['threshold']}")
        print(f"    帧级语音检测率: {stats['speech_detection_rate']:.1f}%")
        print(f"    帧级误报率: {stats['false_alarm_rate']:.1f}%")
        print(f"    话语级检测: {'✓ 成功' if stats['utterance_detected'] else '✗ 失败'} (起始帧={stats['speech_start_frame']}, 捕获={stats['utterance_captured_frames']}帧)")

        # 话语级检测是真实指标，帧级指标作为参考
        passed_utterance = stats['utterance_detected']
        passed_frame_alarm = stats['false_alarm_rate'] <= 50  # 放宽：高噪音可接受高误报

        report.add("VAD-噪音环境", name, "话语检测",
                    100 if stats['utterance_detected'] else 0, "%", passed_utterance,
                    f"阈值={stats['threshold']}, 起始帧={stats['speech_start_frame']}")
        report.add("VAD-噪音环境", name, "帧级误报率",
                    stats['false_alarm_rate'], "%", passed_frame_alarm,
                    f"TP={stats['tp']},FP={stats['fp']}")


# ================================================================
# 测试 2：距离（音量衰减）模拟
# ================================================================

def test_distance_attenuation(report: TestReport):
    """模拟不同距离下的语音衰减。"""
    print("\n" + "=" * 60)
    print("测试 2：距离（音量衰减）对检测的影响")
    print("=" * 60)

    distances = [
        ("0.5 米", 1.0),
        ("1.0 米", 0.5),
        ("2.0 米", 0.25),
        ("3.0 米", 0.125),
        ("5.0 米", 0.05),
    ]

    noise = generate_noise(NOISE_PRE_SECONDS + NOISE_POST_SECONDS, amplitude=200)
    base_speech = generate_speech_like(SPEECH_SECONDS, amplitude=8000)

    for dist_name, attenuation in distances:
        speech_amp = max(100, int(8000 * attenuation))
        speech = generate_speech_like(SPEECH_SECONDS, amplitude=speech_amp)
        audio = concatenate_audio(noise[:int(NOISE_PRE_SECONDS * SAMPLE_RATE * 2)],
                                 speech,
                                 noise[int(NOISE_PRE_SECONDS * SAMPLE_RATE * 2):])
        frames = split_frames(audio)

        vad = create_test_vad()
        pre_frames = int(NOISE_PRE_SECONDS * 1000 / FRAME_MS)
        sp_frames = int(SPEECH_SECONDS * 1000 / FRAME_MS)
        stats = analyze_vad_frames(frames, vad, pre_frames, sp_frames)

        speech_rms = _rms(speech[:FRAME_BYTES * 3])
        label = vad.__class__.__name__
        print(f"\n  [{dist_name}] (衰减={attenuation:.3f}, 语音RMS={speech_rms:.0f}, VAD={label}):")
        print(f"    校准阈值: {stats['threshold']}")
        print(f"    话语级检测: {'✓ 成功' if stats['utterance_detected'] else '✗ 失败'} (起始帧={stats['speech_start_frame']})")
        print(f"    帧级检测率: {stats['speech_detection_rate']:.1f}%")

        passed = stats['utterance_detected']
        report.add("VAD-距离衰减", dist_name, "话语检测",
                    100 if stats['utterance_detected'] else 0, "%", passed,
                    f"衰减={attenuation:.3f}, RMS={speech_rms:.0f}, 阈值={stats['threshold']}")


# ================================================================
# 测试 3：唤醒词检测准确率
# ================================================================

def test_wake_word_detection(report: TestReport):
    """测试唤醒词在不同文本下的检测能力。"""
    print("\n" + "=" * 60)
    print("测试 3：唤醒词检测准确率")
    print("=" * 60)

    detector = WakeWordDetector(["Aivy", "艾薇", "贾维斯", "小艾"])

    positive = [
        ("Aivy，帮我处理邮件", True, "英文+指令"),
        ("aivy 帮我看看日程", True, "小写+空格"),
        ("艾薇，今天天气怎么样", True, "中文+指令"),
        ("哎维帮我一下", True, "近音字-哎维"),
        ("爱维帮个忙", True, "近音字-爱维"),
        ("贾维斯，打开设置", True, "中文唤醒词2"),
        ("小艾，播放音乐", True, "中文唤醒词3"),
        ("AIvy，你好", True, "混合大小写"),
        ("hello aivy help me", True, "英文句子中包含"),
        ("aivy！在吗？", True, "感叹号分隔"),
    ]

    negative = [
        ("帮我处理邮件", False, "无唤醒词"),
        ("今天天气怎么样", False, "普通问句"),
        ("Avi 帮我处理", False, "相似但非唤醒词"),
        ("Jarvis 帮我", False, "英文拼写不同"),
        ("Ivy 帮我", False, "少一个字母"),
        ("aiv 帮我", False, "截断的唤醒词"),
        ("aviation weather", False, "完全不相关"),
        ("打开灯", False, "简短指令"),
        ("播放音乐", False, "媒体指令"),
        ("我最喜欢的颜色是蓝色", False, "闲聊"),
        # 新增：常见中文短句 - 验证 _char_level_match 不误触发
        ("可爱。", False, "常见词-可爱"),
        ("微凉。", False, "常见词-微凉"),
        ("你好世界", False, "问候+无唤醒字"),
        ("爱学习", False, "爱字单独出现"),
        ("微笑", False, "微字单独出现"),
        ("喂喂", False, "喂字但太嘈杂"),
        ("爱护环境", False, "爱字但无薇字"),
        ("微风拂面", False, "微字但无艾字"),
    ]

    print("\n  --- 正面测试（应命中）---")
    tp = tn = fp = fn = 0
    for text, expected, desc in positive:
        result = detector.detect(text)
        if result and expected:
            tp += 1
        elif not result and not expected:
            tn += 1
        elif result and not expected:
            fp += 1
        elif not result and expected:
            fn += 1
        status = "✓" if result == expected else "✗"
        print(f"    [{status}] '{text}' → {'触发' if result else '未触发'} — {desc}")

    print("\n  --- 负面测试（不应命中）---")
    for text, expected, desc in negative:
        result = detector.detect(text)
        if result and expected:
            tp += 1
        elif not result and not expected:
            tn += 1
        elif result and not expected:
            fp += 1
        elif not result and expected:
            fn += 1
        status = "✓" if result == expected else "✗"
        print(f"    [{status}] '{text}' → {'触发' if result else '未触发'} — {desc}")

    total = len(positive) + len(negative)
    accuracy = (tp + tn) / max(total, 1) * 100
    false_positive_rate = fp / max(len(negative), 1) * 100
    false_negative_rate = fn / max(len(positive), 1) * 100

    print(f"\n  汇总: 准确率={accuracy:.1f}%, 误报率={false_positive_rate:.1f}%, 漏报率={false_negative_rate:.1f}%")
    print(f"  TP={tp}, TN={tn}, FP={fp}, FN={fn}")

    report.add("唤醒词检测", "综合", "准确率", accuracy, "%", accuracy >= 90,
                f"TP={tp},TN={tn},FP={fp},FN={fn}")
    report.add("唤醒词检测", "综合", "误报率", false_positive_rate, "%",
                false_positive_rate <= 10, f"FP={fp}")
    report.add("唤醒词检测", "综合", "漏报率", false_negative_rate, "%",
                false_negative_rate <= 10, f"FN={fn}")


# ================================================================
# 测试 4：唤醒词剥离
# ================================================================

def test_wake_word_strip(report: TestReport):
    """测试唤醒词剥离功能。"""
    print("\n" + "=" * 60)
    print("测试 4：唤醒词剥离（strip）")
    print("=" * 60)

    detector = WakeWordDetector(["Aivy", "艾薇", "贾维斯"])

    cases = [
        ("Aivy，帮我处理邮件", "帮我处理邮件"),
        ("aivy 帮我看看日程", "帮我看看日程"),
        ("艾薇，今天天气怎么样", "今天天气怎么样"),
        ("贾维斯，打开设置", "打开设置"),
        ("帮我处理邮件", "帮我处理邮件"),
        ("Aivy帮我处理", "帮我处理"),
        ("Aivy！帮我一下", "帮我一下"),
        ("哎维帮个忙", "帮个忙"),
    ]

    passed = 0
    for text, expected in cases:
        result = detector.strip(text)
        ok = result == expected
        if ok:
            passed += 1
        status = "✓" if ok else "✗"
        print(f"    [{status}] '{text}' → '{result}' (期望 '{expected}')")

    accuracy = passed / len(cases) * 100
    report.add("唤醒词剥离", "剥离测试", "准确率", accuracy, "%", accuracy >= 90,
                f"{passed}/{len(cases)}")


# ================================================================
# 测试 5：响应时间基准
# ================================================================

def test_response_time(report: TestReport):
    """测试唤醒词检测和 VAD 的响应时间。"""
    print("\n" + "=" * 60)
    print("测试 5：响应时间基准")
    print("=" * 60)

    detector = WakeWordDetector(["Aivy", "艾薇", "贾维斯"])

    # 5a: WakeWordDetector.detect()
    print("\n  --- 5a: 唤醒词检测延迟 ---")
    test_texts = [
        ("短文本", "Aivy，帮我"),
        ("中文文本", "艾薇，今天天气怎么样啊，请告诉我明天需要穿什么衣服"),
        ("长英文", "aivy " * 50 + "help me please"),
        ("超长中文", "艾薇" * 50 + "你好世界"),
    ]
    for label, text in test_texts:
        start = time.perf_counter()
        for _ in range(10000):
            detector.detect(text)
        elapsed = (time.perf_counter() - start) / 10000 * 1000
        print(f"    [{label}] len={len(text)}: {elapsed:.4f} ms/次")
        report.add("响应时间", f"唤醒词检测-{label}", "延迟",
                    elapsed, "ms", elapsed < 1.0, f"len={len(text)}")

    # 5b: VAD is_speech()
    print("\n  --- 5b: VAD 检测延迟 ---")
    vad = create_test_vad()
    frames = [
        ("噪音", generate_noise(0.032, amplitude=100)),
        ("语音", generate_speech_like(0.032, amplitude=5000)),
        ("正弦波", generate_sine_wave(200, 0.032, amplitude=8000)),
    ]
    for label, frame in frames:
        start = time.perf_counter()
        for _ in range(10000):
            vad.is_speech(frame)
        elapsed = (time.perf_counter() - start) / 10000 * 1000
        rms = _rms(frame)
        print(f"    [{label}] RMS={rms:.0f}: {elapsed:.4f} ms/帧")
        report.add("响应时间", f"VAD检测-{label}", "延迟",
                    elapsed, "ms", elapsed < 0.5, f"RMS={rms:.0f}")

    # 5c: 完整唤醒链路模拟
    print("\n  --- 5c: 完整唤醒链路模拟 ---")
    warmup = " ".join(["warmup"] * 100)
    for _ in range(1000):
        detector.detect(warmup)

    latencies = []
    utterances = [
        "Aivy，帮我处理邮件",
        "艾薇，今天天气怎么样",
        "贾维斯，打开设置",
        "Aivy 帮我看看日程",
        "小艾，播放音乐",
    ] * 20

    for text in utterances:
        start = time.perf_counter()
        detected = detector.detect(text)
        if detected:
            detector.strip(text)
        latencies.append((time.perf_counter() - start) * 1000)

    avg = sum(latencies) / len(latencies)
    max_l = max(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    min_l = min(latencies)

    print(f"    唤醒链路 (n={len(latencies)}):")
    print(f"      平均: {avg:.4f} ms")
    print(f"      最小: {min_l:.4f} ms")
    print(f"      最大: {max_l:.4f} ms")
    print(f"      P95:  {p95:.4f} ms")
    print(f"      <1s:  {'✓' if avg < 1000 else '✗'}")

    report.add("响应时间", "完整唤醒链路", "平均延迟", avg, "ms", avg < 1000,
                f"avg={avg:.4f}, min={min_l:.4f}, max={max_l:.4f}")
    report.add("响应时间", "完整唤醒链路", "P95延迟", p95, "ms", p95 < 1000, "")


# ================================================================
# 测试 6：误唤醒综合测试
# ================================================================

def test_false_wake(report: TestReport):
    """误唤醒场景测试。"""
    print("\n" + "=" * 60)
    print("测试 6：误唤醒场景")
    print("=" * 60)

    detector = WakeWordDetector(["Aivy", "艾薇", "贾维斯"])

    tests = [
        ("我觉得 aivy 这个名字很好听", True, "句中含英文唤醒词"),
        ("这件事 aivy 处理得很好", True, "句中含唤醒词"),
        ("艾薇儿是加拿大歌手", True, "中文人名含唤醒词-可接受"),
        ("贾维斯·斯塔克是钢铁侠的管家", True, "英文人名含唤醒词-可接受"),
        ("帮我打开电脑", False, "普通指令"),
        ("今天下午开会", False, "日常对话"),
        ("天气不错", False, "闲聊"),
        ("打开灯", False, "简短指令"),
        ("播放音乐", False, "媒体指令"),
        ("aivory coast", False, "英文边界外"),
    ]

    triggered = 0
    for text, expected, desc in tests:
        result = detector.detect(text)
        if result:
            triggered += 1
        status = "✓" if result == expected else "✗"
        print(f"    [{status}] '{text}' → {'触发' if result else '未触发'} (期望 {'触发' if expected else '未触发'}) — {desc}")

    non_wake = [(t, e) for t, e, d in tests if not e]
    fw = sum(1 for t, e in non_wake if detector.detect(t))
    fw_rate = fw / max(len(non_wake), 1) * 100

    print(f"\n  误唤醒率: {fw_rate:.1f}% ({fw}/{len(non_wake)})")

    report.add("误唤醒率", "日常对话", "误唤醒率", fw_rate, "%", fw_rate <= 30,
                f"{fw}/{len(non_wake)}")


# ================================================================
# 主入口
# ================================================================

def run_all_tests() -> TestReport:
    report = TestReport(started_at=datetime.now().isoformat())

    print("=" * 60)
    print("  AivyOS 语音唤醒功能全面测试")
    print(f"  时间: {report.started_at}")
    print(f"  唤醒词: {WakeWordDetector().words}")
    print("=" * 60)

    for fn, name in [
        (test_vad_noise_environments, "VAD噪音环境"),
        (test_distance_attenuation, "距离衰减"),
        (test_wake_word_detection, "唤醒词检测"),
        (test_wake_word_strip, "唤醒词剥离"),
        (test_response_time, "响应时间"),
        (test_false_wake, "误唤醒"),
    ]:
        try:
            fn(report)
        except Exception as e:
            import traceback
            print(f"\n  [ERROR] {name} 测试失败: {e}")
            traceback.print_exc()

    total = len(report.results)
    passed = sum(1 for r in report.results if r.passed)
    failed = total - passed

    categories: Dict[str, Dict[str, int]] = {}
    for r in report.results:
        cat = r.category
        if cat not in categories:
            categories[cat] = {"total": 0, "passed": 0}
        categories[cat]["total"] += 1
        if r.passed:
            categories[cat]["passed"] += 1

    report.summary = {
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / max(total, 1) * 100, 1),
        "by_category": categories,
    }
    report.completed_at = datetime.now().isoformat()

    print("\n" + "=" * 60)
    print("  测试报告汇总")
    print("=" * 60)
    print(f"\n  总测试数: {total}")
    print(f"  通过: {passed}")
    print(f"  失败: {failed}")
    print(f"  通过率: {report.summary['pass_rate']}%")
    for cat, stats in categories.items():
        rate = stats["passed"] / max(stats["total"], 1) * 100
        print(f"    [{cat}] {stats['passed']}/{stats['total']} ({rate:.0f}%)")

    print("\n  --- 关键指标 ---")
    for r in report.results:
        if r.metric in ("检测准确率", "误报率", "漏报率", "平均延迟", "P95延迟",
                         "VAD检测率", "语音检测率"):
            st = "✓" if r.passed else "✗"
            print(f"    [{st}] {r.category}/{r.scenario}/{r.metric}: {r.value:.2f} {r.unit}")

    return report


def main():
    report = run_all_tests()

    report_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_reports")
    os.makedirs(report_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(report_dir, f"wake_word_test_{ts}.json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "started_at": report.started_at,
            "completed_at": report.completed_at,
            "summary": report.summary,
            "results": [asdict(r) for r in report.results],
        }, f, ensure_ascii=False, indent=2)

    print(f"\n  JSON 报告: {json_path}")

    md_lines = [
        "# AivyOS 语音唤醒功能测试报告",
        "",
        f"**测试时间**: {report.started_at}",
        f"**完成时间**: {report.completed_at}",
        "",
        "## 汇总",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 总测试数 | {report.summary['total_tests']} |",
        f"| 通过 | {report.summary['passed']} |",
        f"| 失败 | {report.summary['failed']} |",
        f"| 通过率 | {report.summary['pass_rate']}% |",
        "",
        "## 分类结果",
        "",
    ]
    for cat, stats in report.summary.get("by_category", {}).items():
        rate = stats["passed"] / max(stats["total"], 1) * 100
        md_lines.append(f"- **{cat}**: {stats['passed']}/{stats['total']} ({rate:.0f}%)")

    md_lines.extend(["", "## 关键指标", ""])
    for r in report.results:
        if r.metric in ("准确率", "误报率", "漏报率", "平均延迟", "P95延迟",
                        "VAD检测率", "语音检测率"):
            icon = "✅" if r.passed else "❌"
            md_lines.append(
                f"- {icon} **{r.scenario}**: {r.value:.2f} {r.unit} ({r.metric})"
            )

    md_lines.extend([
        "",
        "## 结论与建议",
        "",
        f"- 总体通过率 {report.summary['pass_rate']}%",
    ])

    if report.summary['pass_rate'] < 80:
        md_lines.append("- **建议**: 部分测试未通过，需要优化 VAD 阈值或唤醒词配置")
    else:
        md_lines.append("- **建议**: 测试整体通过，可进入下一阶段集成测试")

    md_path = json_path.replace(".json", ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print(f"  Markdown 报告: {md_path}")
    return 0 if report.summary["pass_rate"] >= 80 else 1


if __name__ == "__main__":
    sys.exit(main())