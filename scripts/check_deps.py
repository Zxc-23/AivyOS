# -*- coding: utf-8 -*-
"""AivyOS 依赖一键检测：扫描可选依赖 / 工具 / 本地服务，输出缺失项的安装命令。

用法：
    python scripts/check_deps.py             # 全量检测 + 汇总安装命令
    python scripts/check_deps.py --json      # JSON 输出（供脚本消费）

原则（对应 docs/用户联调清单.md）：
    - 全部功能已"代码优先 + 优雅降级"，缺失依赖不影响核心链路
    - 本脚本仅告知"装了能获得什么真实能力 + 怎么装"
"""
import argparse
import importlib.util
import json
import shutil
import sys
import urllib.request

# 依赖组定义：name=组名, pip=安装命令, deps=[(模块名, 显示名, 说明)]
GROUPS = [
    {
        "name": "语音真实化（ASR/VAD/TTS，§3.1/§6.1）",
        "pip": "pip install funasr silero-vad cosyvoice",
        "deps": [
            ("funasr", "ASR SenseVoice"),
            ("silero_vad", "VAD Silero v5"),
            ("cosyvoice", "TTS 音色克隆（体积大）"),
        ],
    },
    {
        "name": "认证真实化（声纹/面部，§9.2）",
        "pip": "pip install speechbrain insightface",
        "deps": [
            ("speechbrain", "声纹 ECAPA-TDNN 192 维"),
            ("insightface", "面部识别 Buffalo_L 512 维"),
        ],
    },
    {
        "name": "记忆真实化（Mem0 后端，§4.2）",
        "pip": "pip install mem0 chromadb",
        "deps": [
            ("mem0", "Mem0 记忆后端"),
            ("chromadb", "向量数据库"),
        ],
    },
    {
        "name": "视觉真实化（OCR，§3.3）",
        "pip": "pip install paddleocr",
        "deps": [
            ("paddleocr", "OCR 文字识别"),
        ],
    },
    {
        "name": "浏览器自动化（Vibe Coding 预览验证，§11）",
        "pip": "pip install playwright browser-use && playwright install chromium",
        "deps": [
            ("playwright", "浏览器自动化（截图/监控/视口）"),
            ("browser_use", "自然语言驱动浏览器（§7.1）"),
        ],
    },
    {
        "name": "python-api 模板运行（§10.2）",
        "pip": "pip install fastapi uvicorn",
        "deps": [
            ("fastapi", "FastAPI 框架"),
            ("uvicorn", "ASGI 服务器"),
        ],
    },
    {
        "name": "Windows Named Pipe 传输（IPC，§16.2）",
        "pip": "pip install pywin32",
        "deps": [
            ("win32file", "Named Pipe（未装自动降级 TCP 回环）"),
        ],
    },
]

# 工具检测：(which 名, 显示名, 说明, 安装提示)
TOOLS = [
    ("node", "Node.js", "Cline SDK 代码生成后端（§10.1）", "https://nodejs.org"),
    ("npm", "npm", "前端构建/Node 模板 dev server", "随 Node.js 安装"),
    ("ollama", "Ollama", "本地 LLM 推理引擎", "winget install Ollama.Ollama"),
    ("gh", "GitHub CLI", "自动推送（scripts/gh_push.ps1）", "winget install GitHub.cli"),
]

OLLAMA_URL = "http://127.0.0.1:11434/api/tags"


def check_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def check_ollama_models() -> list:
    """探测本地 Ollama 已拉取的模型（§4.1.3 真实可用性）。"""
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=2) as r:
            data = json.loads(r.read().decode())
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def detect() -> dict:
    result = {
        "python": sys.version.split()[0],
        "groups": [],
        "tools": {},
        "ollama": {"running": False, "models": []},
        "missing_pip_commands": [],
    }
    for g in GROUPS:
        group_status = {"name": g["name"], "pip": g["pip"], "deps": []}
        missing = []
        for mod, label in [d for d in g["deps"]]:
            ok = check_module(mod)
            group_status["deps"].append({"module": mod, "label": label, "ok": ok})
            if not ok:
                missing.append(mod)
        if missing and g["pip"] not in result["missing_pip_commands"]:
            result["missing_pip_commands"].append(g["pip"])
        result["groups"].append(group_status)
    for exe, label, _desc, _how in TOOLS:
        result["tools"][exe] = shutil.which(exe) is not None
    result["ollama"]["models"] = check_ollama_models()
    result["ollama"]["running"] = bool(result["ollama"]["models"])
    return result


def render_plain(r: dict) -> str:
    lines = []
    lines.append("=" * 58)
    lines.append("AivyOS 依赖一键检测")
    lines.append(f"Python: {r['python']}")
    lines.append("=" * 58)
    for g in r["groups"]:
        ok_all = all(d["ok"] for d in g["deps"])
        tag = "OK " if ok_all else "缺 "
        lines.append(f"\n[{tag}] {g['name']}")
        for d in g["deps"]:
            mark = "✓" if d["ok"] else "✗"
            lines.append(f"    {mark} {d['module']:<14} {d['label']}")
        if not ok_all:
            lines.append(f"    安装: {g['pip']}")
    lines.append("\n--- 工具 ---")
    for exe, label, desc, how in TOOLS:
        mark = "✓" if r["tools"][exe] else "✗"
        lines.append(f"    {mark} {label:<12} {desc}  [{how}]")
    lines.append("\n--- 本地 LLM（Ollama） ---")
    if r["ollama"]["running"]:
        lines.append(f"    ✓ 运行中，模型: {', '.join(r['ollama']['models']) or '(无模型)'}")
    else:
        lines.append("    ✗ 未运行/未安装（`ollama serve` 或 winget install Ollama.Ollama）")
    lines.append("\n" + "=" * 58)
    lines.append("汇总 — 建议按需执行的安装命令：")
    if r["missing_pip_commands"]:
        for cmd in r["missing_pip_commands"]:
            lines.append(f"    {cmd}")
    else:
        lines.append("    （可选依赖全部就绪）")
    lines.append("说明：未安装项均有 mock/降级回退，核心链路不受影响。")
    lines.append("详细见 docs/用户联调清单.md")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="AivyOS 依赖一键检测")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()
    r = detect()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(render_plain(r))


if __name__ == "__main__":
    main()
