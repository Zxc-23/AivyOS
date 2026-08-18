"""配置系统：默认配置 + 用户配置覆盖 + 环境变量覆盖。

- 默认配置内嵌（零依赖可用，对应文档 §18.3 目录结构与 §4.1 路由策略）
- 用户配置：`~/.aivyos/config.yaml`（有 PyYAML）或 `~/.aivyos/config.json`
- 环境变量：AIVYOS_HOME / AIVYOS_LLM_MODE / AIVYOS_CLOUD_API_KEY 等
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULT_HOME = Path.home() / ".aivyos"

# 对应文档 §18.3 目录结构（Phase 1 先落地运行必需项）
DATA_DIRS = ("sessions", "memory", "memfs", "logs", "snapshots")

DEFAULT_CONFIG: Dict[str, Any] = {
    "home": str(DEFAULT_HOME),
    "llm": {
        # auto: 按 §4.1.3 路由（简单→本地，复杂/编程→云端优先，均不可达→mock 回退）
        # local / cloud / mock: 强制指定
        "mode": "auto",
        "local": {
            "base_url": "http://127.0.0.1:11434/v1",  # Ollama OpenAI 兼容端点；vLLM 同构
            "model": "qwen2.5:3b",   # 8GB 显存推荐；文档规格 qwen2.5:7b 需 12GB+（INT4）
            "api_key": None,
            "timeout_s": 60,
            "probe": True,             # 真实可用性探测（GET /models）
            "probe_timeout_s": 1.5,
            "probe_ttl_s": 20,         # 探测结果缓存时长
        },
        "cloud": {
            "base_url": "https://api.anthropic.com/v1",
            "api_key_env": "AIVYOS_CLOUD_API_KEY",
            "model": "claude-latest",
            "timeout_s": 120,
        },
        "mock": {"model": "mock-echo"},
    },
    "chat": {
        "context_window": 32768,   # §4.4.1 按 32K 模型分配；128K 模型可调大
        "history_turns": 12,       # 近期原始保留轮数（§4.4.2 近期保留）
        "summarize_from_turn": 12, # 超过该轮数启用中期摘要
        "summarize_backend": "auto",  # auto | naive | llm（§4.4.2 中期摘要）
        "system_prompt_tokens": 2048,
        "memory_tokens": 8192,
        "max_input_tokens": 4096,
        "output_reserve_tokens": 8192,
        "memory_top_k": 5,
    },
    "persona": {
        # §4.3 Big Five 人格参数
        "name": "Aivy",
        "openness": 0.8,
        "conscientiousness": 0.9,
        "extraversion": 0.3,
        "agreeableness": 0.7,
        "stability": 0.8,
        "tone": "professional",      # professional / casual / witty / serious
        "user_alias": "先生",
        "response_length": "balanced",  # concise / balanced / detailed
        "language": "zh-CN",
    },
    "memory": {
        "backend": "auto",           # auto | simple | mem0
        "extract_backend": "auto",   # auto | rules | llm（事实抽取：真实 LLM 可用则 LLM，否则规则）
        "simple_path": "memory.jsonl",
        "mem0_collection": "aivyos_memory",
        "mem0_embedder_model": "BAAI/bge-m3",
        "mem0_llm_model": "qwen2.5:7b",
        "auto_extract": True,        # 会话中自动抽取"记住"类事实
    },
    "ipc": {
        "transport": "auto",         # auto | tcp | named_pipe
        "host": "127.0.0.1",
        "port": 31701,
        "pipe_name": r"\\.\pipe\aivyos_core",
    },
    # ---- Week 2：语音链路（§3.1 感知输入 / §6.1 输出响应）----
    "audio": {
        "sample_rate": 16000,        # 16 kHz 单声道 PCM（文档 §3.1.1）
        "channels": 1,
        "frame_ms": 30,              # VAD 帧长 30ms（Silero v5 规格）
        "device": None,              # 麦克风设备名/索引；None=系统默认
        "input_backend": "auto",     # auto | mic | wav | synthetic
        "vad_backend": "auto",       # auto | silero | energy
        "wav_path": None,            # input_backend=wav 时指定输入文件
    },
    "asr": {
        "backend": "auto",           # auto | mock | funasr
        "model": "sensevoice-small", # SenseVoice/FunASR（§3.1.1）
        "language": "zh",
        "sample_rate": 16000,
    },
    "tts": {
        "backend": "auto",           # auto | mock | cosyvoice
        "model": "CosyVoice3-0.5B",  # §6.1 主引擎
        "sample_rate": 24000,        # CosyVoice 3 输出 24kHz
        "clone_seconds": 3,          # 3 秒音色克隆（§6.1）
        "clone_ref_path": None,      # 克隆参考音频 WAV 路径（§6.1 3 秒样本）
    },
    "voice": {
        "wake_words": ["Aivy", "艾维", "贾维斯"],
        "wake_required": False,      # True 时需唤醒词后才进入对话
        "silence_timeout_s": 3.0,    # 无语音超时退出
        "max_turn_s": 20.0,          # 单轮最长录音
    },
    "ws": {
        "port": 31702,               # WebSocket 实时通道（§16.3.2 风格）
        "host": "127.0.0.1",
    },
    # ---- Week 3：记忆持久化 + 工作流（§8 记忆连续性 / §4.5 Agent 编排）----
    "memfs": {
        "root": "memfs",             # Letta MemFS 根目录（§8.1，跨重启存活）
        "enabled": True,
    },
    "workflow": {
        "checkpoint_db": "checkpoints.sqlite",  # LangGraph 风格检查点（§4.5.2/§18.3）
        "thread_prefix": "wf_",
        "executor": "demo",          # demo | local（local：真实写文件/构建命令/HTTP 预览）
        "workspace": ".aivyos_workspace",  # local 执行器的工作区
        "build_command": None,       # local 构建命令（如 "python -m build"）；None=跳过构建
        "preview": True,             # local 预览：启动本地 HTTP 服务器
    },
    # ---- Week 4：专属认证（§9）----
    "auth": {
        "enabled": False,            # 开启后语音会话需通过认证
        "voice_threshold": 0.75,     # §9.2 声纹余弦阈值（EER<3% 中文场景）
        "face_threshold": 0.6,       # §9.2 面部余弦阈值
        "voice_backend": "auto",     # auto | simple | speechbrain（ECAPA-TDNN 192 维）
        "face_backend": "auto",      # auto | mock | insightface
        "liveness_enabled": True,    # §9.1 活体检测
        "visual_backend": "auto",    # auto | passive | cv2（视觉活体：cv2 拉普拉斯方差+人脸）
        "silent_reject": True,       # §9.1 失败处理：静默忽略，不暴露系统存在
        "users_dir": "users",        # 用户注册目录（声纹模板 + 人格配置，T6.7）
        "min_enroll_seconds": 3.0,   # 注册样本时长下限（§9.2：3-10 秒）
    },
    # ---- Phase 1 收尾：视觉 / 多模态 / 输出（§3.3 / §3.4 / §6.3）----
    "vision": {
        "ocr_backend": "auto",       # auto | mock | paddleocr
        "understand_backend": "auto",  # auto | mock | qwen2-vl
        "screenshot_backend": "auto",  # auto | mss | none
    },
    "multimodal": {
        "fusion_strategy": "late",   # §3.4 晚期融合
        "max_vision_tokens": 2048,
    },
    "output": {
        "default_channel": "text",   # text | voice | notification（§6.3 路由默认）
        "notify_levels": ["urgent", "important", "normal"],
        "notify_backend": "auto",    # auto | console | win_toast
    },
    "emotion": {
        "tags_enabled": True,        # §6.1 14 种细粒度情感标签 [laughter][breath]...
    },
    # ---- Phase 2 Week 5：MCP 工具层（§5）----
    "mcp": {
        "enabled_servers": ["filesystem", "shell", "code_exec", "office", "search", "screenshot", "memory", "browser"],
        "allowed_dirs": [],          # filesystem 白名单（相对 home 解析；空=仅 home）
        "scratch_dir": ".aivyos_mcp_scratch",  # code-exec/office 工作目录
        "shell_timeout_s": 30,
        "shell_max_output": 8192,
        "mrtr_ttl_s": 60,            # MRTR 确认有效期（§5.1.2）
        "mrtr_auto_approve": False,  # True 跳过确认（演示/测试）
        "docker_image": "python:3.11-slim",  # code-exec Docker 沙箱（可选）
    },
    "scheduler": {
        "timezone": "local",
        "tick_s": 5,                 # 调度循环 tick
    },
    # ---- Phase 2 Week 6：代码生成（§10 一句话做软件 / §11 预览）----
    "codegen": {
        "backend": "auto",           # auto | local | cline（Cline SDK 可选，§10.1 T5.1）
        "model": "qwen2.5:3b",       # Cline 后端模型（可选）
        "llm_enhance": False,        # local 后端生成后是否用 LLM 增强入口文件
        "deliver_via_mcp": False,    # True 时经 MCP filesystem fs_write 交付（§10.1 阶段5）
        "workspace": ".aivyos_workspace",  # 生成项目默认落盘目录
        "preview": {
            "enabled": True,         # 自动预览（§11）
            "viewport": "desktop",   # desktop | mobile | tablet（§11 多设备）
        },
    },
    # ---- Phase 3 Week 9：桌面端工程化（§12-15 托盘/热键/通知）----
    "tray": {
        "initial_state": "booting",     # 托盘状态机初始状态（§3.1）
        "double_click_ms": 300,         # 双击判定窗口（§3.4）
        "dnd": False,                   # 勿扰模式（§3.6）
        "notify_levels": ["urgent", "important", "normal", "silent"],
        "hotkeys": {
            "wake": "Alt+Space",        # 唤醒 AI（§1.3）
            "voice": "Alt+V",           # 语音输入开关
            "screenshot": "Alt+S",      # 截屏分析
            "quit": "Alt+Q",            # 快速退出/最小化
        },
        "autostart": True,              # 首次安装自动开启自启（§1.5）
        "close_to_tray": True,          # 关闭窗口 → 最小化到托盘（§1.4）
    },
    # ---- Phase 3 Week 10：自动更新与签名（§13 / T8.x）----
    "update": {
        "enabled": True,
        "check_interval_h": 6,          # §2.1 检测频率：每 6 小时
        "endpoint": "https://api.aivyos.local/update/{target}/{arch}/{current_version}",
        "current_version": "0.1.0",
        "min_required_version": "0.0.0",
        "keep_versions": 3,             # §2.3 保留 3 个版本
        "versions_dir": ".aivyos_versions",
        "quarantine_dir": ".aivyos_quarantine",
        "chunk_size_mb": 4,             # §1.3 分块 4MB（断点续传/增量基础）
        "max_timestamp_drift_s": 86400, # §1.6.2 时间戳新鲜度 ±24h
        "security_log": "security_events.jsonl",
    },
    # ---- Phase 3 Week 11：热交换与热启动（§3 / 深度规格 §2）----
    "hotswap": {
        "enabled": True,
        "drain_timeout_s": 30,          # §2.3 排空/请求超时
        "breaker_threshold": 3,         # §2.6 熔断阈值（连续失败次数）
        "breaker_cooldown_s": 3600,     # §2.6 熔断冷却
        "snapshots_dir": ".aivyos_snapshots",  # §3.2 状态快照目录
        "health_timeouts_s": {"llm": 10, "memory": 5, "tools": 10, "voice": 5, "scheduler": 3, "frontend": 5},
    },
    "logging": {"level": "INFO"},
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并两个字典（override 覆盖 base），返回新字典。"""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _load_json_or_yaml(path: Path) -> Dict[str, Any]:
    """优先 YAML（有 PyYAML），否则 JSON。两者都失败返回 {}。"""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass
    except Exception:
        pass
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _apply_env_overrides(cfg: Dict[str, Any]) -> None:
    """环境变量覆盖（最高优先级）。"""
    env = os.environ
    if env.get("AIVYOS_HOME"):
        cfg["home"] = env["AIVYOS_HOME"]
    if env.get("AIVYOS_LLM_MODE") in ("auto", "local", "cloud", "mock"):
        cfg["llm"]["mode"] = env["AIVYOS_LLM_MODE"]
    if env.get("AIVYOS_LLM_LOCAL_MODEL"):
        cfg["llm"]["local"]["model"] = env["AIVYOS_LLM_LOCAL_MODEL"]
    if env.get("AIVYOS_CLOUD_API_KEY"):
        cfg["llm"]["cloud"]["api_key"] = env["AIVYOS_CLOUD_API_KEY"]
    if env.get("AIVYOS_IPC_PORT"):
        cfg["ipc"]["port"] = int(env["AIVYOS_IPC_PORT"])
    if env.get("AIVYOS_PERSONA_TONE") in ("professional", "casual", "witty", "serious"):
        cfg["persona"]["tone"] = env["AIVYOS_PERSONA_TONE"]
    if env.get("AIVYOS_ASR_BACKEND") in ("auto", "mock", "funasr"):
        cfg["asr"]["backend"] = env["AIVYOS_ASR_BACKEND"]
    if env.get("AIVYOS_TTS_BACKEND") in ("auto", "mock", "cosyvoice"):
        cfg["tts"]["backend"] = env["AIVYOS_TTS_BACKEND"]
    if env.get("AIVYOS_AUDIO_INPUT") in ("auto", "mic", "wav", "synthetic"):
        cfg["audio"]["input_backend"] = env["AIVYOS_AUDIO_INPUT"]
    if env.get("AIVYOS_WS_PORT"):
        cfg["ws"]["port"] = int(env["AIVYOS_WS_PORT"])
    if env.get("AIVYOS_AUTH_ENABLED") in ("1", "true", "True"):
        cfg["auth"]["enabled"] = True
    if env.get("AIVYOS_AUTH_VOICE_THRESHOLD"):
        cfg["auth"]["voice_threshold"] = float(env["AIVYOS_AUTH_VOICE_THRESHOLD"])


def load_config(user_path: str | Path | None = None) -> Dict[str, Any]:
    """加载配置：默认值 → 用户配置文件 → 环境变量。

    user_path 缺省时依次尝试：$AIVYOS_HOME/config.yaml、$AIVYOS_HOME/config.json、
    ~/.aivyos/config.yaml、~/.aivyos/config.json。
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    candidates: list[Path] = []
    if user_path is not None:
        candidates.append(Path(user_path))
    else:
        home = Path(os.environ.get("AIVYOS_HOME", DEFAULT_HOME))
        for base in (home, DEFAULT_HOME):
            for name in ("config.yaml", "config.yml", "config.json"):
                candidates.append(base / name)

    for path in candidates:
        if path.exists():
            data = _load_json_or_yaml(path)
            cfg = deep_merge(cfg, data)

    _apply_env_overrides(cfg)
    return cfg


def ensure_home(cfg: Dict[str, Any]) -> Path:
    """按 §18.3 创建数据目录，返回 home 路径。"""
    home = Path(cfg["home"]).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    for d in DATA_DIRS:
        (home / d).mkdir(parents=True, exist_ok=True)
    return home
