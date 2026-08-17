# AivyOS — 个人专属 AI 伴侣系统

> 技术规格见同级目录 `AivyOS_Technical_Engineering_Document.md`（V2.1）。
> 本仓库为 **Phase 1 · Week 1：核心对话闭环基础** 的可运行代码。

## 仓库结构

```
aivyos/
├── aivyos_core/            # Python AI 核心（零第三方依赖可运行）
│   ├── config.py           #   配置系统（默认值 + ~/.aivyos/config.yaml + 环境变量）
│   ├── models.py           #   数据模型（消息/会话/路由决策，§14.3 快照）
│   ├── persona.py          #   人格系统（Big Five + System Prompt 模板，§4.3）
│   ├── context.py          #   上下文管理（窗口分配/滑动窗口/归档，§4.4）
│   ├── llm/                #   LLM 层（§4.1）
│   │   ├── router.py       #     路由策略（复杂度估计 + 本地/云端/mock）
│   │   ├── openai_compat.py#     OpenAI 兼容客户端（Ollama/vLLM/云端通用）
│   │   └── mock.py         #     Mock 回退后端（离线可跑）
│   ├── memory/             #   记忆层（§4.2）
│   │   ├── manager.py      #     后端选择（mem0 优先，缺失自动降级）
│   │   ├── mem0_backend.py #     Mem0 + ChromaDB 适配
│   │   └── simple.py       #     JSONL 回退（零依赖）
│   ├── chat/engine.py      #   对话引擎（会话持久化 + 快照）
│   ├── ipc/                #   IPC 层（§16.2）
│   │   ├── protocol.py     #     JSON-RPC 信封 + 长度前缀帧
│   │   └── server.py       #     TCP 回环 / Windows Named Pipe 服务端
│   ├── cli.py              #   CLI 入口（§3.2 文本输入）
│   └── server_entry.py     #   IPC 服务入口
├── shell/                  # Tauri 2.0 桌面壳层骨架（需 Rust 后编译，§12）
├── tests/                  # unittest 测试（38 例，零第三方依赖）
├── scripts/                # 开发辅助脚本
├── pyproject.toml / requirements*.txt
└── README.md
```

## 快速开始

```powershell
# 1) 无需安装任何依赖即可运行（mock 模式）
python -m aivyos_core.cli --once "你好"

# 2) 交互式对话
python -m aivyos_core.cli

# 3) 运行测试（38 例）
python -m unittest discover -s tests -v
```

数据目录默认 `~/.aivyos`（可用 `AIVYOS_HOME` 环境变量覆盖，对应文档 §18.3）。

## 启用真实模型（优雅降级）

代码优先 + 优雅降级：未配置任何模型时链路照常运行（mock），配置后自动切换。

```powershell
# 方式 A：本地 Ollama（推荐，8GB 显存跑 qwen2.5:3b/7b INT4）
winget install Ollama.Ollama
ollama pull qwen2.5:3b
python -m aivyos_core.cli --mode local

# 方式 B：云端（BYOK）
$env:AIVYOS_CLOUD_API_KEY = "sk-..."
python -m aivyos_core.cli --mode auto   # 复杂/编程请求自动路由云端

# 方式 C：启动 IPC 服务（供 Tauri 壳层/外部客户端调用）
python -m aivyos_core.server_entry
python scripts\ipc_demo_client.py "你好"

# 方式 D：WebSocket 实时通道（T1.5，§16.3.2 风格）
python -m aivyos_core.ws_bridge
python scripts\ws_demo_client.py "你好"

# 方式 E：语音会话（采集→VAD→ASR→LLM→TTS→播放，全部可降级）
python -m aivyos_core.voice --once "你好" --wav out.wav   # 单轮 + 保存音频
python -m aivyos_core.voice                                 # 交互式语音对话
```

## 里程碑对应

| 本文档模块 | 技术文档章节 | 状态 |
| --- | --- | --- |
| LLM 路由（本地/云端/mock 三级） | §4.1.3 | ✅ 已实现（含失败降级） |
| 人格系统（Big Five 模板） | §4.3 | ✅ 已实现 |
| 上下文管理（窗口分配/压缩/归档） | §4.4 | ✅ 已实现（摘要为朴素占位，Week 3 升级） |
| 记忆（Mem0 适配 + JSON 回退） | §4.2 | ✅ 已实现（simple 后端完整，mem0 适配就绪） |
| 会话持久化与快照 | §14.3 | ✅ 已实现（JSON 原子写） |
| IPC（JSON-RPC + TCP/NamedPipe） | §16.2 | ✅ 已实现（TCP 全通，NamedPipe 需 pywin32） |
| 语音链路（采集→VAD→ASR→LLM→TTS→播放） | §3.1 / §6.1 | ✅ Week 2 已实现（silero/funasr/cosyvoice 适配 + 优雅降级） |
| 唤醒词检测（Aivy/贾维斯 可配置） | §3.1 | ✅ Week 2 已实现 |
| WebSocket 实时通道 | §16.3.2 | ✅ Week 2 已实现（RFC6455 零依赖，T1.5） |
| CLI 文本输入 | §3.2 | ✅ 已实现 |
| Tauri 2.0 壳层 | §12 | 🚧 骨架就绪（Rust 未安装，待 `cargo check`） |
| 声纹/面部认证 | §9 | ⏳ Week 4 |
| 托盘 / 热键 / 更新 / 热交换 | §12-15 | ⏳ Phase 3 |

## 设计要点

- **零依赖可运行**：核心链路仅用 Python 标准库；PyYAML/pywin32/sounddevice/silero-vad/funasr/cosyvoice/mem0 均为可选增强
- **四级降级**：真实后端失败 → mock（链路不断）；mem0 缺失 → JSON 记忆；NamedPipe 缺失 → TCP 回环；语音模型缺失 → 能量 VAD + 规则 ASR + 占位 TTS
- **路由诚实报告**：`route.fallback=true` 明确标注降级，不伪装真实推理
- **测试即文档**：65 个 unittest 覆盖配置/人格/上下文/路由/引擎/记忆/IPC/唤醒/VAD/ASR/TTS/语音会话/WebSocket 全链路
