# AivyOS 知识代码图谱索引

> 本文件由 Agent 生成，用于向 QMind 知识库提供项目级结构化索引，便于跨文档、跨代码模块检索。

## 1. 项目元信息

- **项目名**：AivyOS — 个人专属 Jarvis 风格 AI 伴侣系统
- **仓库**：`F:\AivyOS\aivyos`（remote: https://github.com/Zxc-23/AivyOS.git）
- **工作区根**：`F:\AivyOS`（含设计文档、UI 稿、原型，但非 git 仓库）
- **当前分支**：`feature/comprehensive_test_v1.0`
- **管理文档**：`aivyos/说明文档.md`（全生命周期唯一管理载体，开工必读、完工必登记）
- **角色架构**：贾维斯 = AI Agent 调度执行者；用户 = 任务发布者；"Aivy" 仅为品牌名
- **测试基线**：607+ unittest 全绿 + `npx tsc --noEmit` exit 0 + Python import smoke

## 2. 目录结构真源

```
aivyos/
├── aivyos_core/           # Python AI 核心（零第三方依赖可运行）
│   ├── asr/               # ASR 抽象 + FunASR/Cloud/Mock 后端
│   ├── audio/             # 音频采集/播放/VAD/唤醒循环/WAV
│   ├── auth/              # 声纹/面部/活体/状态机/多用户认证
│   ├── chat/              # 对话引擎与会话持久化
│   ├── codegen/           # 一句话做软件：模板/Cline 适配/预览
│   ├── hotswap/           # 热交换：读写锁/Drain/熔断/快照/健康/快速启动
│   ├── ipc/               # JSON-RPC + TCP/NamedPipe
│   ├── knowledge/         # 知识卡片 CRUD/标签/语义检索/图谱/备份
│   ├── llm/               # LLM 路由、OpenAI 兼容客户端、Provider 注册表
│   ├── mcp/               # MCP 协议、客户端、八大 Server
│   ├── memory/            # Mem0 后端 + Simple JSONL 回退记忆
│   ├── net/               # WebSocket 工具
│   ├── scheduler/         # Cron/Event/Condition 主动调度器
│   ├── telemetry/         # 链路追踪/指标/日志/反馈闭环
│   ├── tray/              # 托盘 8 状态机/分级通知/文件拖拽路由
│   ├── tts/               # TTS 抽象 + CosyVoice/豆包/Mock 后端
│   ├── update/            # Ed25519/PKI/签名 manifest/增量/验签/回滚
│   ├── vector/            # VectorStore ABC + Mock + Chroma 适配
│   ├── vision/            # OCR/截图/图像理解
│   ├── voice/             # 语音会话链路（ASR→LLM→TTS）
│   ├── workbench/         # 协同工作台：cc-switch + Claude/Codex 双 CLI
│   └── workflow/          # mini_graph 状态图 + LangGraph 适配
├── shell/                 # Tauri 2.0 + React 18 + TypeScript
│   └── src/               # App.tsx / tray.ts / chat.ts bridge / styles.css
├── tests/                 # 73 个 unittest 文件
└── docs/                  # 项目文档、计划、规格
```

## 3. 关键入口与全局真源

| 文件 | 职责 |
|---|---|
| `aivyos_core/roles.py` | 角色名常量与 AGENT_REPORTING_RULES，禁止硬编码 |
| `aivyos_core/config.py` | 配置系统：默认值 + `~/.aivyos/config.yaml` + 环境变量 |
| `aivyos_core/models.py` | 数据模型：Message/Session/RouteDecision |
| `aivyos_core/server_entry.py` | IPC 服务入口，100+ JSON-RPC 方法注册 |
| `aivyos_core/cli.py` | CLI 文本输入入口 |
| `shell/src/App.tsx` | 前端主界面（对话/语音/知识/工作台/设置等 9 屏）|
| `shell/src/chat.ts` | 前端与 Python 后端的 IPC bridge |

## 4. 模块依赖与数据流

- **输入层**：CLI / 语音唤醒 / 悬浮输入 / Tauri 前端 IPC / 拖拽文件
- **调度层**：`wake.py` → `voice/session.py` → `chat/engine.py` → `llm/router.py`
- **执行层**：`mcp/` 工具、`workbench/` 双 CLI、`codegen/` 代码生成、`workflow/` 工作流
- **记忆层**：`memory/`（短期+长期）、`knowledge/`（卡片）、`memfs.py`（类文件系统记忆）
- **输出层**：`tts/`、`output.py`、`notification.py`、IPC 返回前端
- **支撑层**：`telemetry/`、`update/`、`hotswap/`、`recovery.py`

## 5. 测试目录索引

`tests/` 下 73 个测试文件覆盖：
配置、模型、人格、上下文、LLM 路由、记忆、MemFS、工作流、摘要、IPC、唤醒、VAD、ASR、TTS、语音会话、认证、视觉、多模态、输出路由、通知、MCP、调度器、自进化、需求解析、代码生成、预览、浏览器、端到端 Vibe Coding、托盘、更新签名、热交换、可观测性、知识卡片、向量库、工作台全链路。
