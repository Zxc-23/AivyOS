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
# 方式 A：本地 Ollama（8GB 显存推荐 qwen2.5:3b；文档规格 7B 需 12GB+）
winget install Ollama.Ollama
ollama pull qwen2.5:3b
python -m aivyos_core.cli --mode local     # 默认本地模型即 qwen2.5:3b（与 ollama list 一致）

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

# 方式 F：VibeCoding 工作流演示（§4.5.2，检查点 + 断点续传）
python -m aivyos_core.workflow --demo "做一个天气网页"      # 首次执行
python -m aivyos_core.workflow --resume                     # 从检查点续传
python -m aivyos_core.workflow --demo "天气网页失败"        # 观察构建失败→自动修复回环

# 方式 G：专属认证（§9，合成音色演示，零依赖可跑）
python -m aivyos_core.auth demo                              # 注册张三/李四 → 本人通过/陌生人静默拒绝
python -m aivyos_core.auth register 张三 --wav voice.wav     # 真实音频注册（3-10s）
python -m aivyos_core.auth verify --wav test.wav             # 真实音频认证
```

## 里程碑对应

| 本文档模块 | 技术文档章节 | 状态 |
| --- | --- | --- |
| LLM 路由（本地/云端/mock 三级） | §4.1.3 | ✅ 已实现（含失败降级） |
| 人格系统（Big Five 模板） | §4.3 | ✅ 已实现 |
| 上下文管理（窗口分配/压缩/归档） | §4.4 | ✅ 已实现（摘要为朴素占位，Week 3 升级） |
| 记忆（Mem0 适配 + JSON 回退） | §4.2 | ✅ 已实现（simple 后端完整，mem0 适配就绪，update 契约对齐） |
| MemFS 类文件系统记忆（跨重启） | §8.1 | ✅ Week 3 已实现（零依赖，路径安全，快照/恢复） |
| 工作流引擎（StateGraph/条件边/检查点/续传） | §4.5 | ✅ Week 3 已实现（mini_graph 零依赖 + langgraph 可选适配） |
| VibeCoding 预置工作流（构建失败回环） | §4.5.2 / §7.4 | ✅ Week 3 已实现（演示模式） |
| 启动上下文重建（记忆+MemFS+检查点） | §8.2 | ✅ Week 3 已实现（restore_on_boot 三重恢复） |
| 声纹认证（注册 3-10s 多模板 / 余弦阈值 0.75） | §9 | ✅ Week 4 已实现（ECAPA-TDNN 可选 + 零依赖频谱嵌入回退） |
| 面部认证（阈值 0.6）+ 活体检测 | §9.2 | ✅ Week 4 已实现（InsightFace 可选 + mock 回退；频谱反重放） |
| 认证状态机（dormant→listening→verifying→auth/reject） | §9.1 / T6.6 | ✅ Week 4 已实现（静默拒绝 + 自动重置） |
| 多用户认证（每人人格） | T6.7 | ✅ Week 4 已实现 |
| **MCP 工具层**（框架+MRTR+八大 Server） | §5 | ✅ Week 5 已实现（filesystem 白名单/shell/code-exec/browser/office/search/screenshot/memory，L0-L3 权限 + MRTR 确认） |
| **自进化引擎**（SpecSearch gate 容差） | §5.2.2 | ✅ Week 5 已实现（T3.9） |
| **主动调度器**（Cron/事件/条件） | §5.3 | ✅ Week 5 已实现（T3.10） |
| 语音会话认证门控 | §9 | ✅ Week 4 已实现（未认证 → 静默忽略） |
| 视觉输入（OCR/图像理解/截图，全部可降级） | §3.3 | ✅ 已实现（T1.6/T1.7，PaddleOCR/Qwen2-VL 可选） |
| 多模态晚期融合（文本+语音+视觉 → 统一上下文） | §3.4 | ✅ 已实现（T1.8） |
| 多模态输出路由（语音/文本/通知/文件） | §6.3 | ✅ 已实现（T4.3，含紧急度分级） |
| 原生通知适配（win10toast 可选 + console 回退） | §12.6 | ✅ 已实现（T4.4） |
| 情感标签控制（14 标签 [laughter][breath]…） | §6.1 | ✅ 已实现（T4.5） |
| 悬浮输入框（tkinter 可选） | §3.2 | ✅ 已实现（T1.5） |
| **LLM 摘要**（真实后端可用 → LLM；否则朴素回退） | §4.4.2 | ✅ 已实现（A1 清理，杜绝 mock 冒充） |
| **LLM 事实抽取**（extract_backend=auto/rules/llm） | §4.2 | ✅ 已实现（A2 清理） |
| **视觉活体**（cv2 拉普拉斯方差+人脸 / honest passive） | §9.1 | ✅ 已实现（A3 清理） |
| **本地可用性真实探测**（GET /models + TTL 缓存） | §4.1 | ✅ 已实现（A4 清理） |
| **TTS 克隆参考音频**（clone_ref_path 配置加载） | §6.1 | ✅ 已实现（A5 清理） |
| **工作流 local 执行器**（真实写文件/构建/HTTP 预览 + give_up 终止） | §4.5.2 | ✅ 已实现（A6 清理） |
| **端到端联调测试**（语音认证→ASR→LLM→TTS / 视觉融合 / 输出路由 / 记忆持久化） | §23 | ✅ 已实现（164 测试全通，Phase 1 收官） |
| 会话持久化与快照 | §14.3 | ✅ 已实现（JSON 原子写） |
| IPC（JSON-RPC + TCP/NamedPipe） | §16.2 | ✅ 已实现（TCP 全通，NamedPipe 需 pywin32） |
| 语音链路（采集→VAD→ASR→LLM→TTS→播放） | §3.1 / §6.1 | ✅ Week 2 已实现（silero/funasr/cosyvoice 适配 + 优雅降级） |
| 唤醒词检测（Aivy/贾维斯 可配置） | §3.1 | ✅ Week 2 已实现 |
| WebSocket 实时通道 | §16.3.2 | ✅ Week 2 已实现（RFC6455 零依赖，T1.5） |
| CLI 文本输入 | §3.2 | ✅ 已实现 |
| Tauri 2.0 壳层 | §12 | ✅ 已验证（Rust 1.97 GNU + mingw，`cargo check`/`cargo build` 通过，313MB debug 二进制；插件：热键/通知/自启/更新；GUI 运行需本机 WebView2） |
| 声纹/面部认证 | §9 | ✅ Week 4 已实现（见上表，Phase 1 完成） |
| 托盘 / 热键 / 更新 / 热交换 | §12-15 | ⏳ Phase 3 |

## 设计要点

- **零依赖可运行**：核心链路仅用 Python 标准库；PyYAML/pywin32/sounddevice/silero-vad/funasr/cosyvoice/mem0 均为可选增强
- **四级降级**：真实后端失败 → mock（链路不断）；mem0 缺失 → JSON 记忆；NamedPipe 缺失 → TCP 回环；语音模型缺失 → 能量 VAD + 规则 ASR + 占位 TTS
- **路由诚实报告**：`route.fallback=true` 明确标注降级，不伪装真实推理
- **测试即文档**：204 个 unittest 覆盖配置/人格/上下文/路由(含真实探测)/引擎/记忆(含LLM抽取)/MemFS/工作流(含local执行器)/恢复/摘要/IPC/唤醒/VAD/ASR/TTS/语音会话/认证（声纹/面部/活体/状态机/门控）/视觉/多模态融合/输出路由/通知/情感标签/悬浮输入/MCP（协议/MRTR/八 Server/客户端）/调度器/自进化/端到端联调 全链路

## Phase 1 里程碑状态 ✅ 完成（能听、能想、能说、能记、认主、能看）

| 周 | 内容 | 测试数 |
| --- | --- | --- |
| W1 | 核心对话闭环（路由/人格/上下文/记忆/IPC/CLI + Tauri 骨架） | 38 |
| W2 | 语音链路（ASR/VAD/TTS/唤醒词/WebSocket） | 65 |
| W3 | 记忆与工作流（MemFS/状态图检查点/启动恢复） | 89 |
| W4 | 专属认证（声纹/面部/活体/状态机/多用户） | 117 |
| 收尾 | 视觉/多模态融合/输出路由/通知/情感标签/悬浮输入/端到端联调 | **148** |
