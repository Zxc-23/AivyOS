## 目录

**第一部分：基础架构**
- [1. 文档概述](#ch1)
- [2. 系统总体架构](#ch2)

**第二部分：核心层设计**
- [3. 感知输入层](#ch3)
- [4. 核心大脑层](#ch4)
- [5. 能力扩展层](#ch5)
- [6. 输出响应层](#ch6)

**第三部分：五大核心特性**
- [7. Vibe Coding](#ch7)
- [8. 记忆连续性](#ch8)
- [9. 专属认证](#ch9)
- [10. 一句话做软件](#ch10)
- [11. 自动预览](#ch11)

**第四部分：桌面端与工程化**
- [12. 桌面端架构](#ch12)
- [13. 自动更新与签名](#ch13)
- [14. 热启动与热交换](#ch14)
- [15. 托盘交互设计](#ch15)

**第五部分：工程规格**
- [16. 数据流与通信协议](#ch16)
- [17. 技术选型清单](#ch17)
- [18. 部署与硬件](#ch18)
- [19. 安全与隐私](#ch19)
- [20. 性能指标](#ch20)
- [21. 测试与可观测性](#ch21)
- [22. 开源复用矩阵](#ch22)

**第六部分：实施计划**
- [23. 开发计划与里程碑](#ch23)
- [24. 功能模块任务清单](#ch24)
- [25. 风险评估](#ch25)

---

# AivyOS

**个人专属AI伴侣系统 · 完整技术工程文档**

| 文档编号 | 版本 | 日期 | 编写视角 | 密级 |
| --- | --- | --- | --- | --- |
| AIVY-TDD-2026-001 | V2.1 | 2026-08-17 | AI系统工程师 | 个人使用 |

本文档整合了 AivyOS 全部技术规格，涵盖系统架构、四层核心设计、五大核心特性、桌面端工程化能力（托盘/热键/自动更新/签名/热交换）、部署规格、安全隐私、性能基准、测试策略、开源复用决策、开发计划及功能模块任务清单。所有模块经文档审查后统一修正，确保技术选型一致、数据指标准确。

> **V2.0 整合说明** — 本版本将原有 5 份独立文档（技术工程文档、核心特性规格、桌面端与热启动规格、签名/热交换/托盘深度规格、文档审查与开源复用建议）整合为一份完整文档，修正了 TTS 引擎选型、ASR 选型、记忆架构、Agent 编排等全部不一致之处，并新增功能模块任务清单。

<a id="ch1"></a>
## 1. 文档概述

### 1.1 项目背景

当前主流AI助理产品（Siri、Google Assistant、小爱同学等）普遍存在以下局限性：

- **隐私依赖云端** — 用户语音、文本、行为数据需上传至厂商服务器处理，存在数据泄露与合规风险。
- **能力受限** — 以简单指令执行为主，缺乏复杂推理、多步规划和自主决策能力。
- **无持续记忆** — 跨会话记忆能力薄弱，无法形成对用户偏好的深度理解。
- **缺乏个性化** — 通用AI人格无法适配不同用户的交互风格和情感需求。

受Marvel"贾维斯"（J.A.R.V.I.S.）概念启发，本项目旨在打造一个本地优先、隐私至上、持续进化的私人专属AI伴侣系统——**AivyOS**。

### 1.2 项目目标

| 目标维度 | 具体指标 | 对标参照 |
| --- | --- | --- |
| 智能水平 | 具备不输于 Codex 和 Claude Code 的编程/推理能力 | OpenAI Codex / Anthropic Claude Code |
| 记忆能力 | 跨会话长期记忆，支持情节/语义/程序三类记忆，重启后连续 | MemGPT / Letta MemFS |
| 自进化 | 基于用户反馈的持续学习与行为优化闭环 | Self-Refine / Reflexion / OpenJarvis |
| 人格定制 | 可自定义性格参数、语气、交互风格 | Character.AI / Replika |
| 主动服务 | 支持定时唤醒、事件触发、条件监控 | 贾维斯概念原型 |
| 隐私保护 | 核心推理与数据存储均在本地，最小化云端依赖 | Local-First Architecture |
| 工程化 | 原生桌面应用、自动更新、热交换零中断 | Tauri 2.0 + Ed25519 签名 |

### 1.3 设计理念

- **本地优先（Local-First）** — LLM推理、向量存储、记忆检索等核心环节在本地完成，仅在需要外部知识或进化优化时调用云端API。
- **隐私至上（Privacy-First）** — 用户行为数据、对话历史、偏好模型均在本地加密存储，不主动上传。
- **持续进化（Continuous Evolution）** — 构建反馈学习闭环，AI通过每次交互持续优化自身行为。
- **多模态感知（Multimodal Perception）** — 同时支持语音、文本、视觉三种感知通道，实现自然交互。
- **人格化交互（Personified Interaction）** — 可定制AI性格、语气、情感表达，打造"专属感"。
- **开源复用优先（Reuse-First）** — 优先复用成熟开源组件（Mem0/LangGraph/MCP/Cline/CosyVoice），减少约 60% 自研工作量。

### 1.4 文档结构

本文档分为六大部分，共 25 章：

| 部分 | 章节 | 内容 |
| --- | --- | --- |
| 第一部分：基础架构 | 第 1-2 章 | 文档概述、系统总体架构 |
| 第二部分：核心层设计 | 第 3-6 章 | 感知输入层、核心大脑层、能力扩展层、输出响应层 |
| 第三部分：五大核心特性 | 第 7-11 章 | Vibe Coding、记忆连续性、专属认证、一句话做软件、自动预览 |
| 第四部分：桌面端与工程化 | 第 12-15 章 | 桌面端架构、自动更新与签名、热启动与热交换、托盘交互设计 |
| 第五部分：工程规格 | 第 16-22 章 | 数据流、技术选型、部署、安全、性能、测试、开源复用 |
| 第六部分：实施计划 | 第 23-25 章 | 开发计划、功能模块任务清单、风险评估 |

<a id="ch2"></a>
## 2. 系统总体架构

### 2.1 架构总览

AivyOS采用**四层架构**设计，数据自上而下流动，同时存在一条反馈回路使系统持续进化。各层之间通过内部消息总线和事件驱动机制通信，层间耦合度低，可独立替换组件。外层包裹 Tauri 2.0 桌面壳，提供原生窗口、系统托盘、全局热键、自动更新等桌面能力。

> *图 1. AivyOS 系统架构总览（蓝色路径为反馈学习回路，外层为 Tauri 2.0 桌面壳）*

### 2.2 分层职责说明

| 层级 | 核心职责 | 关键组件 | 通信方式 |
| --- | --- | --- | --- |
| 感知输入层 | 多模态信号采集与预处理 | SenseVoice/FunASR、Silero VAD、PaddleOCR、LLaVA | 事件推送 → 消息总线 |
| 核心大脑层 | 推理决策、记忆管理、人格控制、工作流编排 | vLLM、Mem0+ChromaDB、LangGraph、人格配置 | 内部RPC + 消息总线 |
| 能力扩展层 | 外部能力接入与自主行为 | MCP Server 集群、进化引擎、调度器 | 事件驱动 + 异步队列 |
| 输出响应层 | 多模态输出与动作执行 | CosyVoice 3、动作执行器 | 回调 + 事件推送 |
| 桌面壳层 | 原生窗口、托盘、热键、更新 | Tauri 2.0 + React + Rust | IPC (Named Pipe/UDS) |

### 2.3 系统边界定义

- **内部系统**：四层之间的所有通信均在本地进程间完成，使用 Unix Domain Socket / Named Pipe + Redis Streams。
- **外部系统**：云端LLM API（可选，仅进化优化时）、互联网搜索、智能家居网关（HomeAssistant）、第三方API。
- **信任边界**：本地四层为可信域；外部API调用需经审批网关，敏感数据脱敏后传出。

<a id="ch3"></a>
## 3. 感知输入层设计

### 3.1 语音输入子系统

语音是贾维斯级别AI助理的核心交互通道。本子系统负责实时语音活动检测（VAD）、流式语音识别（ASR）及说话人识别。

#### 3.1.1 技术规格

| 参数 | 规格 | 备注 |
| --- | --- | --- |
| ASR引擎 | SenseVoice / FunASR (Paraformer) | 本地推理，支持流式，OpenAI兼容API |
| 模型大小 | ~0.5-1 GB（SenseVoice/Paraformer，FP16/INT8） | 按模型与精度选择 |
| 采样率 | 16 kHz / 24 kHz | 单声道 PCM |
| 识别延迟 | <300 ms（流式首包）/ <1s（完整句） | 本地GPU推理 |
| 字错率（CER） | <5%（中文普通话）/ <8%（中英混合） | 基于Common Voice测试集 |
| VAD引擎 | Silero VAD v5 | 帧长 30ms，支持静音检测 |
| 说话人识别 | SpeechBrain (ECAPA-TDNN / ReDimNet) | 统一API，多模型可选 |
| GPU显存占用 | ~1 GB（FP16推理） | 可与其他模块共享 |

#### 3.1.2 处理流程

```
音频流 (16kHz PCM)
    │
    ├─→ Silero VAD ──→ 静音段裁剪 / 断句
    │
    ├─→ SenseVoice 流式ASR ──→ 实时文本输出
    │
    └─→ ECAPA-TDNN ──→ 说话人ID (可选多用户)
    │
    └─→ 输出: { text, speaker_id, confidence, timestamp }
```

> **选型说明** — ASR 统一采用 SenseVoice/FunASR 生态（与 TTS 的 CosyVoice 同属阿里通义实验室），而非原方案的 Whisper。SenseVoice 支持中英混合识别且延迟更低，FunASR (Paraformer) 支持流式推理。说话人识别从 3D-Speaker 迁移到 SpeechBrain 统一 API，可平滑切换 ECAPA-TDNN / ReDimNet。

### 3.2 文本输入子系统

文本输入是基础交互通道，支持CLI、Web UI、API三种接入方式。系统对输入文本进行预处理（清洗、分词、意图预分类），再送入核心大脑层。

| 参数 | 规格 |
| --- | --- |
| 输入通道 | CLI / Tauri WebView / RESTful API / WebSocket |
| 编码格式 | UTF-8 |
| 最大输入长度 | 32,768 tokens（单次请求） |
| 预处理 | HTML清洗 / 空白规范化 / 敏感词过滤 |
| 意图预分类 | 基于轻量BERT模型，延迟 <50ms |

### 3.3 视觉输入子系统

视觉输入让AI"看"到用户屏幕或摄像头画面，支持OCR文字提取和图像内容理解。

| 参数 | 规格 | 备注 |
| --- | --- | --- |
| OCR引擎 | PaddleOCR (PP-OCRv4) | 支持中英文、版面分析 |
| 图像理解 | Qwen2.5-VL / Qwen3-VL | 图文匹配 + 视觉问答 |
| 屏幕捕获 | mss (Python) / DXcam (Windows) | 支持全屏/区域截取 |
| 处理延迟 | <500ms（OCR）/ <1.5s（VQA） | 取决于图像分辨率 |
| 支持格式 | PNG / JPEG / 截屏帧 | 最大 4K分辨率 |

### 3.4 多模态融合策略

当多个模态同时输入时（如语音+屏幕截图），系统采用**晚期融合（Late Fusion）**策略：

1. 各模态独立预处理，生成结构化中间表示。
2. 时间戳对齐：将语音识别结果与屏幕截图按时间窗口关联。
3. 统一编码：各模态中间表示拼接为统一上下文，送入LLM引擎。
4. LLM引擎在统一上下文中进行跨模态推理。

<a id="ch4"></a>
## 4. 核心大脑层设计

核心大脑层是整个系统的中枢，包含LLM引擎、长期记忆、人格系统、上下文管理和 Agent 编排五个子模块。其设计目标是让AI不仅能"回答问题"，还能"记住你"、"像你专属的助手"。

### 4.1 LLM引擎子系统

LLM引擎是推理与决策的核心。系统采用**混合模型策略**：日常对话使用本地模型（低延迟、隐私好），复杂推理任务可调用云端API（能力强）。

#### 4.1.1 模型选型矩阵

| 场景 | 模型 | 部署方式 | 上下文窗口 | 延迟 |
| --- | --- | --- | --- | --- |
| 日常对话 | Qwen2.5-7B / Llama 3.1-8B | 本地 (INT4量化) | 32K | ~200ms |
| 复杂推理 | Qwen2.5-72B / DeepSeek-V3 | 本地 (FP16/INT4) | 128K | ~1s |
| 编程任务 | Claude 最新旗舰（Sonnet/Opus 系列）/ DeepSeek-V3.x | 云端API (可选) | 200K | ~500ms |
| 视觉理解 | Qwen2.5-VL / Qwen3-VL | 本地 | 32K | ~800ms |
| 嵌入向量化 | BGE-M3 | 本地 | 8K | ~20ms |

#### 4.1.2 推理框架

| 框架 | 用途 | 吞吐量 | 量化支持 |
| --- | --- | --- | --- |
| vLLM | 高并发推理（PagedAttention） | ~50 tok/s (72B, A100) | AWQ / GPTQ / FP8 |
| llama.cpp | 低资源推理（CPU/GPU混合） | ~15 tok/s (7B, i7 CPU) | GGUF Q4_K_M ~ Q8_0 |
| Ollama | 快速部署与模型管理 | ~30 tok/s (7B, RTX 4090) | Q4_0 ~ FP16 |

#### 4.1.3 路由策略

```
def route_model(input_text, context):
    complexity = estimate_complexity(input_text, context)

    if complexity == "simple_chat":
        return LocalModel("qwen2.5-7b", quantization="int4")
    elif complexity == "complex_reasoning":
        if has_gpu(96):  # 96GB+ VRAM（如双 RTX 4090，INT4 量化）
            return LocalModel("qwen2.5-72b", quantization="int4")
        else:
            return CloudAPI("claude-latest")
    elif complexity == "coding":
        return CloudAPI("claude-latest")  # 编程优先云端
    elif complexity == "vision":
        return LocalModel("qwen2.5-vl-7b")
```

> **注** — 72B FP16 需约 160GB 显存（多卡），本地通常以 INT4/INT8 量化运行（≥48GB）；48GB 级别单机建议上限为 32B 模型。

### 4.2 长期记忆子系统（Mem0 + ChromaDB）

长期记忆是AI从"工具"进化为"贾维斯"的关键。系统支持三类记忆模型：情节记忆（事件和交互历史）、语义记忆（用户偏好、事实知识）、程序记忆（操作流程和技能）。

#### 4.2.1 技术规格

记忆系统采用 **Mem0**（61.6K stars，Apache-2.0）作为记忆管理层，负责自动从对话中抽取事实、去重、分类和混合检索；**ChromaDB** 作为底层向量存储后端。这替代了原方案中手动 BGE-M3 编码 + ChromaDB 写入 + BM25 检索 + RRF 融合的全部自研逻辑。

| 参数 | 规格 | 备注 |
| --- | --- | --- |
| 记忆管理层 | Mem0 SDK 2.0 | 自动抽取事实、混合检索、永不覆写保留历史 |
| 向量数据库 | ChromaDB（作为 Mem0 后端） | 嵌入式，无需独立服务 |
| 嵌入模型 | BGE-M3 (1024维) | Mem0 内部调用，无需手动编码 |
| 检索策略 | Mem0 混合检索：语义 + 关键词 + 实体 | 单通道抽取，写入延迟降低~50% |
| 存储容量 | ~10万条记忆 / 1GB | 估算值（取决于记忆长度与向量维度） |
| 检索延迟 | <50ms (10万条) | 本地SSD |
| 记忆更新 | Mem0 自动去重 + 合并 + TTL过期 | 无需手动合并去重 |

#### 4.2.2 记忆写入与检索流程

```
from mem0 import Memory

config = {
    "vector_store": {
        "provider": "chroma",
        "config": {"collection_name": "aivyos_memory", "path": "./.aivyos/memory_db"}
    },
    "embedder": {"provider": "huggingface", "config": {"model": "BAAI/bge-m3"}},
    "llm": {"provider": "ollama", "config": {"model": "qwen2.5:7b"}}
}

memory = Memory.from_config(config)

def write_memory(text, user_id="owner", metadata=None):
    memory.add(messages=text, user_id=user_id, metadata=metadata or {})

def retrieve_memory(query, user_id="owner", top_k=5):
    return memory.search(query=query, user_id=user_id, limit=top_k)
```

> **对比原方案** — 原方案需手动实现 BGE-M3 编码、ChromaDB 写入、BM25 检索、RRF 融合、去重合并等全部逻辑（约 200 行代码）。Mem0 将这些封装为 `add()` / `search()` 两个 API，减少约 70% 记忆层自研代码。

### 4.3 人格系统

人格系统让AI拥有可定制的性格、语气和交互风格，而非千篇一律的通用助手。

| 参数维度 | 取值范围 | 示例 |
| --- | --- | --- |
| 开放性 (Openness) | 0.0 – 1.0 | 0.8 = 喜欢探索新想法 |
| 尽责性 (Conscientiousness) | 0.0 – 1.0 | 0.9 = 严谨细致 |
| 外向性 (Extraversion) | 0.0 – 1.0 | 0.3 = 内敛沉稳 |
| 宜人性 (Agreeableness) | 0.0 – 1.0 | 0.7 = 友好合作 |
| 情绪稳定性 (Neuroticism) | 0.0 – 1.0 | 0.2 = 冷静理性 |
| 语气风格 | 枚举 | professional / casual / witty / serious |
| 称呼方式 | 字符串 | "先生" / "老板" / 用户昵称 |
| 回复长度偏好 | 枚举 | concise / balanced / detailed |

人格参数通过 System Prompt 注入 LLM，在每次推理时生效：

```
PERSONA_TEMPLATE = """
你是 {name}，用户的私人AI助理。

## 性格参数 (Big Five)
- 开放性: {openness} / 1.0
- 尽责性: {conscientiousness} / 1.0
- 外向性: {extraversion} / 1.0
- 宜人性: {agreeableness} / 1.0
- 情绪稳定性: {stability} / 1.0

## 交互风格
- 语气: {tone}
- 称呼用户为: {user_alias}
- 回复长度: {response_length}
- 语言: {language}

## 行为准则
1. 始终记住用户偏好和历史交互
2. 主动提供有帮助的建议
3. 不确定时坦诚说明，不编造信息
"""
```

### 4.4 上下文管理

#### 4.4.1 上下文窗口分配

| 组成 | Token分配 (128K窗口) | 说明 |
| --- | --- | --- |
| System Prompt + 人格 | ~2K | 固定，每次对话注入 |
| 检索记忆（长期） | ~8K | 从向量库检索的相关记忆 |
| 对话历史（短期） | ~32K | 滑动窗口，保留最近交互 |
| 当前用户输入 | ~4K | 本次请求内容 |
| 工具调用上下文 | ~16K | 工具执行结果 |
| 输出预留 | ~66K | LLM生成空间（长文档/代码生成预留，日常场景可动态回收） |

> **注** — 上表按 128K 上下文窗口模型分配；路由到 32K 窗口模型（如 Qwen2.5-7B）时，对话历史压缩与远期归档策略更激进，输出预留收缩至 ~8K，保证窗口不溢出。

#### 4.4.2 上下文压缩策略

1. **近期保留** — 最近3轮对话原样保留。
2. **中期摘要** — 4-10轮前的对话压缩为摘要（每3轮压缩为1段摘要）。
3. **远期归档** — 10轮以前的对话提取关键信息写入长期记忆，从上下文中移除。

### 4.5 Agent 编排框架（LangGraph）

Agent 编排框架负责将 LLM 引擎、记忆系统、工具调用串联为可执行的工作流。AivyOS 采用 **LangGraph** 作为核心编排框架，以类型化状态图表达多步工作流，内置检查点支持失败恢复和断点续传。

#### 4.5.1 选型理由

| 维度 | LangGraph（选用） | CrewAI | OpenAI Agents SDK |
| --- | --- | --- | --- |
| 编排模型 | **类型化状态图** | 角色化团队 | Handoff 链 |
| 状态持久化 | **内置检查点（SQLite）** | 有限 | 有限 |
| 模型无关 | **是（vLLM + 云端均可）** | 是 | 仅 OpenAI |
| 记忆集成 | **LangMem / Mem0 原生** | 需自接 | 需自接 |
| 失败恢复 | **从最后检查点续传** | 重跑 | 重跑 |
| 许可证 | MIT | MIT | MIT |

#### 4.5.2 工作流状态图设计

```
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TypedDict

class VibeCodingState(TypedDict):
    user_request: str
    spec: dict
    files: dict
    preview_url: str
    build_failed: bool
    errors: list

workflow = StateGraph(VibeCodingState)
workflow.add_node("understand", understand_requirement)
workflow.add_node("plan", plan_project)
workflow.add_node("generate", generate_code)
workflow.add_node("deliver", deliver_to_ide)
workflow.add_node("build", build_and_test)
workflow.add_node("preview", auto_preview)
workflow.add_node("save_memory", save_session)

workflow.set_entry_point("understand")
workflow.add_edge("understand", "plan")
workflow.add_edge("plan", "generate")
workflow.add_edge("generate", "deliver")
workflow.add_edge("deliver", "build")
workflow.add_conditional_edges("build",
    lambda s: "generate" if s["build_failed"] else "preview")
workflow.add_edge("preview", "save_memory")
workflow.add_edge("save_memory", END)

app = workflow.compile(checkpointer=SqliteSaver.from_conn_string(
    "./.aivyos/checkpoints.sqlite"
))
```

> **个人使用简化** — 单机场景下检查点存本地 SQLite 即可，无需 LangSmith 云端 trace。工作流失败后从最后检查点续传，无需从头重跑。

<a id="ch5"></a>
## 5. 能力扩展层设计

能力扩展层让AI从"只会聊天"进化为"能做事"的贾维斯。包含工具调用、自我进化和主动调度三个子系统。

### 5.1 工具调用子系统（MCP 架构）

系统采用 **MCP（Model Context Protocol）2026-07-28 规范**作为统一工具调用层。每个工具能力封装为独立 MCP Server，LLM 通过标准协议自动发现并调用工具，无需自研工具注册机制。

#### 5.1.1 MCP Server 架构

```
from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("aivyos-filesystem")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="file_read", description="读取本地文件",
             inputSchema={"type": "object",
                          "properties": {"path": {"type": "string"}},
                          "required": ["path"]}),
        Tool(name="file_write", description="写入本地文件（需确认）",
             inputSchema={"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "content": {"type": "string"}},
                          "required": ["path", "content"]}),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "file_read":
        content = Path(arguments["path"]).read_text()
        return [TextContent(type="text", text=content)]
    elif name == "file_write":
        Path(arguments["path"]).write_text(arguments["content"])
        return [TextContent(type="text", text=f"已写入: {arguments['path']}")]
```

#### 5.1.2 MCP Server 清单

| MCP Server | 功能描述 | 权限级别 | 来源 |
| --- | --- | --- | --- |
| filesystem | 文件读写（路径白名单） | 低（读）/ 高（写需确认） | 官方 MCP Server |
| browser | 浏览器自动化（browser-use 驱动） | 低 — 只读为主 | 自封装 |
| code-exec | Python 本地执行 | 高 — 需确认 | 自封装 |
| shell | 系统命令执行 | 高 — 需确认 | 自封装 |
| memory | Mem0 记忆读写 | 低 | 自封装 |
| search | SearXNG 搜索 | 低 — 只读 | 自封装 |
| screenshot | 屏幕截图 | 低 | 自封装 |
| office | Word/Excel/PPT 生成 | 低 | 自封装 |

> **安全提示** — 高权限工具（code-exec、shell、file_write）通过 MCP 的 **MRTR（Multi Round-Trip Requests）**机制触发用户确认：Server 返回 `resultType: "input_required"`，客户端展示工具名称、参数和预期影响，用户批准后带答案重试请求；用户拒绝或确认超时默认拒绝执行，并写入安全审计日志。

### 5.2 自我进化子系统

自我进化是AivyOS区别于普通AI助理的核心特性，通过反馈学习闭环让AI越用越懂用户。

#### 5.2.1 进化维度

- **偏好学习** — 记录用户对回复的隐式反馈（采纳/修改/拒绝），训练偏好模型。
- **提示词优化** — 基于交互效果自动优化System Prompt中的行为准则。
- **工具使用优化** — 学习用户常用的工具组合和参数偏好。
- **知识更新** — 从交互中提取新知识写入语义记忆。
- **行为模式学习** — 识别用户的日常行为模式，用于主动调度。

#### 5.2.2 LLM 引导的 Spec 搜索（参考 OpenJarvis）

自进化的核心难题是"如何让本地模型越用越聪明而不退化"。AivyOS 借鉴 **OpenJarvis**（Apache-2.0）的 LLM-guided spec search 机制：云端强模型作为"教师"，在搜索时读取本地运行 trace、诊断失败簇、跨原语提出配置编辑建议，通过 gate（默认 1% 容差）只接受不退化的修改，优化后完全本地运行。

```
class SpecSearchEngine:
    def __init__(self, local_llm, cloud_llm, tolerance=0.01):
        self.local = local_llm
        self.cloud = cloud_llm
        self.tolerance = tolerance

    async def search_and_optimize(self, spec: dict, eval_set: list):
        baseline = await self._evaluate(self.local, spec, eval_set)
        traces = self._collect_traces(spec, eval_set)
        failure_clusters = await self.cloud.analyze(traces)
        candidates = await self.cloud.propose_edits(spec, failure_clusters)

        for candidate in candidates:
            score = await self._evaluate(self.local, candidate, eval_set)
            if score >= baseline * (1 - self.tolerance):
                spec = candidate
                baseline = score
            else:
                print(f"[进化] 拒绝退化，score: {score:.4f} < {baseline:.4f}")
        return spec
```

> **个人使用简化** — 云端教师仅在"进化"时调用（如每周一次），日常运行完全本地。OpenJarvis 报告该机制可恢复 13-32pp 的云-本地差距。

### 5.3 主动调度子系统

主动调度让AI不只在用户提问时才响应，还能**主动**提供服务——这正是贾维斯区别于普通助手的关键。

| 触发类型 | 机制 | 示例 |
| --- | --- | --- |
| 定时触发 | Cron表达式调度 | 每天 09:00 汇报今日日程 |
| 事件触发 | 监听系统/外部事件 | 收到邮件时主动提醒 |
| 条件触发 | 周期性检查条件是否满足 | CPU使用率>90%时告警 |
| 行为预测 | 基于行为模式预测用户需求 | 检测到打开IDE，准备项目上下文 |

<a id="ch6"></a>
## 6. 输出响应层设计

### 6.1 语音合成子系统（CosyVoice 3）

语音合成让AI像贾维斯一样"开口说话"，是沉浸式交互的关键。采用 **CosyVoice 3**（2026 年开源 TTS SOTA，Apache-2.0）作为主引擎，GPT-SoVITS 保留为备选。

| 参数 | 规格 | 备注 |
| --- | --- | --- |
| TTS引擎（主） | **CosyVoice 3** (0.5B) | LibriSpeech test-clean SOTA（对比基线以官方发布为准） |
| TTS引擎（备） | GPT-SoVITS V4 | 保留为备选，可插拔切换 |
| 音色克隆 | 3秒样本 zero-shot 克隆 | 比 GPT-SoVITS 的5秒更短 |
| 情感控制 | 14种细粒度标签（[laughter][breath]等） | 适合 AI 伴侣情感表达 |
| 合成延迟 | <150ms（首音频帧） | vLLM/TRT-LLM 加速 |
| 多语言 | 中英日韩等 9 种语言 + 18 种方言 | — |
| 采样率 | 24 kHz / 48 kHz | 16-bit PCM |
| GPU占用 | ~2 GB（推理） | 可与ASR共享 |

> **选型升级理由** — CosyVoice 3 在 LibriSpeech test-clean 上达到 SOTA，首包延迟仅 150ms，3 秒克隆样本，14 种细粒度情感标签适合"AI 伴侣"的情感表达需求。Apache-2.0 许可证可商用。可参考 OmniVoice Studio 的多引擎统一架构实现 TTS 引擎可插拔。

### 6.2 动作执行子系统

| 执行域 | 能力 | 接入方式 |
| --- | --- | --- |
| 智能家居 | 灯光/空调/窗帘/安防控制 | HomeAssistant REST API |
| 系统操作 | 文件管理/进程控制/系统设置 | MCP shell/filesystem Server |
| 消息通信 | 邮件/即时消息/通知推送 | SMTP/IMAP + Webhook |
| 代码部署 | Git操作/CI触发/容器管理 | Git CLI + Docker API |
| 日程管理 | 日历查询/创建/修改 | CalDAV / Graph API |

### 6.3 多模态输出策略

- **语音交互场景** — 语音输入触发语音输出（全双工对话）。
- **文本交互场景** — 文本输入触发文本输出，复杂结果辅以可视化。
- **主动通知场景** — 低紧急度用文本通知，高紧急度用语音播报。
- **代码/文档场景** — 文本输出 + 文件写入，在IDE或文件管理器中展示。

<a id="ch7"></a>
## 7. 核心特性一：Vibe Coding 氛围编程 `核心`

**"Vibe Coding"**是指AI以沉浸式方式参与完整的编程工作流——从理解需求、生成代码、打开浏览器预览、到交付到IDE，全程无需用户手动切换工具。AI同时掌握浏览器、Office文档和IDE三个执行域，形成无缝的工作氛围。

### 7.1 浏览器自动化（browser-use + Playwright）

采用 **browser-use**（95K+ stars）实现自然语言驱动的浏览器操控，底层基于 Playwright。AI 用自然语言描述任务即可完成打开页面、填表、点击、截图、抓取数据，无需编写复杂的选择器脚本。

| 参数 | 规格 | 备注 |
| --- | --- | --- |
| 驱动方式（主） | **browser-use（自然语言）** | AI 描述任务→自动规划浏览器操作 |
| 底层引擎 | Playwright (Python) | browser-use 底层调用，可降级直接使用 |
| 浏览器模式 | 有头模式（可见）/ 无头模式（后台） | 用户可见预览用有头，数据抓取用无头 |
| 页面操作 | 自然语言描述 + 视觉定位 | browser-use 自动元素定位 |
| Cookie/Session | 持久化浏览器上下文 | storageState保存登录态 |

### 7.2 Office 自动化

| 文档类型 | 库 | 能力 |
| --- | --- | --- |
| Word (.docx) | python-docx | 创建/编辑段落、表格、图片、样式 |
| Excel (.xlsx) | openpyxl | 创建/编辑单元格、公式、图表 |
| PPT (.pptx) | python-pptx | 创建/编辑幻灯片、文本框、形状 |
| PDF | reportlab / PyPDF2 | 生成PDF报告 / 合并拆分 |
| Markdown | Python原生 | 生成.md文档 |

所有 Office 能力封装为 MCP Office Server，LLM 通过标准 MCP 协议调用。

### 7.3 IDE 集成（Cline SDK）

采用 **Cline SDK**（Apache-2.0，累计安装 8M+）作为核心代码生成与写入引擎，支持 Plan/Act 双模式和多模型 BYOK。Cline SDK 可直接嵌入 AivyOS，省去自研代码生成管线的大部分工作。

| 集成维度 | 技术方案 | 能力 |
| --- | --- | --- |
| 代码生成引擎（主） | **Cline SDK（可嵌入）** | Plan/Act双模式、多文件编辑、多模型BYOK |
| 文件系统 | MCP filesystem Server | 创建/修改/删除文件和目录 |
| VS Code Extension | VS Code Extension API | 在编辑器中打开文件、设置光标、显示Diff |
| LSP协议 | Language Server Protocol | 代码诊断、跳转定义、自动补全 |
| 终端集成 | VS Code Integrated Terminal API | 在IDE终端中执行命令、运行构建 |
| 多IDE支持 | Cursor / Windsurf / Trae 兼容 | 基于标准文件系统+LSP |

### 7.4 完整工作流编排（LangGraph 状态图）

Vibe Coding 的核心是**工作流引擎**——基于 LangGraph 状态图，将多个步骤编排为自动化的流水线。每个节点执行后自动保存检查点到本地 SQLite，失败可从断点恢复，构建失败时通过条件边自动回到生成阶段修复。

```
节点：understand → plan → generate（Cline Act 模式）→ deliver（MCP filesystem 写入）→ build（MCP shell 构建）→ preview（browser-use 预览）→ save_memory（Mem0 保存记忆）
条件边：build 失败 → 回环 generate 自动修复；成功 → preview
检查点：SqliteSaver → ~/.aivyos/checkpoints.sqlite（每节点执行后自动保存）
```
（状态图完整定义与代码见 §4.5.2，两处共用同一 VibeCodingState 定义，避免重复维护。）

<a id="ch8"></a>
## 8. 核心特性二：记忆连续性 `核心`

重启后AI"醒来"时，仍然记得上次在做什么、用户偏好是什么、正在进行哪个项目——就像贾维斯从不"失忆"。

### 8.1 三层持久化架构

记忆连续性采用三层架构：**Letta MemFS**（类文件系统持久化记忆，Agent 自主管理记忆生命周期，跨重启存活）+ **Mem0**（向量记忆层，自动抽取事实）+ **LangGraph 检查点**（工作流状态持久化，断点续传）。

| 数据类别 | 存储位置 | 保存时机 | 恢复时机 |
| --- | --- | --- | --- |
| 长期记忆（事实/偏好/技能） | Mem0 → ChromaDB (磁盘) | Mem0 自动抽取写入 | 启动时 Mem0 加载索引 |
| Agent 记忆文件系统 | Letta MemFS | Agent 自主调用记忆工具 | 启动时 MemFS 自动恢复 |
| 工作流状态 | LangGraph 检查点 (SQLite) | 每个图节点执行后自动保存 | 启动时从最后检查点恢复 |
| 工作区状态 | workspace_snapshot.json | 任务切换/定时保存 | 启动时恢复工作区 |
| 浏览器状态 | browser_state.json | 浏览器关闭时 | 启动时恢复登录态 |
| 人格配置 | persona.yaml | 用户修改时 | 启动时读取 |
| 工具使用历史 | MCP 调用日志 (JSONL) | 每次 MCP 工具调用后追加 | 启动时加载最近N条 |

### 8.2 启动时上下文重建

```
class MemoryContinuity:
    def __init__(self, data_dir="./.aivyos"):
        self.data_dir = Path(data_dir)
        self.memory = Memory.from_config({
            "vector_store": {"provider": "chroma",
                            "config": {"path": str(self.data_dir / "memory_db")}},
            "embedder": {"provider": "huggingface",
                        "config": {"model": "BAAI/bge-m3"}}
        })
        self.memfs = MemFS(persist_path=self.data_dir / "memfs")
        self.checkpointer = SqliteSaver.from_conn_string(
            str(self.data_dir / "checkpoints.sqlite")
        )

    def restore_on_boot(self):
        all_memories = self.memory.get_all(user_id="owner")
        memfs_state = self.memfs.read_state()
        last_checkpoint = self.checkpointer.aget_latest()
        summary = self._generate_recovery_summary(
            all_memories, memfs_state, last_checkpoint
        )
        return {
            "long_term_memory": all_memories,
            "memfs_state": memfs_state,
            "workflow_checkpoint": last_checkpoint,
            "recovery_summary": summary
        }
```

> **三重保障** — (1) **Mem0** 自动从对话中抽取事实存入向量库；(2) **Letta MemFS** 让 Agent 自主管理记忆生命周期，跨重启存活；(3) **LangGraph 检查点** 自动保存工作流进度，断电后从最后成功节点恢复。
>
> **写入仲裁** — 事实/偏好类信息由 Mem0 统一抽取写入；Agent 主动维护的任务级状态写入 MemFS；工作流进度由 LangGraph 检查点负责。冲突时以 Mem0 的事实记忆为准，避免三方重复写入。

<a id="ch9"></a>
## 9. 核心特性三：专属认证 `安全`

AI只认主人——通过声纹+面部双重认证，未授权者无法唤醒系统。

### 9.1 认证流程

1. **待机监听** — 系统持续运行VAD，检测到语音活动时启动ASR。
2. **声纹采集** — 提取说话人的声纹嵌入向量（SpeechBrain ECAPA-TDNN，192维）。
3. **声纹比对** — 与注册的主人声纹模板做余弦相似度计算，阈值 >0.75通过。
4. **面部验证（可选）** — 若摄像头可用，同步进行面部识别（InsightFace），阈值 >0.6通过。
5. **活体检测** — 检测是否为真人而非录音/照片（频谱分析+眨眼检测）。
6. **认证通过/拒绝** — 通过则唤醒AI进入工作状态；拒绝则静默忽略，保持待机。

### 9.2 技术规格

| 参数 | 规格 | 备注 |
| --- | --- | --- |
| 声纹模型 | SpeechBrain ECAPA-TDNN / ReDimNet | 统一API，可平滑切换 |
| 声纹注册 | 3-10秒纯净语音样本 | 支持多模板注册 |
| 声纹比对 | 余弦相似度，阈值0.75 | EER <3%（中文场景） |
| 面部识别 | InsightFace (Buffalo_L) | 512维嵌入 |
| 面部阈值 | 余弦相似度，阈值0.6（初值，上线前按 EER 校准） | FAR <0.1%（校准后可达） |
| 活体检测 | 频谱反欺骗 + 视觉活体 | 防止录音/照片/视频攻击 |
| 认证延迟 | <500ms（声纹）/ <300ms（面部） | 可并行执行（并行场景 P50 300ms，见 §20.1） |
| 失败处理 | 静默忽略，不回应 | 不暴露系统存在 |

<a id="ch10"></a>
## 10. 核心特性四：一句话做软件 `核心`

用户用一句话描述需求，AI自动完成：需求解析 → 项目规划 → 代码生成 → 依赖安装 → 构建 → 交付到IDE。全程零手动干预。

### 10.1 代码生成管线（Cline SDK 集成）

原 8 阶段自研管线中，阶段 2-4、6 由 **Cline SDK** 接管：Cline 的 Plan/Act 双模式自动完成项目规划、代码生成、自审查和修复；阶段 5（构建验证）由 MCP shell Server 执行；AivyOS 只需负责需求解析（阶段 1）与构建验证、自动预览的编排调度。

| 阶段 | 输入 | 输出 | 执行方 |
| --- | --- | --- | --- |
| 1. 需求解析 | 自然语言一句话 | 结构化项目规格(JSON) | AivyOS LLM |
| 2. 项目规划 | 项目规格 | 文件树 + 每个文件职责 | **Cline Plan 模式** |
| 3. 代码生成 + 写入 | 文件树 | 完整代码文件写入工作区 | **Cline Act 模式** |
| 4. 自审查 + 修复 | 生成的代码 | 修复后的代码 | **Cline 内置** |
| 5. 构建验证 | 完整项目 | 构建结果 + 错误日志 | MCP shell Server |
| 6. 构建修复 | 错误日志 | 修复后的代码 | **Cline Act 模式**（LangGraph 条件边回环） |

### 10.2 项目脚手架模板

| 模板 | 技术栈 | 触发关键词 |
| --- | --- | --- |
| react-web-app | React + Vite + TailwindCSS | "网页""React""前端" |
| vue-web-app | Vue 3 + Vite + TailwindCSS | "Vue""前端" |
| nextjs-app | Next.js 14 + TailwindCSS | "全栈""SSR""Next" |
| python-cli | Python + Click/Typer | "命令行""CLI""脚本" |
| python-api | FastAPI + SQLAlchemy | "API""后端""服务" |
| static-site | HTML + CSS + JS | "静态网页""简单页面" |
| tauri-desktop-app | Tauri 2.0 + React + Rust | "桌面应用""桌面端""托盘" |

> **对比原方案** — 原方案 8 阶段全部自研。集成 Cline SDK 后，阶段 2-4 和 6 由 Cline 接管，自研代码减少约 75%。

<a id="ch11"></a>
## 11. 核心特性五：自动预览 `核心`

代码写完，AI自己打开浏览器，导航到预览页面，截图验证效果——用户只需看着结果。

| 参数 | 规格 | 备注 |
| --- | --- | --- |
| 浏览器引擎 | Playwright (Chromium) | 有头模式，用户可见 |
| 启动方式 | 自动启动浏览器实例 | 无需用户手动打开 |
| 开发服务器 | 自动启动并管理生命周期 | vite/webpack/python http.server |
| 热重载 | 文件变化时自动刷新页面 | Playwright page.reload() |
| 截图反馈 | 自动截图供AI视觉检查 | 全页截图 + 元素截图 |
| 多设备预览 | 支持桌面/手机/平板视口 | viewport切换 |
| 控制台监控 | 捕获浏览器console错误/警告 | page.on("console") |
| 网络监控 | 检测失败的API请求 | page.on("requestfailed") |

### 11.1 端到端完整工作流示例

**示例："做一个天气预报网页"**
- **专属认证** — 用户说"帮我做个天气预报网页"，声纹认证通过，AI唤醒
- **需求解析** — AI解析为：web_app / 静态HTML / 天气展示 / 需调用天气API
- **模板选择** — 匹配 static-site 模板
- **项目规划** — Cline Plan 模式规划文件树：index.html / style.css / script.js
- **代码生成** — Cline Act 模式逐文件生成完整代码
- **写入IDE** — MCP filesystem 写入用户工作区，IDE自动检测并打开
- **启动预览** — AI启动本地HTTP服务器，browser-use打开浏览器加载页面
- **视觉验证** — AI截图检查页面是否正常渲染，确认天气数据加载
- **控制台检查** — 捕获console错误，如有则自动修复
- **保存记忆** — Mem0记录"用户做了一个天气预报网页"，下次可在此基础上修改

<a id="ch12"></a>
## 12. 桌面端架构 `核心`

### 12.1 技术选型（Tauri 2.0）

AivyOS 桌面端采用 **Tauri 2.0** 作为应用壳层，Python 作为 AI 核心引擎。Tauri 提供原生窗口、系统托盘、全局热键等桌面能力，Python 通过子进程 + IPC 通信提供 AI 功能。

| 维度 | Tauri 2.0 | Electron | 选型理由 |
| --- | --- | --- | --- |
| 安装包大小 | ~8 MB | ~150 MB | 系统WebView，不打包Chromium |
| 内存占用 | ~80 MB | ~300 MB | 无Node.js运行时开销 |
| 启动速度 | 壳层UI <500 ms | ~2 s | Rust原生编译；完整就绪：冷启动19s / 热启动4s（见§20.1/§14.4） |
| 系统托盘 | 原生API | 需Tray插件 | Tauri 2.0内置tray-permission |
| 全局热键 | 原生API (global-shortcut) | 需globalShortcut插件 | Tauri 2.0内置 |
| 自动更新 | updater插件 (原生) | electron-updater | 支持增量更新 |
| 安全性 | Rust内存安全 + 权限沙箱 | Node.js安全模型 | Rust无内存泄漏风险 |
| 跨平台 | Windows / macOS / Linux | 同左 | 均支持三平台 |

> **架构决策** — Tauri 壳层负责 UI 渲染（React + WebView）、系统托盘、全局热键、自动更新、原生通知。Python 子进程负责 AI 推理（LLM/ASR/TTS）、记忆管理、工具执行。两者通过 **Unix Domain Socket / Named Pipe** 通信，延迟 <1ms。

### 12.2 系统托盘

AivyOS 常驻系统托盘，用户随时可呼出。这是"贾维斯始终在"的视觉体现。

| 功能 | 实现 | 说明 |
| --- | --- | --- |
| 托盘图标 | Tauri tray-icon API | 8 状态动态图标：待机(蓝)/监听(脉动)/工作(绿)/语音(青)/更新(橙)/启动(闪烁)/错误(红)/暂停(灰) |
| 左键单击 | 显示/隐藏主窗口 | 快速切换对话界面 |
| 右键菜单 | context menu | 打开主界面 / 设置 / 暂停监听 / 退出 |
| 双击 | 全局语音唤醒 | 立即进入语音交互模式 |
| 原生通知 | 原生系统通知 API | AI主动消息以通知形式展示 |
| 拖拽文件 | 托盘drag-drop | 拖文件到托盘图标，AI自动分析 |

### 12.3 全局热键

| 热键 | 功能 | 平台 |
| --- | --- | --- |
| Alt + Space | 唤醒AI（显示悬浮输入框） | Windows / Linux |
| Cmd + Space (覆盖Spotlight) | 唤醒AI | macOS (可选) |
| Alt + V | 开始/停止语音输入 | 全平台 |
| Alt + S | 截屏并发送给AI | 全平台 |
| Alt + Q | 快速退出/最小化 | 全平台 |

### 12.4 后台常驻服务

关闭主窗口时 AivyOS 不退出，而是最小化到托盘后台运行。语音监听、定时任务、事件触发等持续工作。

| 常驻组件 | 运行方式 | 关闭窗口后状态 |
| --- | --- | --- |
| Python AI核心 | 子进程 (persistent) | 持续运行 |
| VAD语音监听 | Python线程 | 持续监听 |
| 调度器(Cron/事件) | Python asyncio loop | 持续运行 |
| 记忆持久化 | Mem0 + ChromaDB (磁盘) | 持续可读写 |
| WebSocket服务 | Python aiohttp | 持续监听 |
| UI渲染(WebView) | Tauri窗口 | 隐藏，托盘可唤出 |

### 12.5 开机自启动

| 平台 | 自启机制 | 实现 |
| --- | --- | --- |
| Windows | 注册表 HKCU\...\Run | Tauri autostart插件 |
| macOS | LaunchAgent plist | Tauri autostart插件 |
| Linux | ~/.config/autostart/.desktop | Tauri autostart插件 |

### 12.6 原生通知

- **普通通知** — 文本消息，点击后在 AivyOS 中打开详情。
- **带操作按钮** — 通知附带"确认"/"忽略"按钮，用户可直接在通知中操作。
- **紧急通知** — 高优先级消息（如系统异常），绕过勿扰模式。

<a id="ch13"></a>
## 13. 自动更新与签名机制 `安全`

### 13.1 更新检测

| 参数 | 规格 |
| --- | --- |
| 检测频率 | 每6小时检查一次（可配置） |
| 检测方式 | GET /update/{target}/{arch}/{current_version} |
| 更新类型 | critical(安全) / feature(功能) / patch(补丁) |
| 用户通知 | critical: 立即更新 / feature: 询问 / patch: 静默 |
| 回退检测 | 更新后启动失败3次 → 自动回滚到上一版本 |

### 13.2 增量下载

通过 bsdiff/zstd 算法生成差异补丁，仅下载变更部分：二进制（壳层、模型权重）用 bsdiff，文本/脚本模块按文件哈希差量 + zstd 打包。

| 更新类型 | 包大小 | 下载时间 | 说明 |
| --- | --- | --- | --- |
| Tauri壳层更新 | 2-5 MB | <5s | 前端资源+Rust二进制差异补丁 |
| Python模块更新 | 0.5-3 MB | <3s | 按文件哈希差量 + zstd 打包（bsdiff 仅用于二进制） |
| 模型权重更新 | 10-50 MB | <30s | LoRA差异权重，非全量模型 |
| 全量更新（回退用） | ~15 MB | <15s | 完整安装包，仅在增量失败时使用 |

### 13.3 版本管理

系统保留最近3个版本，支持一键回滚。版本目录结构使用符号链接指向当前运行版本。

### 13.4 更新签名机制

AivyOS 的自动更新涉及从远程服务器下载可执行代码并执行。签名机制是唯一保障——确保用户收到的更新包**未被篡改**且**来源可信**，同时防止攻击者通过降级攻击植入旧版漏洞。

#### 13.4.1 三层 PKI 密钥体系

| 层级 | 密钥名称 | 算法 | 用途 | 存储位置 | 泄露影响 |
| --- | --- | --- | --- | --- | --- |
| L0 (Root) | Root CA | Ed25519 | 签发 Intermediate 证书 | 离线 HSM / 气隙机器 | 灾难级 — 全体系重建 |
| L1 (Intermediate) | Release Signing CA | Ed25519 | 签发 Code Signing 证书 | CI/CD 签名服务器 (TPM) | 严重 — 需撤销所有叶子证书 |
| L2 (Leaf) | Code Signing Key | Ed25519 | 签名实际更新包 | CI/CD 临时密钥 (每次发布) | 可控 — 撤销单次发布 |

#### 13.4.2 签名算法选型

| 候选算法 | 密钥长度 | 签名长度 | 验证速度 | 选型决策 |
| --- | --- | --- | --- | --- |
| **Ed25519** | 32 bytes | 64 bytes | ~50μs | **采用** — 签名快、长度小、无随机数陷阱 |
| RSA-2048 | 256 bytes | 256 bytes | ~100μs | 不采用 — 签名过大、性能差 |
| ECDSA P-256 | 32 bytes | 64 bytes | ~80μs | 不采用 — 有 k 值泄露风险 |

#### 13.4.3 客户端七步验签流程

客户端下载更新包后，**必须完整通过以下七步验证**才能执行安装。任何一步失败，立即中止并上报。

| 步骤 | 验证内容 | 失败动作 | 耗时 |
| --- | --- | --- | --- |
| ① 证书链验证 | Leaf → Intermediate → Root CA 信任链 | 拒绝更新，上报可疑活动 | ~1ms |
| ② 证书有效期 | 检查 not_before / not_after | 拒绝更新 | <1ms |
| ③ 撤销列表检查 | 查询 CRL / OCSP | 拒绝更新，上报 | ~50ms |
| ④ Ed25519 签名验证 | 用 Leaf 公钥验证 manifest 签名 | 拒绝更新，立即删除已下载文件 | ~50μs |
| ⑤ 全包哈希校验 | 计算下载包 BLAKE3，比对 manifest | 删除文件，从 CDN 重新下载 | ~100ms |
| ⑥ 逐文件哈希校验 | 解包后每个文件 BLAKE3 比对 | 删除损坏文件，重下该文件 | ~200ms |
| ⑦ 防降级检查 | 新版本号 > 当前版本号 | 拒绝更新，上报可疑活动 | <1ms |

#### 13.4.4 防篡改与防降级

| 攻击场景 | 防御机制 | 攻击结果 |
| --- | --- | --- |
| CDN 被入侵，替换二进制 | 逐文件 BLAKE3 哈希校验 | Step 6 拦截，文件被删除重下 |
| 中间人篡改 manifest | Ed25519 签名验证 | Step 4 拦截，包被隔离 |
| 中间人重放旧版 manifest | 时间戳 + 版本号检查 | Step 7 拦截，拒绝降级 |
| 自签名伪造证书 | Root CA 信任锚点预置 | Step 1 拦截，证书链断裂 |
| 混合攻击：真签名+假文件 | 签名覆盖 manifest（含文件哈希） | Step 4 签名验证失败 |

#### 13.4.5 密钥轮换策略

| 密钥层级 | 轮换周期 | 轮换流程 |
| --- | --- | --- |
| Root CA | 10 年 | 气隙机器生成新密钥 → 签发新 Intermediate → 客户端收到新 Root 公钥 |
| Intermediate CA | 1 年 | CI 签名服务器用 Root 签发新 Intermediate → 旧证书加入 CRL |
| Leaf Key | **每次发布** | CI 生成临时密钥 → 用 Intermediate 签发单次证书 → 发布后销毁私钥 |

> **安全基线** — ① 更新包完整性 — 64 字节 Ed25519 签名 + BLAKE3 哈希；② 来源认证 — 三层 PKI 证书链；③ 防降级 — 版本单调递增 + 时间戳新鲜度；④ 密钥安全 — Root 离线、Leaf 单次使用；⑤ 抗中间人 — 签名覆盖 manifest。

<a id="ch14"></a>
## 14. 热启动与热交换 `核心`

热启动（Hot Restart）是 AivyOS 的核心工程能力——更新代码/模型后**不中断服务**，用户无感知地切换到新版本。即使必须重启，也通过状态快照实现秒级恢复。

> **边界说明** — 本章热交换主体为 Python 模块与 LLM 模型；Tauri 壳层更新（§13）与前端资源热替换为独立通道（壳层更新需 WebView 重载或整包替换），不占用本章的零中断保证。

### 14.1 热交换机制

热交换是热启动的核心机制：在不停止进程的前提下，卸载旧模块、加载新模块、切换流量。支持三类热交换：

- **Python 模块热交换** — 通过 `importlib.reload()` 重新导入模块，保留全局状态（如数据库连接）。
- **LLM 模型热交换** — 加载新模型到内存 → 原子切换引用 → 等待旧请求完成 → 卸载旧模型释放显存。
- **前端热交换** — Tauri WebView 通过 HMR 热替换前端资源，无需刷新整个页面（仅开发模式；生产构建走整包替换 + WebView 重载）。

### 14.2 热交换冲突处理

热交换期间"模块正在被调用"会产生冲突。本章定义完整的冲突检测、隔离和解决体系，确保**常规场景零请求丢失、零状态损坏、零数据竞争**；排空超时的极端场景下，被中断的请求通过 LangGraph 检查点续传或重试队列补偿（见 §14.2.3）。

#### 14.2.1 冲突场景分类

| 冲突类别 | 典型场景 | 风险等级 | 核心解决策略 |
| --- | --- | --- | --- |
| **C1: 执行中热交换** | LLM 正在推理时模块被 reload | 高危 | 引用计数 + Drain 排空 |
| **C2: 状态结构不兼容** | 旧模块状态 JSON schema 与新模块不匹配 | 中危 | 版本化 schema + 自动迁移 |
| **C3: 并发请求竞争** | 热交换瞬间，请求 A 进入旧模块、请求 B 进入新模块 | 高危 | 读写锁 + 原子指针切换 |
| **C4: 资源依赖冲突** | 新模块需要新版底层依赖 | 中危 | 依赖兼容性矩阵 + 预检查 |

#### 14.2.2 读写锁与引用计数

解决 C1 和 C3 的核心机制：**模块级读写锁**。正常请求持读锁（可并发），热交换持写锁（独占）。热交换必须等所有读锁释放后才能执行。

```
class ModuleRWLock:
    """模块级读写锁（写者优先）— 读操作可并发，写操作（热交换）独占。
    写者到达后置 writer_waiting，后续新读者排队，避免写者饥饿；
    双写者互斥：已有写者在执行或排队时，新写者等待。"""
    def __init__(self):
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer_active = False
        self._writer_waiting = False
        self._active_calls = 0

    def acquire_read(self):
        with self._cond:
            while self._writer_active or self._writer_waiting:
                self._cond.wait()
            self._readers += 1
            self._active_calls += 1

    def release_read(self):
        with self._cond:
            self._readers -= 1
            self._active_calls -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self, timeout: float = 30.0):
        deadline = time.time() + timeout
        with self._cond:
            # 双写者互斥：已有写者在执行或排队时，新写者等待
            while self._writer_active or self._writer_waiting:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError("热交换超时：仍有写者占用模块")
                self._cond.wait(remaining)
            self._writer_waiting = True
            # 等待所有读者释放（新读者已被 writer_waiting 门控，不会继续进入）
            while self._readers > 0:
                remaining = deadline - time.time()
                if remaining <= 0:
                    self._writer_waiting = False
                    self._cond.notify_all()
                    raise TimeoutError(f"热交换超时：仍有 {self._readers} 个请求在执行")
                self._cond.wait(remaining)
            self._writer_waiting = False
            self._writer_active = True

    def release_write(self):
        with self._cond:
            self._writer_active = False
            self._cond.notify_all()
```

#### 14.2.3 Drain 排空策略

热交换不是瞬间完成的——必须**排空**（Drain）旧模块上的所有活跃请求，才能安全替换。

| Drain 阶段 | 动作 | 超时 | 超时后动作 |
| --- | --- | --- | --- |
| D1: 进入排空 | 设置 draining=True，拒绝新请求入队 | — | — |
| D2: 请求排队 | 新请求进入等待队列 | 30s | 超时后请求转入新模块 |
| D3: 等待活跃请求完成 | 轮询 active_count → 0 | 30s | 超时强制切换 — 中断请求标记后走检查点续传/重试 |
| D4: 状态提取 | 从旧模块提取持久状态 | 5s | 跳过状态迁移，使用快照 |
| D5: 模块重载 | importlib.reload() | 10s | 回滚到旧模块 |
| D6: 状态恢复 | 迁移并恢复状态到新模块 | 5s | 跳过，继续无状态启动 |
| D7: 健康检查 | 执行验证测试 | 10s | 回滚 |
| D8: 放行排队请求 | 队列中的请求转入新模块执行 | — | — |

#### 14.2.4 冲突解决矩阵

| 冲突 | 检测方式 | 解决步骤 | 用户影响 |
| --- | --- | --- | --- |
| C1: 请求正在旧模块执行 | active_count > 0 | Drain 排空 → 等待完成 → 超时强制标记中断 | ≤30s 延迟；超时中断的请求走检查点续传/重试 |
| C2: 状态 schema 不兼容 | schema_version 比对 | 调用 _migrate_state_() → 失败则从快照恢复 | 可能丢失当前会话上下文 |
| C3: 新旧模块并发执行 | 读写锁互斥 | 写锁阻塞新请求 → 原子指针切换 → 写锁释放 | 无感知 |
| C4: 依赖版本冲突 | 预检查 compat_matrix | 预检查失败 → 拒绝热交换 → 回退全量安装 | 需要 4s 快速启动 |
| C5: 新模块 import 失败 | importlib.reload 抛异常 | 捕获异常 → 不切换指针 → 释放写锁 | 无感知 |
| C6: 健康检查不通过 | HealthChecker.verify() | 回滚指针 → 恢复旧状态 → 释放写锁 | 通知"更新失败已回滚" |
| C7: 显存不足无法加载新模型 | torch.cuda.OutOfMemoryError | 卸载旧模型 → 重试加载 → 仍失败则回滚 | ~10s 延迟 |

#### 14.2.5 熔断与降级

当热交换连续失败时，系统进入**熔断状态**，停止尝试热交换，降级为"下载后下次冷启动安装"模式。熔断阈值 3 次连续失败，冷却期 1 小时。

> **零中断保证** — 通过读写锁 + Drain 排空 + 熔断降级三层机制，保证：① 热交换期间常规场景无请求丢失（排空超时中断的请求走检查点续传/重试）；② 热交换失败时无状态损坏（回滚+快照恢复）；③ 连续失败时不反复尝试（熔断保护）。

### 14.3 状态快照

热交换前，系统对所有运行时状态做**原子快照**。如果热交换失败，从快照恢复。

| 快照对象 | 内容 | 保存方式 | 恢复时间 |
| --- | --- | --- | --- |
| 会话上下文 | 当前对话历史、工作记忆 | JSON序列化 | <100ms |
| LLM推理状态 | KV Cache、生成中间态 | 不保存（可重建） | — |
| 工具执行状态 | 正在执行的工具、中间结果 | JSON + 进程检查 | <50ms |
| 调度器状态 | 定时任务列表、下次执行时间 | JSON | <50ms |
| 浏览器状态 | 打开的页面、Cookie、表单 | Playwright storageState | <200ms |
| 记忆索引 | 向量数据库状态 | 磁盘持久化 | 0（无需恢复） |

### 14.4 健康检查与回滚

| 检查项 | 方法 | 超时 | 失败动作 |
| --- | --- | --- | --- |
| LLM推理 | 发送测试prompt，检查响应 | 10s | 回滚模型 |
| 记忆检索 | 执行测试查询，检查结果 | 5s | 回滚记忆模块 |
| 工具调用 | 调用web_search测试 | 10s | 回滚工具模块 |
| ASR/TTS | 发送测试音频，检查识别 | 5s | 回滚语音模块 |
| 调度器 | 检查定时任务是否正常 | 3s | 回滚调度器 |
| 前端渲染 | 检查WebView是否正常加载 | 5s | 回滚前端资源 |

<a id="ch15"></a>
## 15. 托盘交互设计 `新增`

系统托盘是 AivyOS "始终在线"的视觉锚点。本章定义完整的**状态机、交互流程、菜单结构**，确保用户通过托盘即可完成所有核心操作。

### 15.1 托盘状态机（8 种状态）

- 🔵 **idle 待命**: AI核心已就绪，等待交互
- 🌀 **listening 监听**: VAD持续监听语音唤醒词
- 🟢 **working 工作**: 正在执行任务
- 🔊 **voice 语音**: 正在语音对话中
- ⏳ **updating 更新**: 正在下载/安装更新
- ⚡ **booting 启动**: 快速启动恢复中
- 🔴 **error 异常**: AI核心异常，需关注
- ⏸️ **paused 暂停**: 用户手动暂停了监听

### 15.2 左键交互流程

左键是最高频操作，设计原则是**单击即出/即收**，零延迟切换窗口可见性。双击（300ms 内两次单击）进入语音模式。

| 当前状态 | 左键单击动作 | 视觉反馈 |
| --- | --- | --- |
| 窗口隐藏 + idle | 显示主窗口 + 聚焦 | 窗口淡入 200ms |
| 窗口可见 + idle | 隐藏窗口到托盘 | 窗口淡出 150ms，气泡"我还在" |
| working | 显示窗口 + 滚动到任务进度区 | 任务进度高亮 |
| updating | 显示窗口 + 显示更新进度条 | 更新进度条 + 百分比 |
| error | 显示窗口 + 错误详情面板 | 红色错误卡片 + "重试"按钮 |
| booting | 忽略左键（正在启动） | 图标闪烁，无窗口 |

### 15.3 右键菜单设计

```
AivyOS 右键菜单
─────────────────────
📋 打开主界面 Alt+Space
🎙️ 语音对话 Alt+V
📸 截屏分析 Alt+S
─────────────────────
⏸️ 暂停监听 / ▶️ 恢复监听 Alt+P
─────────────────────
  🧠 记忆管理 ▸
    📊 查看记忆图谱
    🗑️ 清除短期记忆
    📥 导出记忆备份
    📤 导入记忆备份
  🔄 更新 ▸
    🔍 检查更新
    📜 查看更新历史
    ⏪ 回滚到上一版本
─────────────────────
⚙️ 设置
📊 诊断信息
─────────────────────
🚪 退出 AivyOS Alt+Q
```

### 15.4 双击交互（语音快捷入口）

1. **检测双击** — 300ms 内连续两次左键单击，触发双击事件。
2. **状态检查** — updating 或 booting 状态忽略双击。
3. **切换到 voice 状态** — 托盘图标变为 🎙️，播放提示音。
4. **激活 ASR** — 启动语音识别，显示语音波形可视化。
5. **语音对话循环** — 用户说话 → ASR → AI推理 → TTS语音回复 → 循环。
6. **退出语音模式** — 再次双击 / 按 Alt+V / 5秒无语音输入 → 回到 idle。

### 15.5 拖拽文件交互

用户可将文件直接拖到托盘图标上，AI 自动分析文件内容。

| 文件类型 | AI 分析动作 | 结果展示 |
| --- | --- | --- |
| 图片 (PNG/JPG) | OCR提取文字 + 视觉理解描述 | 弹窗显示分析结果 |
| 文档 (PDF/Word/Excel) | 解析内容并生成摘要 | 在主窗口展示摘要 |
| 代码文件 | 语法分析 + 代码审查 | 在IDE中打开并标注 |
| 数据文件 (CSV/JSON) | 统计分析 + 可视化建议 | 生成图表预览 |
| 其他文件 | 文件信息摘要 + 类型识别 | 弹窗显示文件信息 |

<a id="ch16"></a>
## 16. 数据流与通信协议

### 16.1 系统数据流

```
用户说话
  │
  ▼
[感知层] 音频采集 → VAD断句 → ASR识别
  │     输出: { text: "帮我查一下明天的日程", modality: "voice" }
  │
  ▼ (消息总线: perception.input)
[大脑层]
  ├→ 上下文管理: 拼接系统提示+人格+历史+当前输入
  ├→ 长期记忆检索: Mem0 查询"日程""明天"相关记忆
  ├→ LangGraph 工作流: LLM推理 → 判断需要调用 calendar 工具
  ├→ MCP 工具调用: calendar.query(date=tomorrow)
  ├→ LLM推理: 基于工具结果生成自然语言回复
  │
  ▼ (消息总线: core.output)
[输出层]
  ├→ TTS合成: CosyVoice 3 文本 → 语音
  └→ 播放音频
  │
  ▼
[进化层] (异步)
  ├→ Mem0 记录交互到情节记忆
  ├→ 更新偏好模型
  └→ 检查是否需要更新行为模式
```

### 16.2 内部通信协议

| 通信机制 | 用途 | 技术实现 |
| --- | --- | --- |
| 消息总线 | 层间异步消息传递 | Redis Streams |
| 事件总线 | 组件间事件通知 | Redis Streams（复用；NATS JetStream 为高并发备选） |
| RPC | 同步调用（如工具执行） | gRPC (本地UDS) |
| IPC | Tauri壳层 ↔ Python核心 | Named Pipe / UDS |
| 共享状态 | 会话状态、配置 | Redis Hash + 本地JSON |

### 16.3 外部 API 规范

#### 16.3.1 RESTful API

```
POST /api/v1/chat
Content-Type: application/json

{
  "session_id": "sess_a1b2c3",
  "input": {"modality": "text", "content": "帮我分析今天的日程安排"},
  "options": {"use_memory": true, "use_tools": true, "personality": "professional"}
}

Response 200:
{
  "session_id": "sess_a1b2c3",
  "response": {"text": "今天您有三个会议...", "tools_used": ["calendar.query"]},
  "metadata": {"model": "qwen2.5-72b", "latency_ms": 1200}
}
```

#### 16.3.2 WebSocket API（实时语音）

```
// 客户端 → 服务端
{ "type": "audio_start", "format": "pcm_16khz" }
{ "type": "audio_chunk", "data": "base64_encoded_pcm" }
{ "type": "audio_end" }

// 服务端 → 客户端
{ "type": "asr_partial", "text": "帮我看..." }
{ "type": "asr_final", "text": "帮我看一下明天的日程", "confidence": 0.97 }
{ "type": "llm_thinking", "status": "processing" }
{ "type": "response_text", "text": "明天您有两个会议..." }
{ "type": "tts_start" }
{ "type": "tts_chunk", "data": "base64_encoded_pcm" }
{ "type": "tts_end" }
```

<a id="ch17"></a>
## 17. 技术选型清单

| 模块 | 技术选型 | 备选方案 | 选型理由 |
| --- | --- | --- | --- |
| ASR语音识别 | SenseVoice / FunASR (Paraformer) | Whisper / Vosk | 同生态配套，中文流式识别最优 |
| VAD语音检测 | Silero VAD v5 | WebRTC VAD | 模型小(~2MB)，准确率高 |
| 说话人识别 | SpeechBrain (ECAPA-TDNN/ReDimNet) | 3D-Speaker / Resemblyzer | 统一API，多模型可选 |
| OCR文字识别 | PaddleOCR PP-OCRv4 | Tesseract / EasyOCR | 中文OCR SOTA |
| 视觉理解 | Qwen2.5-VL / Qwen3-VL | LLaVA-OneVision / InternVL | 开源多模态 |
| TTS语音合成 | **CosyVoice 3** (0.5B) | GPT-SoVITS V4 | 2026 SOTA，150ms首包，3秒克隆 |
| LLM推理引擎 | vLLM | TGI / Ollama | PagedAttention，Continuous Batching |
| Agent编排框架 | **LangGraph** | CrewAI / Claude Agent SDK | 图编排+检查点+模型无关 |
| 记忆管理层 | **Mem0** SDK 2.0 | 自研 MemoryContinuity | 自动抽取事实，混合检索 |
| 跨重启记忆 | **Letta MemFS** | 自研文件序列化 | 类文件系统持久化，跨重启存活 |
| 向量数据库 | ChromaDB（嵌入式） | Qdrant / Milvus | 嵌入式无依赖，作为 Mem0 后端 |
| 嵌入模型 | BGE-M3 (1024维) | bge-small-zh | 中英多语言，Mem0 内部调用 |
| 意图预分类 | MiniLM / 蒸馏BERT | 规则+关键词 | 轻量（<50ms），输入预处理用 |
| 工具调用协议 | **MCP 2026-07-28** | 自研 ToolBase | 事实标准，无状态核心+Tasks扩展 |
| 浏览器自动化 | **browser-use** + Playwright | Selenium / 自研 | 95K stars，自然语言驱动 |
| 代码生成引擎 | **Cline SDK** | Aider / Open Interpreter | 可嵌入SDK，Plan/Act双模式 |
| 桌面壳 | **Tauri 2.0** + React + Rust | Electron | 8MB/80MB，本地优先 |
| 消息总线 | Redis Streams | NATS JetStream | 轻量，支持消费者组 |
| 内部RPC | gRPC (本地UDS) | HTTP/REST | 低延迟，类型安全 |
| IPC通信 | Named Pipe / UDS | stdio | Tauri壳层 ↔ Python核心 |
| 更新签名 | Ed25519 + BLAKE3 | RSA-2048 / ECDSA | 签名快64B，无随机数陷阱 |
| 增量更新 | bsdiff + zstd | 全量替换 | 典型补丁 <5MB |
| 安全沙箱 | Docker容器（代码执行） | nsjail / Firecracker | 隔离不可信代码 |
| 链路追踪 | OpenTelemetry | Jaeger / Zipkin | CNCF标准，LangGraph原生集成 |
| 指标采集 | Prometheus + Grafana | Datadog | 开源，本地部署 |

> **选型原则** — 全部选型遵循"开源复用优先"原则，优先选择 Apache-2.0 / MIT 许可证的成熟开源组件。32+ 个开源项目覆盖 7 大技术方向，预计减少约 60% 自研工作量，MVP 周期从 3 个月缩短至 6-8 周。

<a id="ch18"></a>
## 18. 部署与硬件规格

### 18.1 硬件需求

| 配置等级 | GPU | 内存 | 存储 | 适用场景 |
| --- | --- | --- | --- | --- |
| 最低配置 | RTX 3060 12GB | 32 GB | 512 GB SSD | 7B模型 + 基础功能 |
| 推荐配置 | RTX 4070 Ti 16GB | 64 GB | 1 TB NVMe | 14B模型 + 全功能 |
| 高性能配置 | RTX 4090 24GB / 双卡 | 128 GB | 2 TB NVMe | 72B模型 + 多模态全开 |
| 云端补充 | — | — | — | 调用 Claude/GPT API 处理超长上下文/复杂推理 |

### 18.2 软件运行环境

| 组件 | 版本要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 11 / macOS 13+ / Ubuntu 22.04+ | 三平台支持 |
| Python | 3.11+ | AI核心引擎 |
| Node.js | 20 LTS+ | 前端构建工具链 |
| Rust | 1.75+ | Tauri壳层编译 |
| CUDA | 12.1+ | GPU推理加速 |
| Docker | 24.0+ | 代码执行沙箱 |
| Redis | 7.0+ | 消息总线 + 共享状态 |

### 18.3 目录结构

```
~/.aivyos/
    checkpoints.sqlite         # SQLite — LangGraph 工作流检查点
    memory_db/                 # ChromaDB — Mem0 向量存储
    memfs/                     # Letta MemFS — Agent 记忆文件系统
    snapshots/latest.json      # 热交换状态快照
    workspace_snapshot.json    # 工作区状态快照（任务切换/定时保存）
    browser_state.json         # 浏览器登录态
    persona.yaml               # 人格配置
    versions/                  # 版本管理（保留3个版本）
        current → v1.2.3/      # 符号链接指向当前版本
        v1.2.3/
        v1.2.2/
    quarantine/                # 可疑更新包隔离区
    logs/                      # 运行日志
    security_audit.log         # 安全审计日志
```

<a id="ch19"></a>
## 19. 安全与隐私设计

### 19.1 数据安全策略

| 数据类别 | 存储位置 | 加密方式 | 是否上传云端 |
| --- | --- | --- | --- |
| 对话历史 | 本地 SQLite + ChromaDB | AES-256 磁盘加密 | 否 |
| 声纹模板 | 本地加密存储 | AES-256-GCM 加密 + Ed25519 完整性签名 | 否 |
| 面部特征 | 本地加密存储 | AES-256 | 否 |
| 记忆向量 | 本地 ChromaDB | 磁盘级加密 | 否 |
| 人格配置 | 本地 persona.yaml | 明文（用户可读） | 否 |
| 浏览器状态 | 本地 browser_state.json | 默认 AES-256，用户可关闭 | 否 |

### 19.2 权限分级体系

| 权限级别 | 操作示例 | 确认机制 |
| --- | --- | --- |
| L0 只读 | 文件读取、网页浏览、搜索 | 自动执行 |
| L1 低危写 | 文件写入、代码生成、文档创建 | 自动执行，日志记录 |
| L2 高危写 | Shell命令、代码执行、系统设置 | 需用户确认（MCP MRTR） |
| L3 危险操作 | 删除文件、网络外发、安装软件 | 需用户确认 + 操作日志 |

### 19.3 安全审计

- **操作日志** — 所有 L2+ 操作写入安全审计日志，含时间戳、操作类型、参数、结果。
- **行为漂移检测** — 三层防护：统计异常检测（操作频率/类型分布偏离基线）+ 语义异常检测（LLM 审查操作意图）+ 人工审核（高危操作触发通知）。
- **安全事件上报** — 签名验证失败、证书撤销、降级攻击检测时，隔离可疑文件 + 写入审计日志 + 暂停自动更新 24 小时。
- **代码执行沙箱** — 不可信代码（AI 生成的脚本）在 Docker 容器中执行，限制网络访问、文件系统挂载和资源配额。

### 19.4 许可证合规

| 组件 | 许可证 | 合规状态 |
| --- | --- | --- |
| Mem0 / Letta / LangGraph | Apache-2.0 / MIT | 友好，无传染性风险 |
| Cline SDK / Aider | Apache-2.0 | 友好 |
| CosyVoice 3 | Apache-2.0 | 友好 |
| browser-use / Playwright | 开源 | 友好 |
| Open Interpreter | AGPL v3 | **注意** — 传染性较强，仅参考不深度集成 |
| Tauri 2.0 | MIT / Apache-2.0 | 友好 |

<a id="ch20"></a>
## 20. 性能指标基准

### 20.1 延迟指标

| 链路 | P50 | P95 | 说明 |
| --- | --- | --- | --- |
| 语音唤醒 → 认证完成 | 300ms | 500ms | 声纹+面部并行 |
| ASR 识别（短句） | 200ms | 500ms | SenseVoice 流式 |
| LLM 首 Token | 150ms | 500ms | vLLM + KV Cache |
| LLM 完整回复（100 Token） | 1.2s | 3s | 14B 模型 |
| TTS 首音频帧 | 150ms | 300ms | CosyVoice 3 |
| 记忆检索 | 30ms | 50ms | Mem0 + ChromaDB |
| MCP 工具调用（本地） | 50ms | 200ms | gRPC UDS |
| 热交换完成 | 5s | 15s | 含 Drain 排空 |
| 冷启动 → 就绪 | 19s | 30s | 含模型加载 |
| 热启动 → 就绪 | 4s | 6s | 模型常驻+快照恢复 |

### 20.2 资源占用

| 组件 | 内存 | 显存 | CPU |
| --- | --- | --- | --- |
| Tauri 壳层（空闲） | ~80 MB | — | <1% |
| Python AI 核心（空闲） | ~500 MB | — | <5% |
| LLM 推理（14B） | ~2 GB | ~12 GB | 推理时 30-80% |
| ASR（SenseVoice） | ~300 MB | ~1 GB | 监听时 5-10% |
| TTS（CosyVoice 3） | ~200 MB | ~2 GB | 合成时 10-20% |
| ChromaDB + Mem0 | ~200 MB | — | <2% |
| Redis | ~50 MB | — | <1% |
| **总计（待机）** | **~1.3 GB** | **~15 GB** | **<10%** |
| **总计（全负载）** | **~3.5 GB** | **~17 GB** | **30-80%** |

<a id="ch21"></a>
## 21. 测试策略与可观测性

### 21.1 测试分层

AivyOS 作为个人使用项目，测试策略以实用为先，聚焦核心链路稳定性，不追求企业级覆盖率。

| 测试层 | 范围 | 工具 | 目标 |
| --- | --- | --- | --- |
| 单元测试 | 记忆检索、记忆抽取、路由策略 | pytest | 核心逻辑无回归 |
| 集成测试 | LangGraph 工作流端到端、MCP 工具调用链 | pytest + LangGraph 检查点回放 | 节点串联正确 |
| 语音链路压测 | ASR→LLM→TTS 全链路延迟 | 自定义 benchmark 脚本 | P95 延迟达标 |
| 记忆连续性测试 | 重启后记忆恢复、MemFS 状态存活 | 模拟断电重启脚本 | 零记忆丢失 |
| 热交换验证 | 模块热重载后健康检查 | HealthChecker 自动化 | 热交换成功率>99% |
| 签名验证测试 | 七步验签流程、防篡改、防降级 | 模拟篡改测试包 | 100% 拦截篡改 |

### 21.2 可观测性架构

| 维度 | 工具 | 采集内容 |
| --- | --- | --- |
| 链路追踪 | OpenTelemetry | 每个请求的完整调用链：ASR→LLM→工具→TTS |
| 指标采集 | Prometheus + Grafana | 延迟分布、Token吞吐、GPU利用率、记忆检索命中率 |
| 日志聚合 | 结构化JSON日志 | 运行日志、安全审计、MCP调用日志(JSONL) |
| 工作流追踪 | LangGraph 检查点回放 + 本地可视化 | 图执行轨迹、检查点状态、节点耗时（本地，不上云） |

### 21.3 关键监控指标

| 指标 | 阈值 | 告警动作 |
| --- | --- | --- |
| LLM 首 Token 延迟 P95 | <500ms | >1s 持续 5 分钟 → 降级到更小模型 |
| 记忆检索延迟 P95 | <50ms | >100ms → 检查 ChromaDB 索引 |
| GPU 显存占用 | <90% | >95% → 触发模型卸载 |
| 热交换失败率 | <1% | >3 次连续失败 → 熔断，改冷启动 |
| 签名验证失败次数 | 0 | 任意失败 → 安全告警 + 暂停更新 |

<a id="ch22"></a>
## 22. 开源复用决策矩阵

对 AivyOS 每个核心模块，明确"自研"还是"复用开源"，以及理由：

| 模块 | 决策 | 复用对象 | 理由 |
| --- | --- | --- | --- |
| 记忆抽取/检索/摘要 | `复用` | Mem0 + ChromaDB | 61.6K stars，自研成本高且易错 |
| 跨重启记忆持久化 | `复用` | Letta MemFS | 类文件系统记忆抽象直接解决"重启连续" |
| Agent 工作流编排 | `复用` | LangGraph | 图编排+检查点+模型无关，生产验证 |
| 工具调用协议 | `复用` | MCP 2026-07-28 | 事实标准，一次封装处处可用 |
| 浏览器自动化 | `复用` | browser-use + Playwright | 95K stars，自然语言驱动 |
| 代码生成/IDE 写入 | `复用` | Cline SDK | 可嵌入 SDK，省去自研 8 阶段管线 |
| TTS 语音合成 | `复用` | CosyVoice 3 | 2026 SOTA，Apache-2.0 |
| ASR 语音识别 | `复用` | SenseVoice + FunASR | 同生态配套，OpenAI 兼容 API |
| 声纹认证 | `复用` | SpeechBrain（ECAPA-TDNN/ReDimNet） | 统一 API，多模型可选 |
| 面部识别 | `复用` | InsightFace | 成熟、性能与许可满足要求 |
| 桌面壳 | `复用` | Tauri 2 + React | 8MB/80MB，本地优先 |
| LLM 推理引擎 | `复用` | vLLM | PagedAttention，Continuous Batching |
| 向量数据库 | `复用` | ChromaDB | 作为 Mem0 后端 |
| 嵌入模型 | `复用` | BGE-M3 | 中英多语言 |
| 更新签名 | `复用` | PyNaCl (Ed25519) + BLAKE3 | 成熟密码学库 |
| 自进化引擎 | `部分复用` | OpenJarvis spec 搜索 + LangMem | 借鉴架构，AivyOS 个性化逻辑自研 |
| 人格系统 | `自研` | — | 差异化核心，Big Five + 自定义模板 |
| 主动调度器 | `自研` | — | 基于 LangGraph + Cron，触发逻辑个性化 |
| 认证状态机 | `自研` | — | 声纹/面部/活体融合逻辑是差异化体验 |
| 安全与权限分级 | `自研` | — | 本地隐私策略需定制 |

> **预期收益** — 若按上述矩阵复用开源组件，AivyOS 核心模块的自研工作量可减少约 **60%**，MVP 周期从 3 个月缩短至 6-8 周。最大红利来自 MCP（工具层）、Mem0+Letta（记忆层）、Cline SDK（代码生成）三个方向。

<a id="ch23"></a>
## 23. 开发计划与里程碑

AivyOS 采用三阶段渐进式开发，每阶段聚焦核心能力闭环，确保每阶段结束时都有可演示的成果。其中 Phase 1-2（核心对话 + Vibe Coding 闭环）构成 MVP，约 6-8 周；Phase 3 补齐签名、热交换、自进化等完整工程化能力，总周期 12 周。

**Phase 1：核心对话闭环（第 1-4 周）** (4 周 · 目标：能听、能想、能说、能记)
- **第 1 周** — 搭建 Tauri 2.0 壳层 + Python 子进程 IPC；vLLM 本地部署 Qwen2.5-7B；基础文本对话链路
- **第 2 周** — SenseVoice/FunASR 流式 ASR 集成；Silero VAD 语音活动检测；CosyVoice 3 TTS 集成
- **第 3 周** — Mem0 + ChromaDB 记忆系统搭建；Letta MemFS 跨重启持久化；LangGraph 基础工作流
- **第 4 周** — SpeechBrain 声纹认证；InsightFace 面部认证；认证状态机；端到端语音对话联调

**Phase 2：Vibe Coding 闭环（第 5-8 周）** (4 周 · 目标：一句话做软件 + 自动预览)
- **第 5 周** — MCP 架构搭建（filesystem/shell/browser/code-exec Server）；MRTR 确认机制
- **第 6 周** — Cline SDK 集成；需求解析引擎；项目脚手架模板；代码生成→IDE写入链路
- **第 7 周** — browser-use 集成；自动预览控制器；开发服务器管理；截图验证
- **第 8 周** — LangGraph Vibe Coding 状态图编排；构建失败回环修复；端到端 Vibe Coding 联调

**Phase 3：工程化与自进化（第 9-12 周）** (4 周 · 目标：桌面常驻 + 自动更新 + 自进化)
- **第 9 周** — 系统托盘 8 状态机；全局热键；后台常驻；开机自启；原生通知
- **第 10 周** — Ed25519 三层 PKI 签名体系；七步验签流程；增量更新；版本管理与回滚
- **第 11 周** — 热交换机制（读写锁 + Drain 排空 + 熔断降级）；状态快照；健康检查与回滚；快速启动
- **第 12 周** — OpenJarvis spec 搜索集成；自进化反馈闭环；OpenTelemetry 可观测性；最终联调与优化

<a id="ch24"></a>
## 24. 功能模块任务清单

以下按模块拆分详细任务，每个任务标注优先级（P0 最高 / P1 高 / P2 中）和所属开发阶段。

#### M1：感知输入层
*Phase 1 · 第 1-2 周*

- [P0] T1.1 — Tauri 2.0 壳层搭建，Python 子进程 IPC 通信（Named Pipe / UDS）
- [P0] T1.2 — vLLM 本地部署 Qwen2.5-7B/14B，OpenAI 兼容 API 封装
- [P0] T1.3 — SenseVoice/FunASR 流式 ASR 集成，VAD 端点检测
- [P0] T1.4 — Silero VAD v5 集成，语音活动检测 + 唤醒词触发
- [P1] T1.5 — 文本输入子系统（悬浮输入框 + WebSocket 实时通信）
- [P1] T1.6 — PaddleOCR PP-OCRv4 集成，截图文字识别
- [P2] T1.7 — LLaVA/Qwen2-VL 视觉理解集成，图片内容描述
- [P2] T1.8 — 多模态融合策略（语音+文本+视觉权重分配）

#### M2：核心大脑层
*Phase 1 · 第 3-4 周*

- [P0] T2.1 — Mem0 SDK 2.0 集成，ChromaDB 后端配置，BGE-M3 嵌入模型
- [P0] T2.2 — Mem0 记忆写入/检索 API 封装（add/search）
- [P0] T2.3 — Letta MemFS 集成，Agent 记忆文件系统持久化
- [P0] T2.4 — LangGraph 工作流框架搭建，SqliteSaver 检查点配置
- [P0] T2.5 — LLM 路由策略实现（本地 vLLM ↔ 云端 Claude/GPT 动态切换）
- [P1] T2.6 — 人格系统（Big Five 参数 + System Prompt 模板）
- [P1] T2.7 — 上下文管理器（128K 窗口分配 + 滑动窗口 + 压缩策略）
- [P1] T2.8 — 启动时上下文重建（Mem0 + MemFS + LangGraph 检查点三重恢复）

#### M3：能力扩展层
*Phase 2 · 第 5-8 周*

- [P0] T3.1 — MCP Server 框架搭建（2026-07-28 规范，无状态核心）
- [P0] T3.2 — MCP filesystem Server（文件读写，路径白名单）
- [P0] T3.3 — MCP shell Server（命令执行，MRTR 确认机制）
- [P0] T3.4 — MCP browser Server（browser-use 驱动，Playwright 底层）
- [P0] T3.5 — MCP code-exec Server（Docker 沙箱内 Python 执行）
- [P1] T3.6 — MCP office Server（python-docx/openpyxl/pptx 封装）
- [P1] T3.7 — MCP search Server（SearXNG 集成）
- [P1] T3.8 — MCP screenshot Server（屏幕截图 + 区域截取）
- [P2] T3.9 — 自进化引擎（OpenJarvis spec 搜索 + LangMem 提示词优化）
- [P2] T3.10 — 主动调度器（Cron 定时任务 + 事件触发 + 条件监控）

#### M4：输出响应层
*Phase 1-2 · 第 2、7 周*

- [P0] T4.1 — CosyVoice 3 TTS 引擎集成，3 秒音色克隆
- [P0] T4.2 — TTS 流式合成（首包 <150ms，vLLM 加速）
- [P1] T4.3 — 多模态输出策略（语音/文本/通知/文件 路由）
- [P1] T4.4 — 原生系统通知（Tauri notification 插件）
- [P2] T4.5 — 情感标签控制（14 种细粒度标签：[laughter][breath]等）
- [P2] T4.6 — GPT-SoVITS 备选引擎可插拔切换

#### M5：Vibe Coding 闭环
*Phase 2 · 第 6-8 周*

- [P0] T5.1 — Cline SDK 集成（Plan/Act 双模式，多模型 BYOK）
- [P0] T5.2 — 需求解析引擎（自然语言 → 结构化项目规格 JSON）
- [P0] T5.3 — 项目脚手架模板（react-web-app / vue / nextjs / python-cli 等 7 种）
- [P0] T5.4 — 代码生成 → IDE 写入链路（MCP filesystem Server）
- [P0] T5.5 — 自动预览控制器（启动 dev server → 打开浏览器 → 截图验证）
- [P1] T5.6 — LangGraph Vibe Coding 状态图（understand→plan→generate→deliver→build→preview→save_memory）
- [P1] T5.7 — 构建失败条件边回环（build 失败 → 自动回到 generate 修复）
- [P1] T5.8 — 浏览器控制台错误监控 + 网络请求失败检测
- [P2] T5.9 — 多设备预览（桌面/手机/平板视口切换）

#### M6：专属认证
*Phase 1 · 第 4 周*

- [P0] T6.1 — SpeechBrain 声纹模型集成（ECAPA-TDNN，192 维嵌入）
- [P0] T6.2 — 声纹注册流程（3-10 秒纯净语音样本，支持多模板）
- [P0] T6.3 — 声纹比对（余弦相似度，阈值 0.75）
- [P1] T6.4 — InsightFace 面部识别集成（Buffalo_L，512 维嵌入，阈值 0.6）
- [P1] T6.5 — 活体检测（频谱反欺骗 + 视觉活体）
- [P1] T6.6 — 认证状态机（dormant→listening→verifying→authenticated/rejected）
- [P2] T6.7 — 多用户注册支持（不同用户不同人格配置）

#### M7：桌面端工程化
*Phase 3 · 第 9 周*

- [P0] T7.1 — Tauri 2.0 系统托盘（8 状态机：idle/listening/working/voice/updating/booting/error/paused）
- [P0] T7.2 — 托盘图标设计（8 套状态图标 × 4 尺寸 16/24/32/48）
- [P0] T7.3 — 托盘左键交互（单击切换窗口 + 状态感知行为）
- [P0] T7.4 — 托盘右键菜单（主界面/语音/截屏/暂停/记忆管理/更新/设置/退出）
- [P0] T7.5 — 托盘双击语音快捷入口（300ms 判定 + 语音模式切换）
- [P1] T7.6 — 托盘拖拽文件交互（文件类型路由 + AI 自动分析）
- [P0] T7.7 — 全局热键（Alt+Space 唤醒 / Alt+V 语音 / Alt+S 截屏 / Alt+Q 退出）
- [P0] T7.8 — 后台常驻（窗口关闭 → 最小化到托盘 + Python 核心持续运行）
- [P1] T7.9 — 开机自启（Tauri autostart 插件，三平台支持）
- [P1] T7.10 — 原生通知（分级推送：紧急/重要/普通/静默 + 勿扰模式）

#### M8：自动更新与签名
*Phase 3 · 第 10 周*

- [P0] T8.1 — 三层 PKI 密钥体系搭建（Root CA / Intermediate / Leaf）
- [P0] T8.2 — CI/CD 签名生成脚本（BLAKE3 哈希 + Ed25519 签名 + manifest.signed.json）
- [P0] T8.3 — 客户端七步验签流程实现（证书链→有效期→CRL→签名→全包哈希→逐文件→防降级）
- [P0] T8.4 — Tauri updater 插件集成，更新检测（每 6 小时检查）
- [P1] T8.5 — 增量下载（bsdiff + zstd，典型补丁 <5MB）
- [P1] T8.6 — 版本管理（保留 3 个版本，符号链接切换，一键回滚）
- [P1] T8.7 — 密钥轮换策略（Root 10 年 / Intermediate 1 年 / Leaf 每次发布）
- [P2] T8.8 — 安全事件上报（篡改检测 → 隔离 + 审计日志 + 暂停更新 24h）

#### M9：热交换与热启动
*Phase 3 · 第 11 周*

- [P0] T9.1 — ModuleRWLock 模块级读写锁（读操作并发，写操作独占）
- [P0] T9.2 — SafeModuleProxy 安全模块代理（所有调用经锁保护）
- [P0] T9.3 — DrainManager 排空管理器（8 阶段：entering→queueing→draining→extracting→reloading→restoring→verifying→releasing）
- [P0] T9.4 — 状态迁移兼容（schema 版本声明 + _migrate_state_ 迁移函数 + 快照兜底）
- [P0] T9.5 — ModelHotSwapper 模型热交换（加载新模型→原子切换→Drain 旧请求→卸载旧模型）
- [P1] T9.6 — HotSwapCircuitBreaker 熔断器（连续 3 次失败 → 熔断 1 小时 → 降级冷启动）
- [P1] T9.7 — StateSnapshot 状态快照（会话/工具/调度器/浏览器 原子快照 + 恢复）
- [P1] T9.8 — HealthChecker 健康检查（LLM/记忆/工具/语音/调度器/前端 6 项检查 + 自动回滚）
- [P1] T9.9 — FastBoot 快速启动（模型常驻 + 快照恢复，冷启动 19s → 热启动 4s）
- [P2] T9.10 — 前端热交换（Vite HMR + WebView 资源热替换）

#### M10：可观测性与测试
*Phase 3 · 第 12 周*

- [P1] T10.1 — OpenTelemetry 链路追踪集成（ASR→LLM→工具→TTS 全链路）
- [P1] T10.2 — Prometheus 指标采集 + Grafana 仪表盘
- [P1] T10.3 — 工作流追踪（LangGraph 检查点回放 + 本地可视化）
- [P1] T10.4 — 结构化 JSON 日志 + 安全审计日志
- [P2] T10.5 — 单元测试（记忆检索/路由策略/签名验证）
- [P2] T10.6 — 集成测试（LangGraph 工作流端到端 + MCP 工具调用链）
- [P2] T10.7 — 语音链路压测（ASR→LLM→TTS 全链路延迟 benchmark）
- [P2] T10.8 — 记忆连续性测试（模拟断电重启 → 零记忆丢失验证）

<a id="ch25"></a>
## 25. 风险评估与应对

| 风险 | 概率 | 影响 | 应对措施 |
| --- | --- | --- | --- |
| GPU 显存不足导致多模型无法同时加载 | 中 | 高 | 模型分时加载 + vLLM 显存利用率动态调整 + 云端 API 降级 |
| 热交换期间状态不一致导致数据损坏 | 低 | 高 | 读写锁 + Drain 排空 + 状态快照 + 熔断降级四层防护 |
| 签名密钥泄露导致更新包被伪造 | 极低 | 灾难 | Root CA 离线 HSM + Leaf 密钥单次使用 + CRL 撤销机制 |
| Mem0/Letta 记忆抽取质量不稳定 | 中 | 中 | 定期审查抽取结果 + 手动修正接口 + LangMem 提示词优化补充 |
| Cline SDK 生成的代码质量不达标 | 中 | 中 | 构建验证 + 条件边回环修复 + LLM 自审查机制 |
| browser-use 在复杂网页上定位失败 | 中 | 低 | 降级到 Playwright API 手动定位 + 视觉定位 fallback |
| 声纹认证误识（家人声音相似） | 低 | 中 | 提高阈值 + 面部双重认证 + 活体检测 |
| 开源组件许可证变更（如 AGPL 传染） | 低 | 中 | 定期审查许可证 + 避免深度集成 AGPL 组件 + 替换方案预案 |
| 本地模型推理延迟过高影响体验 | 中 | 中 | 路由策略动态切换小模型 + KV Cache 优化 + 云端 API 辅助 |

> **风险总结** — AivyOS 作为个人使用项目，最大风险在于 GPU 硬件限制和开源组件质量。通过云端 API 降级、模型分时加载、多模型 BYOK 策略可缓解硬件风险；通过 Build vs Reuse 矩阵选择成熟开源组件、定期审查许可证可降低开源风险。热交换和签名机制的设计已充分考虑安全性，实际风险极低。

---

**AivyOS — 个人专属AI伴侣系统 · 完整技术工程文档**

文档编号 AIVY-TDD-2026-001 · 版本 V2.1 · 日期 2026-08-17

整合自 5 份独立文档：技术工程文档、核心特性规格、桌面端与热启动规格、签名/热交换/托盘深度规格、文档审查与开源复用建议。

**版本历史**

- V1.0 (2026-08-16) — 初版技术工程文档，含四层架构、五大特性、数据流协议
- V1.1 (2026-08-16) — 新增核心特性规格书（FDD-002），补充五大特性技术细节
- V1.2 (2026-08-17) — 新增桌面端与热启动规格（DDD-003），定义 Tauri 2.0 壳层
- V1.3 (2026-08-17) — 新增签名/热交换/托盘深度规格（DDD-004），Ed25519 三层 PKI
- V1.4 (2026-08-17) — 新增文档审查与开源复用建议（REV-003），32+ 开源项目调研
- **V2.0 (2026-08-17) — 全文档整合：5 份文档合并为一份，修正全部不一致（TTS→CosyVoice 3、ASR→SenseVoice、记忆→Mem0+Letta、编排→LangGraph、工具→MCP、浏览器→browser-use、代码→Cline SDK、桌面→Tauri 2.0），新增功能模块任务清单（10 模块 80+ 任务）**
- **V2.1 (2026-08-17) — 文档审查修订：修复 §10.1 阶段表述矛盾与脚手架模板数量、重写 ModuleRWLock（写者优先 + 双写者互斥）、明确排空超时补偿策略；统一 ASR 显存/多语言/事件总线/检查点目录/启动三口径；更新模型版本（Claude 旗舰、Qwen-VL 系列）；声纹模板加密改 AES-256-GCM；补充记忆写入仲裁与热交换边界说明；去重 §7.4 与 §4.5.2 LangGraph 代码**

