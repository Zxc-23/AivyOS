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
            "model": "qwen2.5:7b",
            "api_key": None,
            "timeout_s": 60,
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
        "summarize_from_turn": 12, # 超过该轮数启用中期摘要（Week 1 为朴素截断占位）
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
