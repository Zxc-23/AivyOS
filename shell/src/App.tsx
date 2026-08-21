import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ChatReply, StatusInfo, fetchStatus, sendChat, inTauri,
  getVoiceStatus, runVoiceTurn, listenVoice, pttStart, pttStop,
  listTasks, createTask, executeTask,
  listSchedules, createSchedule,
  runVibe,
  runBootCheck,
  getVoiceSettings, setVoiceSettings as saveVoiceSettings,
  listModels, getModelsHealth, getModelsCost, setActiveModel, getModelsBackends,
  BackendHealth, CostDashboard,
  listMcpTools, callMcpTool,
  executeFallbackChain,
  listMemory, searchMemory, addMemory,
  listKnowledge, getKnowledge, createKnowledge, updateKnowledge,
  deleteKnowledge, toggleKnowledgeFavorite, searchKnowledge,
  recallKnowledge, getKnowledgeStats, linkKnowledge, backupKnowledge, restoreKnowledge,
  getKnowledgeGraph, exportKnowledge,
  KnowledgeCard as KnowledgeCardType, KnowledgeHit,
  VoiceStatus, VoiceTurnResult,
  TaskInfo, SchedulerJob,
  BootCheckResult, MemoryEntry,
  VibeRunResult, VoiceSettings,
  getModelCatalog, listApiKeys, setApiKey, removeApiKey,
  getVoiceEngines, configVoiceEngine,
  testModelConnection, listProviderModels,
  testCloudModels, CloudTestSummary, CloudTestResult,
  addBackend, removeBackend,
  testTts,
  applyVoiceTts,
  ProviderCatalogEntry, ApiKeyEntry, TestConnectionResult, ListModelsResult,
  SetApiKeyResult, RemoveApiKeyResult,
  apiKeyStorage,
  startWakeLoop, stopWakeLoop, getWakeLoopStatus, listenWakeEvents,
  WakeLoopStatus, WakeEvent,
  readImagePreview, loadVisionModel, releaseVisionModel,
  listSkills, createSkill, updateSkill, deleteSkill, setSkillEnabled,
  Skill as SkillType, SkillResult,
  listTools, setToolEnabled, ManagedTool, ToolsResult,
} from "./chat";
import {
  TrayStateName,
  onTrayEvent,
  onWindowFileDrop,
  setTrayState as setTrayStateCmd,
  setupAutostart,
  setupCloseToTray,
  setupHotkeys,
} from "./tray";

const TRAY_LABEL: Record<string, string> = {
  idle: "待命", listening: "监听中", working: "工作中",
  voice: "语音对话", updating: "更新中", booting: "启动中",
  error: "异常", paused: "已暂停",
};

type NavId =
  | "chat" | "voice" | "task" | "sched" | "vibe"
  | "memory" | "boot" | "voiceset" | "models" | "settings"
  | "skills" | "tools";

interface Msg {
  role: "user" | "assistant";
  text: string;
  /** 用户消息附带的图片（base64 data URL，用于预览展示） */
  image?: string;
}

interface Notif {
  id: number; title: string; body: string;
  type: "success" | "warning" | "danger"; removing?: boolean;
}

/** 知识图谱力导向图（轻量实现：SVG + 简单斥力/弹簧布局 + 拖拽 + 双击编辑）。 */
function KnowledgeGraphView(props: {
  nodes: { id: string; title: string; category: string; favorite: boolean; usage: number }[];
  edges: { source: string; target: string }[];
  onNodeClick: (id: string) => void;
  onNodeDoubleClick?: (id: string) => void;
}) {
  const { nodes, edges, onNodeClick, onNodeDoubleClick } = props;
  const W = 720, H = 320;
  const CX = W / 2, CY = H / 2;
  const R = 14;
  // 圆周布局 + 弹簧松弛
  const posRef = React.useRef(new Map<string, { x: number; y: number }>());
  const [pos, setPos] = React.useState<Map<string, { x: number; y: number }>>(new Map());
  const draggingRef = React.useRef<{ id: string; dx: number; dy: number } | null>(null);
  const svgRef = React.useRef<SVGSVGElement | null>(null);

  React.useEffect(() => {
    const posMap = new Map<string, { x: number; y: number }>();
    const n = nodes.length;
    nodes.forEach((node, i) => {
      const angle = (i / Math.max(1, n)) * Math.PI * 2 - Math.PI / 2;
      const r = Math.min(W, H) * 0.36;
      posMap.set(node.id, { x: CX + r * Math.cos(angle), y: CY + r * Math.sin(angle) });
    });
    // 弹簧松弛：相连节点互相拉近（3 轮）
    for (let iter = 0; iter < 3; iter++) {
      for (const e of edges) {
        const a = posMap.get(e.source), b = posMap.get(e.target);
        if (!a || !b) continue;
        const dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const pull = 0.1 * (d - 90);
        a.x += (dx / d) * pull * 0.5; a.y += (dy / d) * pull * 0.5;
        b.x -= (dx / d) * pull * 0.5; b.y -= (dy / d) * pull * 0.5;
      }
    }
    posRef.current = posMap;
    setPos(posMap);
  }, [nodes, edges]);

  const onMouseDown = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const p = pos.get(id);
    if (!p) return;
    const scaleX = W / rect.width, scaleY = H / rect.height;
    draggingRef.current = { id, dx: (e.clientX - rect.left) * scaleX - p.x, dy: (e.clientY - rect.top) * scaleY - p.y };
  };

  const onMouseMove = (e: React.MouseEvent) => {
    const drag = draggingRef.current;
    const svg = svgRef.current;
    if (!drag || !svg) return;
    const rect = svg.getBoundingClientRect();
    const scaleX = W / rect.width, scaleY = H / rect.height;
    const nx = (e.clientX - rect.left) * scaleX - drag.dx;
    const ny = (e.clientY - rect.top) * scaleY - drag.dy;
    setPos(prev => {
      const next = new Map(prev);
      next.set(drag.id, { x: Math.max(R, Math.min(W - R, nx)), y: Math.max(R, Math.min(H - R, ny)) });
      return next;
    });
  };

  const onMouseUp = () => { draggingRef.current = null; };

  const catColors: Record<string, string> = {
    "个人偏好": "#f59e0b", "概念定义": "#3b82f6", "个人信息": "#10b981",
    "要点": "#8b5cf6", "知识总结": "#ec4899", "习惯日程": "#14b8a6", "其他": "#6b7280",
  };
  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${W} ${H}`}
      style={{ width: "100%", height: "auto", maxHeight: 340, touchAction: "none", cursor: draggingRef.current ? "grabbing" : "grab" }}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      {edges.map((e, i) => {
        const a = pos.get(e.source), b = pos.get(e.target);
        if (!a || !b) return null;
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="rgba(255,255,255,0.25)" strokeWidth={1.5} />;
      })}
      {nodes.map((node) => {
        const p = pos.get(node.id);
        if (!p) return null;
        const color = catColors[node.category] || "#6b7280";
        return (
          <g key={node.id} transform={`translate(${p.x},${p.y})`}
            style={{ cursor: "pointer" }}
            onMouseDown={(e) => onMouseDown(e, node.id)}
            onClick={(e) => { e.stopPropagation(); onNodeClick(node.id); }}
            onDoubleClick={(e) => { e.stopPropagation(); onNodeDoubleClick?.(node.id); }}
          >
            <circle r={R} fill={color} opacity={0.85} stroke={node.favorite ? "#f59e0b" : "#fff"} strokeWidth={node.favorite ? 2.5 : 1} />
            <text textAnchor="middle" dominantBaseline="central" style={{ fontSize: 10, fill: "#fff", fontWeight: 600, pointerEvents: "none" }}>
              {node.title.length > 6 ? node.title.slice(0, 6) + "…" : node.title}
            </text>
          </g>
        );
      })}
      {draggingRef.current && (
        <text x={W / 2} y={H - 8} textAnchor="middle" style={{ fontSize: 10, fill: "rgba(255,255,255,0.5)" }}>
          拖动调整布局 · 双击节点编辑
        </text>
      )}
    </svg>
  );
}

/* ---- 演示模式降级数据（bridge 未就绪时使用） ---- */
const DEMO_VOICE_STATUS: VoiceStatus = {
  asr: "funasr", tts: "cosyvoice", vad: "silero",
  source: "text-sim", sink: "wav-file",
  wake_required: true, wake_words: ["艾薇", "艾维"],
  llm_route_mode: "local",
  asr_ready: true, tts_ready: true,
};

const DEMO_VOICE_TEXTS = [
  '"帮我处理一下邮件，然后把明天会议的材料整理一下"',
  '"把每天检查邮箱的时间改到晚上9点"',
  '"帮我看看这周还有什么事没做完"',
];

const DEMO_TASKS: TaskInfo[] = [
  {
    id: "task_demo_001", title: "处理每日邮件", status: "working",
    steps: [
      { title: "打开邮箱", detail: "启动邮件客户端" },
      { title: "筛选未读邮件", detail: "按优先级排序" },
      { title: "回复重要邮件", detail: "生成并发送草稿" },
      { title: "设置定时任务", detail: "归档低优先级邮件" },
    ],
    current_step: 2,
    logs: [
      "[09:00:12] 邮箱客户端已启动",
      "[09:00:15] 检测到 5 封未读邮件",
      "[09:00:18] 按重要性排序，选取最新 2 封",
      "[09:00:22] 第 1 封已回复",
      "[09:00:25] 正在生成第 2 封回复草稿...",
    ],
    created_at: "2026-08-19 09:00:08",
  },
];

const DEMO_SCHEDULES: SchedulerJob[] = [
  { name: "每日邮件检查", kind: "cron:0 21 * * *", runs: 47, last_run: "2026-08-19 21:00", error: "" },
  { name: "周报整理", kind: "cron:0 17 * * 5", runs: 12, last_run: "2026-08-15 17:00", error: "" },
  { name: "日程提醒", kind: "cron:0 8 * * *", runs: 89, last_run: "2026-08-19 08:00", error: "" },
  { name: "代码仓库检查", kind: "cron:30 9 * * *", runs: 23, last_run: "2026-08-18 09:30", error: "preview 服务超时" },
];

const DEMO_MEMORIES: MemoryEntry[] = [
  { id: "mem_001", text: "博哥习惯在早上 9 点开始处理邮件，喜欢先看未读邮件再回复。", score: 0.95, created_at: "2026-08-10", category: "偏好" },
  { id: "mem_002", text: "张老师 — 项目评审委员会成员，邮件风格正式，需要提前准备材料。", score: 0.92, created_at: "2026-08-12", category: "人脉" },
  { id: "mem_003", text: "每周三 10:00 项目周会，每周五 17:00 需要提交周报。", score: 0.98, created_at: "2026-08-01", category: "日程" },
  { id: "mem_004", text: "Q3 项目评审会议定在 8月20日上午10:00，A会议室。", score: 0.89, created_at: "2026-08-15", category: "重要" },
  { id: "mem_005", text: "邮件回复风格：正式但简洁，先确认事项再补充细节。签名「博哥」。", score: 0.87, created_at: "2026-08-08", category: "技能" },
  { id: "mem_006", text: "当前正在开发 AivyOS 桌面端，使用 Tauri 2.0 + React 技术栈。", score: 0.91, created_at: "2026-08-17", category: "上下文" },
];

const DEMO_MODELS = [
  { mode: "local", model: "Qwen3-4B", available: true },
  { mode: "local", model: "DeepSeek-R1-7B", available: true },
  { mode: "cloud", model: "GPT-4o", available: false },
  { mode: "local", model: "BGE-M3", available: true },
];

/** 本地提供商回退数据（bridge 失败时使用）。 */
const LOCAL_PROVIDERS: ProviderCatalogEntry[] = [
  { id: "deepseek", name: "DeepSeek", category: "cloud-compat", description: "深度求索", base_url: "https://api.deepseek.com/v1", api_key_env: "DEEPSEEK_API_KEY", auth_type: "api_key", website: "https://deepseek.com", default_model: "deepseek-v4-flash", models: [] },
  { id: "openai", name: "OpenAI", category: "cloud-native", description: "GPT 系列", base_url: "https://api.openai.com/v1", api_key_env: "OPENAI_API_KEY", auth_type: "api_key", website: "https://openai.com", default_model: "gpt-4o", models: [] },
  { id: "anthropic", name: "Anthropic", category: "cloud-native", description: "Claude 系列", base_url: "https://api.anthropic.com/v1", api_key_env: "ANTHROPIC_API_KEY", auth_type: "api_key", website: "https://anthropic.com", default_model: "claude-3-sonnet-20240229", models: [] },
  { id: "google", name: "Google", category: "cloud-native", description: "Gemini 系列", base_url: "https://generativelanguage.googleapis.com/v1", api_key_env: "GOOGLE_API_KEY", auth_type: "api_key", website: "https://google.com", default_model: "gemini-1.5-pro", models: [] },
  { id: "qwen", name: "阿里云百炼", category: "cloud-compat", description: "通义系列", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", api_key_env: "DASHSCOPE_API_KEY", auth_type: "api_key", website: "https://aliyun.com", default_model: "qwen-plus", models: [] },
  { id: "siliconflow", name: "SiliconFlow", category: "cloud-compat", description: "硅基流动", base_url: "https://api.siliconflow.cn/v1", api_key_env: "SILICONFLOW_API_KEY", auth_type: "api_key", website: "https://siliconflow.cn", default_model: "deepseek-v4-flash", models: [] },
  { id: "doubao", name: "豆包/火山引擎", category: "cloud-native", description: "豆包大模型", base_url: "https://ark.cn-beijing.volces.com/api/v3", api_key_env: "VOLCENGINE_API_KEY", auth_type: "api_key", website: "https://volcengine.com", default_model: "doubao-pro-32k", models: [] },
  { id: "mistral", name: "Mistral AI", category: "cloud-native", description: "Mistral 系列", base_url: "https://api.mistral.ai/v1", api_key_env: "MISTRAL_API_KEY", auth_type: "api_key", website: "https://mistral.ai", default_model: "mistral-large-latest", models: [] },
  { id: "azure-openai", name: "Azure OpenAI", category: "cloud-native", description: "Azure 托管", base_url: "", api_key_env: "AZURE_OPENAI_API_KEY", auth_type: "api_key", website: "https://azure.microsoft.com", default_model: "gpt-4o", models: [] },
  { id: "ollama", name: "Ollama", category: "local", description: "本地运行", base_url: "http://localhost:11434/v1", api_key_env: "", auth_type: "none", website: "https://ollama.com", default_model: "qwen2.5:7b", models: [] },
  { id: "vllm", name: "vLLM", category: "local", description: "本地推理服务", base_url: "http://localhost:8000/v1", api_key_env: "", auth_type: "none", website: "https://vllm.ai", default_model: "qwen2.5-7b", models: [] },
  { id: "bedrock", name: "AWS Bedrock", category: "cloud-native", description: "亚马逊云", base_url: "", api_key_env: "AWS_ACCESS_KEY_ID", auth_type: "sigv4", website: "https://aws.amazon.com", default_model: "anthropic.claude-3-sonnet", models: [] },
];

const DEMO_BOOT: BootCheckResult = {
  checks: [
    { name: "GPU 加速检测", ok: true, detail: "NVIDIA RTX 4060 · 8GB VRAM" },
    { name: "本地模型加载", ok: true, detail: "Qwen3-4B · 已就绪" },
    { name: "向量数据库连接", ok: true, detail: "ChromaDB · 端口 5432" },
    { name: "语音引擎 (STT/TTS)", ok: true, detail: "Whisper + Edge-TTS" },
    { name: "浏览器自动化引擎", ok: true, detail: "Playwright · Chromium 已就绪" },
    { name: "邮件集成 (Outlook)", ok: true, detail: "已授权" },
    { name: "日历同步", ok: false, detail: "需重新授权 Google Calendar" },
    { name: "记忆向量索引", ok: true, detail: "2,847 条记忆 · 384 维" },
    { name: "系统托盘注册", ok: true, detail: "已注册 · 全局快捷键激活" },
    { name: "自动更新检查", ok: true, detail: "当前版本 V2.0 · 最新版" },
  ],
  progress: 90, passed: 9, total: 10,
  summary: "9/10 项检查通过",
};

const DEMO_VOICE_SETTINGS: VoiceSettings = {
  wake_words: ["艾薇", "艾维"],
  wake_required: true,
  asr_backend: "funasr",
  asr_model: "paraformer-zh",
  tts_backend: "auto",
  tts_model: "",
  tts_voice: "zh_female_xiaohe_uranus_bigtts",
  tts_speed: 1.0,
  tts_resource_id: "seed-tts-2.0",
  language: "zh",
  silence_timeout_s: 3.0,
};

/* ---- 辅助函数 ---- */
function getModelIcon(mode: string, model: string): { icon: string; iconBg: string; desc: string } {
  const name = model.toLowerCase();
  if (name.includes("qwen")) return { icon: "🧠", iconBg: "rgba(59,130,246,0.15)", desc: "通义千问" };
  if (name.includes("deepseek")) return { icon: "🔮", iconBg: "rgba(139,92,246,0.15)", desc: "深度推理" };
  if (name.includes("gpt")) return { icon: "☁️", iconBg: "rgba(6,182,212,0.15)", desc: "多模态推理" };
  if (name.includes("bge") || name.includes("embed")) return { icon: "🎯", iconBg: "rgba(16,185,129,0.15)", desc: "向量嵌入" };
  if (mode === "cloud") return { icon: "☁️", iconBg: "rgba(6,182,212,0.15)", desc: "云端 API" };
  return { icon: "🤖", iconBg: "rgba(148,163,184,0.15)", desc: mode };
}

function getModelTags(mode: string, available: boolean) {
  return [
    { text: mode === "local" ? "本地" : "云端", color: mode === "local" ? "var(--accent)" : "var(--accent2)" },
    { text: available ? "已就绪" : "未连接", color: available ? "var(--success)" : "var(--danger)" },
  ];
}

function getMemoryColor(category?: string): { color: string; bg: string } {
  switch (category) {
    case "偏好": return { color: "var(--accent)", bg: "rgba(59,130,246,0.1)" };
    case "人脉": return { color: "var(--accent3)", bg: "rgba(139,92,246,0.1)" };
    case "日程": return { color: "var(--accent2)", bg: "rgba(6,182,212,0.1)" };
    case "重要": return { color: "var(--warning)", bg: "rgba(245,158,11,0.1)" };
    case "技能": return { color: "var(--success)", bg: "rgba(16,185,129,0.1)" };
    default: return { color: "var(--muted2)", bg: "rgba(100,116,139,0.1)" };
  }
}

export default function App() {
  const [nav, setNav] = useState<NavId>("boot"); // 启动先进入系统自检
  const [messages, setMessages] = useState<Msg[]>([
    { role: "assistant", text: "早上好！我是 Aivy，您的私人 AI 助理。有什么可以帮您？" },
  ]);
  const [input, setInput] = useState("");
  // 待发送图片附件（拖拽/粘贴）：{path 原始路径, dataUrl 预览, mime}
  const [pendingImage, setPendingImage] = useState<{ path?: string; dataUrl: string; mime: string; name: string } | null>(null);
  const [imageSending, setImageSending] = useState(false);
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [trayState, setTrayStateUi] = useState<TrayStateName>("booting");
  const [notifs, setNotifs] = useState<Notif[]>([]);
  const notifIdRef = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [bridgeReady, setBridgeReady] = useState(false);

  // 聊天自动滚动：消息变化时滚动到底部（最新消息）
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // 语音播报播放句柄（供打断：PTT 开始 / 新播报 / 切页时停止当前播放）
  const voicePlaybackRef = useRef<{ ctx: AudioContext | null; source: AudioBufferSourceNode | null }>({ ctx: null, source: null });

  const stopVoicePlayback = useCallback(() => {
    const p = voicePlaybackRef.current;
    if (p.source) {
      try { p.source.stop(); } catch {}
      p.source.disconnect();
      p.source = null;
    }
    if (p.ctx) {
      try { p.ctx.close(); } catch {}
      p.ctx = null;
    }
  }, []);

  /* ---- Voice screen state ---- */
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [voiceTurnResult, setVoiceTurnResult] = useState<VoiceTurnResult | null>(null);
  const [voiceTextInput, setVoiceTextInput] = useState("帮我处理一下邮件");
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [voiceListening, setVoiceListening] = useState(false);
  const [voiceStatusLoading, setVoiceStatusLoading] = useState(false);

  /* ---- Wake Loop (后台唤醒) state ---- */
  const [wakeLoopActive, setWakeLoopActive] = useState(false);
  const [wakeLoopCount, setWakeLoopCount] = useState(0);
  const [lastWakeEvent, setLastWakeEvent] = useState<WakeEvent | null>(null);
  const wakeUnlistenRef = useRef<(() => void) | null>(null);

  /* ---- Task screen state ---- */
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [taskDescInput, setTaskDescInput] = useState("");
  const [tasksLoading, setTasksLoading] = useState(false);
  const [taskExecuting, setTaskExecuting] = useState<string | null>(null);

  /* ---- Scheduler screen state ---- */
  const [schedules, setSchedules] = useState<SchedulerJob[]>([]);
  const [activeSchedIdx, setActiveSchedIdx] = useState(0);
  const [schedLoading, setSchedLoading] = useState(false);
  const [schedNameInput, setSchedNameInput] = useState("");
  const [schedCronInput, setSchedCronInput] = useState("0 21 * * *");
  const [schedHandlerInput, setSchedHandlerInput] = useState("检查并处理未读邮件");
  const [showAddSched, setShowAddSched] = useState(false);

  /* ---- Vibe Coding state ---- */
  const [vibeRequest, setVibeRequest] = useState("创建一个项目周会 PPT 大纲");
  const [vibeResult, setVibeResult] = useState<VibeRunResult | null>(null);
  const [vibeLoading, setVibeLoading] = useState(false);

  /* ---- Memory state ---- */
  const [memories, setMemories] = useState<MemoryEntry[]>([]);
  const [memorySearchQuery, setMemorySearchQuery] = useState("");
  const [memoryNewText, setMemoryNewText] = useState("");
  const [memoryLoading, setMemoryLoading] = useState(false);

  /* ---- Knowledge Cards state ---- */
  const [kCards, setKCards] = useState<KnowledgeCardType[]>([]);
  const [kLoading, setKLoading] = useState(false);
  const [kSearch, setKSearch] = useState("");
  const [kCategory, setKCategory] = useState("");
  const [kTag, setKTag] = useState("");
  const [kSort, setKSort] = useState("updated");
  const [kFavOnly, setKFavOnly] = useState(false);
  const [kStats, setKStats] = useState<{ total: number; favorites: number; categories: string[]; tags: string[] }>({ total: 0, favorites: 0, categories: [], tags: [] });
  const [kExpanded, setKExpanded] = useState<Record<string, boolean>>({});
  const [kEditId, setKEditId] = useState<string | null>(null);
  const [kEditForm, setKEditForm] = useState<{ title: string; summary: string; content: string; category: string; tags: string }>({ title: "", summary: "", content: "", category: "其他", tags: "" });
  const [kShowNew, setKShowNew] = useState(false);
  const [kRelated, setKRelated] = useState<Record<string, KnowledgeCardType[]>>({});
  const [kKnowledgeHits, setKKnowledgeHits] = useState<KnowledgeHit[]>([]); // 对话中自动调用的卡片
  // 图谱 / 导出 / 关联管理
  const [kShowGraph, setKShowGraph] = useState(false);
  const [kGraph, setKGraph] = useState<{ nodes: { id: string; title: string; category: string; favorite: boolean; usage: number }[]; edges: { source: string; target: string }[] }>({ nodes: [], edges: [] });
  const [kLinkTarget, setKLinkTarget] = useState<string>(""); // 当前展开卡片要关联的目标
  const [kExportText, setKExportText] = useState<string | null>(null);

  /* ---- Boot/Self-check state ---- */
  const [bootResult, setBootResult] = useState<BootCheckResult | null>(null);
  const [bootLoading, setBootLoading] = useState(false);

  /* ---- Voice settings state ---- */
  const [voiceSettings, setVoiceSettings] = useState<VoiceSettings | null>(null);
  const [vsetWakeWord, setVsetWakeWord] = useState("艾薇");
  const [vsetContinuous, setVsetContinuous] = useState(true);
  const [vsetActiveVoice, setVsetActiveVoice] = useState(0);
  const [vsetAsrEngine, setVsetAsrEngine] = useState("");
  const [vsetLanguage, setVsetLanguage] = useState("");
  const [vsetLoading, setVsetLoading] = useState(false);

  /* ---- Model management state ---- */
  const [models, setModels] = useState<{ mode: string; model: string; available: boolean; active?: boolean }[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [activeModelName, setActiveModelName] = useState<string | null>(null);
  const [modelHealth, setModelHealth] = useState<BackendHealth[]>([]);
  const [modelCost, setModelCost] = useState<CostDashboard | null>(null);
  const [modelsTab, setModelsTab] = useState<"health" | "cost" | "list">("health");
  const [catalog, setCatalog] = useState<ProviderCatalogEntry[]>([]);
  const [catalogFilter, setCatalogFilter] = useState<string>("all");
  const [showAddModelDialog, setShowAddModelDialog] = useState(false);
  const [apiKeys, setApiKeys] = useState<Record<string, ApiKeyEntry>>({});
  const [editingKeyEnv, setEditingKeyEnv] = useState<string>("");
  const [voiceEngines, setVoiceEngines] = useState<any>(null);
  const [addModelProvider, setAddModelProvider] = useState("");
  const [addModelName, setAddModelName] = useState("");
  const [addModelApiKey, setAddModelApiKey] = useState("");
  const [addModelBaseUrl, setAddModelBaseUrl] = useState("");
  const [addModelApiType, setAddModelApiType] = useState("chat_completions");
  const [addModelThinking, setAddModelThinking] = useState(false);
  const [addModelInputText, setAddModelInputText] = useState(true);
  const [addModelInputImage, setAddModelInputImage] = useState(false);
  const [addModelInputAudio, setAddModelInputAudio] = useState(false);
  const [addModelInputVideo, setAddModelInputVideo] = useState(false);
  const [addModelContextWindow, setAddModelContextWindow] = useState(32768);
  const [addModelMaxOutput, setAddModelMaxOutput] = useState(4096);
  const [addModelTesting, setAddModelTesting] = useState(false);
  const [addModelTestResult, setAddModelTestResult] = useState<TestConnectionResult | null>(null);
  const [addModelPresetModels, setAddModelPresetModels] = useState<ListModelsResult | null>(null);
  const [addModelFetchingModels, setAddModelFetchingModels] = useState(false);
  const [editingProviderId, setEditingProviderId] = useState<string | null>(null);
  const [providerSearch, setProviderSearch] = useState("");
  const [providerFilter, setProviderFilter] = useState<"all" | "configured" | "unconfigured" | "local" | "cloud">("all");
  const [providerSort, setProviderSort] = useState<"name" | "status" | "category">("name");
  // 云端模型批量连通性测试
  const [cloudTesting, setCloudTesting] = useState(false);
  const [cloudTestSummary, setCloudTestSummary] = useState<CloudTestSummary | null>(null);
  // 技能管理
  const [skills, setSkills] = useState<SkillType[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillFormOpen, setSkillFormOpen] = useState(false);
  const [skillForm, setSkillForm] = useState<{
    id: string | null; name: string; description: string; category: string;
    keywords: string; system_prompt: string; enabled: boolean;
  }>({ id: null, name: "", description: "", category: "自定义", keywords: "", system_prompt: "", enabled: true });
  // 工具管理
  const [managedTools, setManagedTools] = useState<ManagedTool[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolFilter, setToolFilter] = useState<"all" | "enabled" | "disabled">("all");
  const [editingForm, setEditingForm] = useState<{
    providerId: string;
    apiKey: string;
    baseUrl: string;
    fetchedModels: any[];
    fetching: boolean;
    customSettingsOpen: boolean;
    addedModels: string[];
    testing: boolean;
    testResult: TestConnectionResult | null;
  } | null>(null);
  const [showAddProviderDropdown, setShowAddProviderDropdown] = useState(false);
  const [showCustomProviderForm, setShowCustomProviderForm] = useState(false);
  const [customProvider, setCustomProvider] = useState({
    backendType: "",
    name: "",
    baseUrl: "",
    apiKey: "",
    defaultModel: "",
  });
  const [vsetDoubaoSpeed, setVsetDoubaoSpeed] = useState(1.0);
  const [vsetDoubaoVolume, setVsetDoubaoVolume] = useState(1.0);
  const [vsetDoubaoPitch, setVsetDoubaoPitch] = useState(1.0);
  const [vsetEngineConfigEngine, setVsetEngineConfigEngine] = useState("doubao-tts");

  /* ---- Voice settings: cloud + emotion ---- */
  const [vsetEmotion, setVsetEmotion] = useState("neutral");
  const [vsetEmotionAuto, setVsetEmotionAuto] = useState(true);
  const [vsetCloudAsr, setVsetCloudAsr] = useState("");
  const [vsetCloudTts, setVsetCloudTts] = useState("");

  /* ---- Voice settings: cloud providers ---- */
  const [vsetAsrProvider, setVsetAsrProvider] = useState("aliyun");
  const [vsetAsrApiKey, setVsetAsrApiKey] = useState("");
  const [vsetTtsProvider, setVsetTtsProvider] = useState("auto");
  const [vsetTtsVoice, setVsetTtsVoice] = useState("zh_female_xiaohe_uranus_bigtts");
  const [vsetTtsSpeed, setVsetTtsSpeed] = useState(1.0);
  const [vsetTtsApiKey, setVsetTtsApiKey] = useState("");
  const [vsetTtsResourceId, setVsetTtsResourceId] = useState("");
  const [vsetPlaybackLive, setVsetPlaybackLive] = useState(true);
  const [vsetRobotEffect, setVsetRobotEffect] = useState(false);
  const [vsetRobotUnlocked, setVsetRobotUnlocked] = useState(false);
  const [vsetRobotPwd, setVsetRobotPwd] = useState("");
  const [vsetSensitivity, setVsetSensitivity] = useState(0.008);
  const [vsetListeningLang, setVsetListeningLang] = useState("zh-CN");
  const [vsetMicDevice, setVsetMicDevice] = useState("default");
  const [vsetOutputDevice, setVsetOutputDevice] = useState("auto");
  const [vsetTesting, setVsetTesting] = useState(false);
  const [vsetTestResult, setVsetTestResult] = useState<string>("");

  /* ---- Voice provider options ---- */
  const ASR_PROVIDERS = [
    { id: "aliyun", name: "阿里云百炼 (推荐)", hint: "阿里云 / 腾讯云 / 讯飞 / 火山豆包 ASR Key" },
    { id: "tencent", name: "腾讯云 ASR", hint: "腾讯云一句话识别 API Key" },
    { id: "iflytek", name: "讯飞语音", hint: "讯飞语音听写 API Key" },
    { id: "volcengine", name: "火山引擎 (豆包)", hint: "火山引擎流式语音识别" },
    { id: "deepgram", name: "Deepgram", hint: "Deepgram API Key (国际)" },
    { id: "edge", name: "Edge-Speech", hint: "微软 Edge 语音服务" },
  ];
  const TTS_PROVIDERS = [
    { id: "auto", name: "自动 (推荐：豆包 → Edge-TTS → Mock)" },
    { id: "doubao-tts", name: "豆包 (方舟，流式，中文最自然)" },
    { id: "bytedance", name: "火山引擎 · 字节跳动" },
    { id: "elevenlabs", name: "ElevenLabs (英文)" },
    { id: "edge-tts", name: "Edge-TTS (微软免费云端)" },
    { id: "cosyvoice", name: "CosyVoice (本地离线)" },
    { id: "volcengine", name: "火山引擎" },
  ];
  const TTS_VOICES: Record<string, { id: string; name: string }[]> = {
    "auto": [
      { id: "zh_female_xiaohe_uranus_bigtts", name: "小何 2.0 (女声·通用)" },
      { id: "zh_female_vv_uranus_bigtts", name: "Vivi 2.0 (女声·活泼)" },
      { id: "zh_female_sophie_uranus_bigtts", name: "魅力苏菲 2.0 (女声·知性)" },
      { id: "zh_female_cancan_uranus_bigtts", name: "知性灿灿 2.0 (女声·角色扮演)" },
      { id: "zh_female_shuangkuaisisi_uranus_bigtts", name: "爽快思思 2.0 (女声·通用)" },
      { id: "zh_female_linjianvhai_uranus_bigtts", name: "邻家女孩 2.0 (女声·通用)" },
      { id: "zh_female_peiqi_uranus_bigtts", name: "佩奇猪 2.0 (女声·视频配音)" },
      { id: "zh_male_m191_uranus_bigtts", name: "云舟 2.0 (男声·通用)" },
      { id: "zh_male_taocheng_uranus_bigtts", name: "小天 2.0 (男声·通用)" },
      { id: "zh_male_liufei_uranus_bigtts", name: "刘飞 2.0 (男声·通用)" },
      { id: "zh_male_shaonianzixin_uranus_bigtts", name: "少年梓辛 2.0 (男声·少年)" },
      { id: "zh_male_dayi_uranus_bigtts", name: "大壹 2.0 (男声·视频配音)" },
      { id: "en_male_tim_uranus_bigtts", name: "Tim (英语男声)" },
      { id: "en_female_dacey_uranus_bigtts", name: "Dacey (英语女声)" },
    ],
    "doubao-tts": [
      { id: "zh_female_xiaohe_uranus_bigtts", name: "小何 2.0 (女声·通用)" },
      { id: "zh_female_vv_uranus_bigtts", name: "Vivi 2.0 (女声·活泼)" },
      { id: "zh_female_sophie_uranus_bigtts", name: "魅力苏菲 2.0 (女声·知性)" },
      { id: "zh_female_cancan_uranus_bigtts", name: "知性灿灿 2.0 (女声·角色扮演)" },
      { id: "zh_female_shuangkuaisisi_uranus_bigtts", name: "爽快思思 2.0 (女声·通用)" },
      { id: "zh_female_linjianvhai_uranus_bigtts", name: "邻家女孩 2.0 (女声·通用)" },
      { id: "zh_female_peiqi_uranus_bigtts", name: "佩奇猪 2.0 (女声·视频配音)" },
      { id: "zh_male_m191_uranus_bigtts", name: "云舟 2.0 (男声·通用)" },
      { id: "zh_male_taocheng_uranus_bigtts", name: "小天 2.0 (男声·通用)" },
      { id: "zh_male_liufei_uranus_bigtts", name: "刘飞 2.0 (男声·通用)" },
      { id: "zh_male_shaonianzixin_uranus_bigtts", name: "少年梓辛 2.0 (男声·少年)" },
      { id: "zh_male_dayi_uranus_bigtts", name: "大壹 2.0 (男声·视频配音)" },
      { id: "en_male_tim_uranus_bigtts", name: "Tim (英语男声)" },
      { id: "en_female_dacey_uranus_bigtts", name: "Dacey (英语女声)" },
    ],
    "bytedance": [
      { id: "female-1", name: "女声 1" },
      { id: "male-1", name: "男声 1" },
    ],
    "elevenlabs": [
      { id: "rachel", name: "Rachel (English)" },
      { id: "adam", name: "Adam (English)" },
      { id: "bella", name: "Bella (English)" },
      { id: "antoni", name: "Antoni (English)" },
    ],
    "edge-tts": [
      { id: "zh-CN-XiaoxiaoNeural", name: "晓晓 (女声·推荐)" },
      { id: "zh-CN-XiaoyiNeural", name: "晓伊 (女声·温柔)" },
      { id: "zh-CN-XiaomengNeural", name: "晓梦 (女声·知性)" },
      { id: "zh-CN-XiaohanNeural", name: "晓涵 (女声·亲切)" },
      { id: "zh-CN-YunxiNeural", name: "云希 (男声·推荐)" },
      { id: "zh-CN-YunjianNeural", name: "云健 (男声·有力)" },
      { id: "zh-CN-YunyangNeural", name: "云扬 (男声·阳光)" },
      { id: "zh-CN-YunzeNeural", name: "云泽 (男声·温和)" },
      { id: "en-US-AriaNeural", name: "Aria (English Female)" },
      { id: "en-US-GuyNeural", name: "Guy (English Male)" },
    ],
    "cosyvoice": [
      { id: "zh_female_xiaohe", name: "小何 (本地女声)" },
      { id: "zh_male_m191", name: "云舟 (本地男声)" },
    ],
    "volcengine": [
      { id: "xiaoming", name: "小明" },
      { id: "xiaohong", name: "小红" },
    ],
  };
  const MIC_DEVICES = ["系统默认麦克风", "麦克风阵列 (高质量)", "USB 麦克风", "HDMI 音频输出"];
  const OUTPUT_DEVICES = ["自动 (跟随系统，避开虚拟设备)", "扬声器 (Realtek)", "耳机 (蓝牙耳机)", "HDMI 音频输出"];

  /* ---- Theme system ---- */
  type ThemeId = "ink" | "aurora" | "twilight";
  const THEMES: { id: ThemeId; name: string; desc: string; colors: string[] }[] = [
    { id: "ink", name: "墨韵深空", desc: "深邃内敛 · 护眼蓝调", colors: ["#0b0f1a", "#6c8cff", "#b088ff"] },
    { id: "aurora", name: "极光青域", desc: "清爽澄澈 · 青蓝渐变", colors: ["#0a1628", "#22d3ee", "#2dd4bf"] },
    { id: "twilight", name: "暮光紫境", desc: "温润优雅 · 紫粉梦境", colors: ["#120e1a", "#c084fc", "#f472b6"] },
  ];
  const [currentTheme, setCurrentTheme] = useState<ThemeId>("ink");
  const applyTheme = useCallback((id: ThemeId) => {
    setCurrentTheme(id);
    document.documentElement.setAttribute("data-theme", id === "ink" ? "" : id);
  }, []);

  /* ---- Demo mode fallback state ---- */
  const [demoVoiceIdx, setDemoVoiceIdx] = useState(0);

  /* ================================================================
   *  Notification helper
   * ================================================================ */
  const showNotification = useCallback((title: string, body: string, type: "success" | "warning" | "danger" = "success") => {
    const id = ++notifIdRef.current;
    setNotifs(prev => [...prev, { id, title, body, type }]);
    setTimeout(() => {
      setNotifs(prev => prev.map(n => n.id === id ? { ...n, removing: true } : n));
      setTimeout(() => setNotifs(prev => prev.filter(n => n.id !== id)), 300);
    }, 4000);
  }, []);

  const updateTrayState = useCallback((state: TrayStateName) => {
    setTrayStateUi(state);
    setTrayStateCmd(state).catch(() => {});
  }, []);

  /* ================================================================
   *  Bridge readiness polling
   * ================================================================ */
  useEffect(() => {
    let cancelled = false;
    let retries = 0;
    const tryConnect = async () => {
      if (cancelled) return;
      try {
        const s = await fetchStatus();
        if (cancelled) return;
        setStatus(s);
        setBridgeReady(true);
        updateTrayState("idle");
        showNotification("艾薇已就绪", "早上好！今天有 2 个会议，已帮您检查了 5 封未读邮件。", "success");
        return;
      } catch {
        retries++;
        if (retries >= 60) {
          if (!cancelled) {
            showNotification("核心未连接", "仍在演示模式。请确保 Python 核心已启动。", "warning");
            updateTrayState("error");
          }
          return;
        }
        setTimeout(tryConnect, 800);
      }
    };
    updateTrayState("booting");
    tryConnect();
    return () => { cancelled = true; };
  }, [updateTrayState, showNotification]);

  /* ================================================================
   *  Wake Loop 自动启动（bridge 就绪后）
   * ================================================================ */
  useEffect(() => {
    if (!bridgeReady) return;
    if (!inTauri) return;

    let cancelled = false;

    const initWakeLoop = async () => {
      try {
        // 订阅唤醒事件
        const unlisten = await listenWakeEvents((event: WakeEvent) => {
          setLastWakeEvent(event);
          setWakeLoopCount(c => c + 1);
          // 自动切换到语音模式并触发聆听
          setNav("voice");
          showNotification("🔔 已唤醒", `识别到: "${event.text}"`, "success");
          // 自动触发语音聆听
          setTimeout(() => {
            handleVoiceListen();
          }, 500);
        });
        wakeUnlistenRef.current = unlisten;

        // 启动后台监听循环
        const result = await startWakeLoop();
        if (result.ok) {
          setWakeLoopActive(true);
          console.log("[AivyOS] WakeLoop 已启动");
        }
      } catch (e) {
        console.warn("[AivyOS] WakeLoop 启动失败:", e);
      }
    };

    initWakeLoop();
    return () => {
      cancelled = true;
      if (wakeUnlistenRef.current) {
        wakeUnlistenRef.current();
        wakeUnlistenRef.current = null;
      }
      stopWakeLoop().catch(() => {});
    };
  }, [bridgeReady]);

  /* ================================================================
   *  Tauri tray/hotkey/drag-drop setup
   * ================================================================ */
  useEffect(() => {
    setupCloseToTray().catch(() => {});
    setupAutostart().catch(() => {});
    const cleanupFns: (() => void)[] = [];
    setupHotkeys({
      wake: () => { setNav("chat"); },
      voice: () => { setNav("voice"); },
    }).then(fn => { if (typeof fn === "function") cleanupFns.push(fn); }).catch(() => {});
    onTrayEvent((ev) => {
      if (ev.kind === "click" && ev.double) setNav("chat");
    }).then(fn => { if (typeof fn === "function") cleanupFns.push(fn); }).catch(() => {});
    return () => { cleanupFns.forEach(fn => fn()); };
  }, [showNotification]);

  /* ================================================================
   *  Chat handlers
   * ================================================================ */

  // 拖拽图片 → 读取预览（Tauri onDragDropEvent 给本地路径）
  const handleImageDrop = useCallback(async (paths: string[]) => {
    const imgExts = ["png", "jpg", "jpeg", "gif", "webp", "bmp"];
    const imgPath = paths.find(p => {
      const ext = p.split(".").pop()?.toLowerCase() ?? "";
      return imgExts.includes(ext);
    });
    if (!imgPath) {
      showNotification("仅支持图片", "请拖入 PNG/JPG/GIF/WebP/BMP 图片", "warning");
      return;
    }
    setImageSending(true);
    try {
      if (!bridgeReady) {
        showNotification("演示模式", "连接核心后可拖入图片让艾薇看图回答", "warning");
        return;
      }
      const res = await readImagePreview(imgPath);
      if (!res.ok || !res.base64) {
        showNotification("读取失败", res.error || "无法读取图片", "danger");
        return;
      }
      const name = imgPath.split(/[\\/]/).pop() ?? imgPath;
      setPendingImage({
        path: imgPath,
        dataUrl: `data:${res.mime || "image/png"};base64,${res.base64}`,
        mime: res.mime || "image/png",
        name,
      });
      showNotification("已添加图片", `${name} · 随下一条消息发送`, "success");
    } catch (e) {
      showNotification("读取失败", e instanceof Error ? e.message : String(e), "danger");
    } finally {
      setImageSending(false);
    }
  }, [bridgeReady, showNotification]);

  // 窗口拖拽图片（Tauri onDragDropEvent）→ 附件预览
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    onWindowFileDrop((paths) => {
      void handleImageDrop(paths);
    }).then(fn => { unlisten = fn; }).catch(() => {});
    return () => { unlisten?.(); };
  }, [handleImageDrop]);

  // 键盘粘贴图片（Ctrl+V）→ 剪贴板 base64 附件
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (!file) continue;
          const reader = new FileReader();
          reader.onload = () => {
            const dataUrl = String(reader.result || "");
            setPendingImage({
              dataUrl,
              mime: item.type,
              name: "剪贴板图片.png",
            });
            showNotification("已粘贴图片", "随下一条消息发送", "success");
          };
          reader.readAsDataURL(file);
          break;
        }
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [showNotification]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    const hasImage = !!pendingImage;
    if (!text && !hasImage) return;
    const userMsg: Msg = { role: "user", text: text || "（图片）" };
    if (pendingImage?.dataUrl) userMsg.image = pendingImage.dataUrl;
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setPendingImage(null);
    updateTrayState("working");
    if (!bridgeReady) {
      setTimeout(() => {
        setMessages(prev => [...prev, { role: "assistant", text: "（演示模式）核心尚未连接，请通过 npm run tauri dev 启动完整应用。" }]);
        updateTrayState("idle");
      }, 600);
      return;
    }
    try {
      const reply: ChatReply = await sendChat(
        text,
        undefined,
        hasImage ? { path: pendingImage?.path, b64: pendingImage?.dataUrl.split(",")[1] } : undefined
      );
      setMessages(prev => [...prev, { role: "assistant", text: reply.text }]);
      // 知识卡片自动调用：对话中呈现相关卡片
      if (reply.knowledge_hits && reply.knowledge_hits.length > 0) {
        setKKnowledgeHits(reply.knowledge_hits);
      }
      updateTrayState("idle");
    } catch (e) {
      setMessages(prev => [...prev, { role: "assistant", text: "抱歉，出现了错误：" + (e instanceof Error ? e.message : String(e)) }]);
      updateTrayState("error");
    }
  }, [input, pendingImage, bridgeReady, updateTrayState]);

  const quickSend = useCallback((text: string) => {
    setInput(text);
    setTimeout(() => {
      setMessages(prev => [...prev, { role: "user", text }]);
      setInput("");
      if (!bridgeReady) {
        setMessages(prev => [...prev, { role: "assistant", text: "（演示模式）核心尚未连接。" }]);
        return;
      }
      updateTrayState("working");
      sendChat(text).then(reply => {
        setMessages(prev => [...prev, { role: "assistant", text: reply.text }]);
        updateTrayState("idle");
      }).catch(() => updateTrayState("error"));
    }, 50);
  }, [bridgeReady, updateTrayState]);

  /* ================================================================
   *  Data loading per screen
   * ================================================================ */

  // ---- Voice screen ----
  const loadVoiceStatus = useCallback(async () => {
    setVoiceStatusLoading(true);
    try {
      if (!bridgeReady) { setVoiceStatus(DEMO_VOICE_STATUS); return; }
      const st = await getVoiceStatus();
      setVoiceStatus(st);
    } catch { setVoiceStatus(DEMO_VOICE_STATUS); }
    finally { setVoiceStatusLoading(false); }
  }, [bridgeReady]);

  const handleRunVoiceTurn = useCallback(async () => {
    const text = voiceTextInput.trim();
    if (!text) return;
    setVoiceLoading(true);
    updateTrayState("voice");
    try {
      if (!bridgeReady) {
        await new Promise(r => setTimeout(r, 600));
        const demoResult: VoiceTurnResult = {
          ok: true, text,
          reply: "好的，我正在帮您处理。完成后会通知您~",
          model: "demo-mode", route: { mode: "mock", model: "demo", reason: "bridge not ready", fallback: true },
          latency_ms: 600, asr_backend: "demo", tts_backend: "demo", fallback: true,
        };
        setVoiceTurnResult(demoResult);
        showNotification("演示模式", "语音对话以模拟模式运行", "warning");
        return;
      }
      const result = await runVoiceTurn(text);
      setVoiceTurnResult(result);
      if (result.reply) {
        setMessages(prev => [...prev, { role: "user", text }]);
        setMessages(prev => [...prev, { role: "assistant", text: result.reply! }]);
      }
      if (result.wav_b64) {
        try {
          const binary = atob(result.wav_b64);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
          const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
          const audioBuffer = await audioCtx.decodeAudioData(bytes.buffer);
          const source = audioCtx.createBufferSource();
          source.buffer = audioBuffer;
          source.connect(audioCtx.destination);
          source.start(0);
          source.onended = () => { try { audioCtx.close(); } catch {} };
        } catch (e) {
          console.warn("语音播放失败:", e);
        }
      }
      if (result.fallback) showNotification("降级模式", "语音组件未就绪，已使用对话引擎回复", "warning");
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      setVoiceTurnResult({ ok: false, text, reply: errMsg });
      showNotification("语音错误", errMsg, "danger");
    } finally {
      setVoiceLoading(false);
      updateTrayState("idle");
    }
  }, [voiceTextInput, bridgeReady, updateTrayState, showNotification]);

  // ---- 共享的语音结果处理（handleVoiceListen 与 PTT 共用）----
  const handleVoiceResult = useCallback(async (result: VoiceTurnResult) => {
    setVoiceTurnResult(result);
    if (result.continuous) {
      showNotification(
        "连续对话",
        `已进入连续对话（剩 ${result.continuous.turns_left} 轮 / ${result.continuous.window_left_s}s），无需重复唤醒词`,
        "success",
      );
    }
    if (result.error_type === "no_speech_detected") {
      showNotification("未检测到语音", "请靠近麦克风并重新点击说话", "warning");
      return;
    }
    if (result.error_type === "wake_word_missed") {
      showNotification("唤醒词未识别", `已识别: "${result.text}" — 请说唤醒词后再试`, "warning");
      return;
    }
    if (!result.ok && result.error) {
      showNotification("语音错误", result.error, "danger");
      return;
    }
    if (result.reply) {
      setMessages(prev => [...prev, { role: "user", text: result.text || "(语音输入)" }]);
      setMessages(prev => [...prev, { role: "assistant", text: result.reply! }]);
    }
    if (result.wav_b64) {
      try {
        const binary = atob(result.wav_b64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        // 打断上一段播报（连续语音时）
        stopVoicePlayback();
        const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
        const audioBuffer = await audioCtx.decodeAudioData(bytes.buffer);
        const source = audioCtx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioCtx.destination);
        voicePlaybackRef.current = { ctx: audioCtx, source };
        source.onended = () => {
          if (voicePlaybackRef.current.source === source) {
            voicePlaybackRef.current.source = null;
          }
          try { audioCtx.close(); } catch {}
          if (voicePlaybackRef.current.ctx === audioCtx) voicePlaybackRef.current.ctx = null;
        };
        source.start(0);
      } catch (e) {
        console.warn("语音播放失败:", e);
      }
    }
    if (result.fallback) showNotification("降级模式", "语音组件部分不可用", "warning");
    if (!result.ok) showNotification("语音识别失败", result.error || "未检测到语音输入", "danger");
  }, [showNotification]);

  const handleVoiceListen = useCallback(async () => {
    setVoiceLoading(true);
    setVoiceListening(true);
    updateTrayState("voice");
    try {
      if (!bridgeReady) {
        await new Promise(r => setTimeout(r, 1500));
        const demoResult: VoiceTurnResult = {
          ok: true, text: "（演示模式：真实麦克风采集）",
          reply: "演示模式下暂不支持真实麦克风。请连接 Python 核心后体验。",
          model: "demo-mode", route: { mode: "mock", model: "demo", reason: "bridge not ready", fallback: true },
          latency_ms: 1500, asr_backend: "demo", tts_backend: "demo", fallback: true,
        };
        setVoiceTurnResult(demoResult);
        showNotification("演示模式", "连接核心后即可使用真实语音", "warning");
        return;
      }
      const result = await listenVoice(vsetContinuous);
      await handleVoiceResult(result);
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      setVoiceTurnResult({ ok: false, text: "", reply: errMsg });
      showNotification("语音错误", errMsg, "danger");
    } finally {
      setVoiceLoading(false);
      setVoiceListening(false);
      updateTrayState("idle");
    }
  }, [bridgeReady, updateTrayState, showNotification, vsetContinuous, handleVoiceResult]);

  // ---- PTT（按住说话）：按住空格/鼠标开始采集，松开处理 ----
  const pttActiveRef = useRef(false);
  const voiceReady = bridgeReady && voiceStatus?.asr_ready !== false;
  const handlePttStart = useCallback(async () => {
    if (pttActiveRef.current) return;
    if (!voiceReady) return; // 核心未就绪/模型预热中：不进入聆听状态（显示加载门）
    // 打断正在播报的语音（用户开始说话时立即停止 Aivy 播报）
    stopVoicePlayback();
    pttActiveRef.current = true;
    setVoiceListening(true);
    updateTrayState("voice");
    try {
      await pttStart();
    } catch (e) {
      console.warn("PTT 开始失败:", e);
      pttActiveRef.current = false;
      setVoiceListening(false);
      updateTrayState("idle");
    }
  }, [voiceReady, updateTrayState, stopVoicePlayback]);

  const handlePttStop = useCallback(async () => {
    if (!pttActiveRef.current) return;
    pttActiveRef.current = false;
    setVoiceListening(false);
    updateTrayState("idle");
    try {
      if (!bridgeReady) {
        setVoiceListening(false);
        return;
      }
      setVoiceLoading(true);
      const result = await pttStop(vsetContinuous);
      await handleVoiceResult(result);
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      setVoiceTurnResult({ ok: false, text: "", reply: errMsg });
      showNotification("语音错误", errMsg, "danger");
    } finally {
      setVoiceLoading(false);
      updateTrayState("idle");
    }
  }, [bridgeReady, updateTrayState, showNotification, vsetContinuous, handleVoiceResult]);

  // 空格键 = PTT（按住说话）：按住空格开始采集，松开停止处理
  // 排除输入框/文本域聚焦时（避免打字时空格误触发语音）
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.repeat) return; // 长按不重复触发
      e.preventDefault();
      void handlePttStart();
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      e.preventDefault();
      void handlePttStop();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [handlePttStart, handlePttStop]);

  // ---- Task screen ----
  const loadTasks = useCallback(async () => {
    setTasksLoading(true);
    try {
      if (!bridgeReady) {
        setTasks(DEMO_TASKS);
        if (DEMO_TASKS.length > 0) setActiveTaskId(DEMO_TASKS[0].id);
        return;
      }
      const list = await listTasks();
      setTasks(list);
      if (list.length > 0 && !activeTaskId) setActiveTaskId(list[0].id);
    } catch { setTasks(DEMO_TASKS); }
    finally { setTasksLoading(false); }
  }, [bridgeReady, activeTaskId]);

  const handleCreateTask = useCallback(async () => {
    const desc = taskDescInput.trim();
    if (!desc) return;
    if (!bridgeReady) { showNotification("演示模式", "核心未连接，无法创建真实任务", "warning"); return; }
    try {
      const result = await createTask(desc);
      if (result.ok) {
        showNotification("任务已创建", `任务 ID: ${result.task_id}`, "success");
        setTaskDescInput("");
        await loadTasks();
      }
    } catch (e) { showNotification("创建失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [taskDescInput, bridgeReady, loadTasks, showNotification]);

  const handleExecuteTask = useCallback(async (taskId: string) => {
    if (!bridgeReady) { showNotification("演示模式", "核心未连接，无法执行任务", "warning"); return; }
    setTaskExecuting(taskId);
    try {
      const result = await executeTask(taskId);
      if (result.ok) {
        showNotification("步骤已执行", `进度: ${result.task.current_step}/${result.task.steps.length}`, "success");
        await loadTasks();
      }
    } catch (e) { showNotification("执行失败", e instanceof Error ? e.message : String(e), "danger"); }
    finally { setTaskExecuting(null); }
  }, [bridgeReady, loadTasks, showNotification]);

  // ---- Scheduler screen ----
  const loadSchedules = useCallback(async () => {
    setSchedLoading(true);
    try {
      if (!bridgeReady) { setSchedules(DEMO_SCHEDULES); return; }
      const list = await listSchedules();
      setSchedules(list);
    } catch { setSchedules(DEMO_SCHEDULES); }
    finally { setSchedLoading(false); }
  }, [bridgeReady]);

  const handleCreateSchedule = useCallback(async () => {
    const name = schedNameInput.trim();
    const cron = schedCronInput.trim();
    const handler = schedHandlerInput.trim();
    if (!name || !cron || !handler) {
      showNotification("参数不完整", "请填写任务名称、Cron 表达式和执行指令", "warning");
      return;
    }
    if (!bridgeReady) { showNotification("演示模式", "核心未连接，无法创建定时任务", "warning"); return; }
    try {
      const result = await createSchedule(name, cron, handler);
      if (result.ok) {
        showNotification("定时任务已创建", `${name} · ${cron}`, "success");
        setShowAddSched(false); setSchedNameInput(""); setSchedCronInput("0 21 * * *"); setSchedHandlerInput("");
        await loadSchedules();
      } else { showNotification("创建失败", result.error || "未知错误", "danger"); }
    } catch (e) { showNotification("创建失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [schedNameInput, schedCronInput, schedHandlerInput, bridgeReady, loadSchedules, showNotification]);

  // ---- Vibe Coding ----
  const handleRunVibe = useCallback(async () => {
    const req = vibeRequest.trim();
    if (!req) return;
    setVibeLoading(true);
    updateTrayState("working");
    try {
      if (!bridgeReady) {
        await new Promise(r => setTimeout(r, 1200));
        setVibeResult({
          ok: true,
          steps: { note_understand: "理解需求：" + req, note_plan: "规划：生成项目周会 PPT", note_generate: "生成代码...", note_build: "构建完成", note_preview: "预览就绪" },
          files: { "output.html": "<h1>Q3 项目进度汇报</h1>", "outline.json": JSON.stringify({ title: "Q3 项目周会" }) },
          delivered_to: "preview", preview_url: "demo://preview", preview_ok: true, build_failed: false,
        });
        showNotification("演示模式", "Vibe Coding 以模拟模式运行", "warning");
        return;
      }
      const result = await runVibe(req, "demo");
      setVibeResult(result);
      if (result.error) showNotification("Vibe Coding 错误", result.error, "danger");
      else if (result.ok) showNotification("代码生成完成", result.preview_ok ? "预览已就绪" : "构建完成", "success");
    } catch (e) {
      setVibeResult({ ok: false, error: e instanceof Error ? e.message : String(e) });
      showNotification("Vibe Coding 失败", e instanceof Error ? e.message : String(e), "danger");
    } finally { setVibeLoading(false); updateTrayState("idle"); }
  }, [vibeRequest, bridgeReady, updateTrayState, showNotification]);

  // ---- Boot/Self-check ----
  const runBoot = useCallback(async (deep = false) => {
    setBootLoading(true);
    updateTrayState("booting");
    try {
      if (!bridgeReady) { await new Promise(r => setTimeout(r, 1500)); setBootResult(DEMO_BOOT); return; }
      // fast 模式（默认）：仅依赖探测，秒级完成；deep 模式做真实模型加载验证
      const result = await runBootCheck(!deep);
      setBootResult(result);
      showNotification("系统自检完成", result.summary, result.passed === result.total ? "success" : "warning");
    } catch (e) {
      setBootResult(DEMO_BOOT);
      showNotification("自检异常", e instanceof Error ? e.message : String(e), "danger");
    } finally { setBootLoading(false); updateTrayState("idle"); }
  }, [bridgeReady, updateTrayState, showNotification]);

  // 启动就绪后自动执行系统自检（首次进入 boot 页）
  const bootAutoRanRef = useRef(false);
  useEffect(() => {
    if (!bridgeReady || bootAutoRanRef.current) return;
    bootAutoRanRef.current = true;
    setNav("boot"); // 确保停留在自检页
    void runBoot();
  }, [bridgeReady, runBoot]);

  // 自检完成且全部通过 → 自动进入主界面；未全通过则停留展示结果（用户可手动进入）
  useEffect(() => {
    if (!bootLoading && bootResult && nav === "boot") {
      if (bootResult.passed === bootResult.total && bootResult.total > 0) {
        const t = setTimeout(() => setNav("chat"), 1200); // 展示 1.2s 后进入
        return () => clearTimeout(t);
      }
      // 有失败项：停留，用户查看后点"进入主界面"或"重新自检"
    }
  }, [bootLoading, bootResult, nav]);

  // ---- Voice settings ----
  const loadVoiceSettings = useCallback(async () => {
    setVsetLoading(true);
    try {
      if (!bridgeReady) {
        setVoiceSettings(DEMO_VOICE_SETTINGS);
        setVsetWakeWord(DEMO_VOICE_SETTINGS.wake_words[0] || "艾薇");
        setVsetAsrEngine(DEMO_VOICE_SETTINGS.asr_backend);
        setVsetLanguage(DEMO_VOICE_SETTINGS.language);
        setVsetTtsProvider(DEMO_VOICE_SETTINGS.tts_backend || "doubao-tts");
        setVsetTtsVoice(DEMO_VOICE_SETTINGS.tts_voice || "zh_female_xiaohe_uranus_bigtts");
        setVsetTtsSpeed(DEMO_VOICE_SETTINGS.tts_speed || 1.0);
        setVsetTtsResourceId(DEMO_VOICE_SETTINGS.tts_resource_id || "");
        return;
      }
      const st = await getVoiceSettings();
      setVoiceSettings(st);
      if (st.wake_words && st.wake_words.length > 0) setVsetWakeWord(st.wake_words[0]);
      setVsetAsrEngine(st.asr_backend);
      setVsetLanguage(st.language);
      if (st.tts_backend && TTS_VOICES[st.tts_backend]) setVsetTtsProvider(st.tts_backend);
      else if (st.tts_backend) setVsetTtsProvider("auto");
      if (st.tts_voice) setVsetTtsVoice(st.tts_voice);
      if (st.tts_speed) setVsetTtsSpeed(st.tts_speed);
      if (st.tts_resource_id) setVsetTtsResourceId(st.tts_resource_id);
    } catch { setVoiceSettings(DEMO_VOICE_SETTINGS); }
    finally { setVsetLoading(false); }
  }, [bridgeReady]);

  const handleSaveWakeWord = useCallback(async () => {
    if (!bridgeReady) { showNotification("演示模式", "设置以本地模拟保存", "warning"); return; }
    try {
      await saveVoiceSettings("voice.wake_words", [vsetWakeWord]);
      showNotification("唤醒词已更新", `新唤醒词: ${vsetWakeWord}`, "success");
    } catch (e) { showNotification("保存失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [vsetWakeWord, bridgeReady, showNotification]);

  const handleSaveAsrEngine = useCallback(async () => {
    if (!bridgeReady) return;
    try {
      await saveVoiceSettings("asr.backend", vsetAsrEngine);
      showNotification("ASR 引擎已更新", vsetAsrEngine, "success");
    } catch (e) { showNotification("保存失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [vsetAsrEngine, bridgeReady, showNotification]);

  const handleSaveLanguage = useCallback(async () => {
    if (!bridgeReady) return;
    try {
      await saveVoiceSettings("asr.language", vsetLanguage);
      showNotification("语言设置已更新", vsetLanguage, "success");
    } catch (e) { showNotification("保存失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [vsetLanguage, bridgeReady, showNotification]);

  const handleTestVoice = useCallback(async () => {
    setVsetTesting(true);
    setVsetTestResult("");
    try {
      const defaultText = "你好，这是一段语音测试。当前语速设置为 " + vsetTtsSpeed.toFixed(1) + " 倍速。";
      const result = await testTts(
        defaultText,
        vsetTtsProvider,
        vsetTtsVoice,
        vsetTtsSpeed,
        vsetTtsApiKey,
        vsetTtsResourceId,
      );
      if (!result.ok || !result.wav_b64) {
        throw new Error(result.error || "合成失败，未返回音频数据");
      }
      // Mock 降级警告（云端调用失败导致 fallback 到 mock 提示音）
      if (result.warning) {
        setVsetTestResult("⚠ " + result.warning);
        showNotification("试听警告", result.warning, "warning");
        return;
      }
      // 使用 Web Audio API 播放（比 <audio> 更可靠）
      const binary = atob(result.wav_b64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      const audioBuffer = await audioCtx.decodeAudioData(bytes.buffer);
      const source = audioCtx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioCtx.destination);
      source.start(0);
      const duration = result.wav_len ? (result.wav_len / (result.sample_rate || 24000) / 2) : 0;
      const info = `${result.backend || "unknown"} · ${vsetTtsVoice} · ${vsetTtsSpeed.toFixed(1)}x · ${Math.round(duration * 1000)}ms`;
      setVsetTestResult(`试听音频已播放（${info}）`);
      showNotification("试听完成", `语音合成测试通过 · ${result.backend}`, "success");
      source.onended = () => { try { audioCtx.close(); } catch {} };
    } catch (e) {
      setVsetTestResult("试听失败：" + (e instanceof Error ? e.message : String(e)));
      showNotification("试听失败", String(e), "danger");
    } finally {
      setVsetTesting(false);
    }
  }, [vsetTtsProvider, vsetTtsVoice, vsetTtsSpeed, vsetTtsApiKey, vsetTtsResourceId, showNotification]);

  const handleSaveTts = useCallback(async () => {
    try {
      showNotification("保存中...", "正在应用 TTS 配置", "success");
      const result = await applyVoiceTts(
        vsetTtsProvider,
        vsetTtsVoice,
        vsetTtsSpeed,
        vsetTtsApiKey,
        vsetTtsResourceId,
      );
      if (result.ok) {
        showNotification("保存成功", `TTS 已切换到 ${result.backend} · ${vsetTtsVoice} · ${vsetTtsSpeed.toFixed(1)}x`, "success");
      } else {
        showNotification("保存失败", result.error || "未知错误", "danger");
      }
    } catch (e) {
      showNotification("保存失败", String(e), "danger");
    }
  }, [vsetTtsProvider, vsetTtsVoice, vsetTtsSpeed, vsetTtsApiKey, vsetTtsResourceId, showNotification]);

  const handleRefreshDevices = useCallback(() => {
    setVsetMicDevice("default");
    setVsetOutputDevice("auto");
    showNotification("设备刷新", "已重新扫描音频设备", "success");
  }, [showNotification]);

  const handleUnlockRobot = useCallback(() => {
    if (vsetRobotPwd.length < 4) {
      showNotification("解锁失败", "密码至少 4 位", "warning");
      return;
    }
    setVsetRobotUnlocked(true);
    showNotification("已解锁", "机器人音效功能已解锁", "success");
  }, [vsetRobotPwd, showNotification]);

  // ---- Model management ----
  const loadModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      if (!bridgeReady) {
        setModels(DEMO_MODELS);
        // bridge 未就绪，使用 localStorage 缓存回退
        setCatalog(LOCAL_PROVIDERS);
        const cachedKeys = apiKeyStorage.load();
        setApiKeys(Object.keys(cachedKeys).length > 0 ? cachedKeys : {});
        return;
      }
      const list = await listModels();
      setModels(list);
      const active = list.find((m: any) => m.active);
      setActiveModelName(active ? active.model : null);
      // Phase 2: 加载健康仪表盘
      try {
        const health = await getModelsHealth();
        setModelHealth(health.backends || []);
      } catch {}
      // Phase 2: 加载成本数据
      try {
        const cost = await getModelsCost(undefined, true);
        setModelCost(cost);
      } catch {}
      // 加载提供商目录（失败时使用本地回退）
      try {
        const cat = await getModelCatalog();
        setCatalog(cat.providers?.length ? cat.providers : LOCAL_PROVIDERS);
      } catch {
        setCatalog(LOCAL_PROVIDERS);
      }
      // 加载 API Key 列表
      try {
        const keys = await listApiKeys();
        setApiKeys(keys.api_keys || {});
        // 同步到 localStorage 缓存
        apiKeyStorage.save(keys.api_keys || {});
      } catch {
        // 使用本地缓存回退
        const cachedKeys = apiKeyStorage.load();
        setApiKeys(Object.keys(cachedKeys).length > 0 ? cachedKeys : {});
      }
    } catch { setModels(DEMO_MODELS); }
    finally { setModelsLoading(false); }
  }, [bridgeReady]);

  // 启动就绪后自动加载模型列表（主界面右下角模型下拉框需要）
  useEffect(() => {
    if (bridgeReady) void loadModels();
  }, [bridgeReady, loadModels]);

  // 一键测试所有已配置的云端提供商连通性
  const handleTestCloud = useCallback(async () => {
    if (!bridgeReady) {
      showNotification("演示模式", "连接核心后可测试云端模型", "warning");
      return;
    }
    setCloudTesting(true);
    setCloudTestSummary(null);
    try {
      const res = await testCloudModels();
      setCloudTestSummary(res);
      showNotification(
        "云端测试完成",
        res.ok ? `${res.passed}/${res.total} 个云端可用，${res.failed} 个失败` : res.error || "测试失败",
        res.ok && res.failed === 0 ? "success" : "warning"
      );
    } catch (e) {
      showNotification("云端测试失败", e instanceof Error ? e.message : String(e), "danger");
    } finally {
      setCloudTesting(false);
    }
  }, [bridgeReady, showNotification]);

  /* ================================================================
   *  Skills（技能管理）
   * ================================================================ */
  const loadSkills = useCallback(async () => {
    setSkillsLoading(true);
    try {
      if (!bridgeReady) { setSkills([]); return; }
      const res = await listSkills();
      if (res.ok && res.skills) setSkills(res.skills);
    } catch { /* 静默 */ }
    finally { setSkillsLoading(false); }
  }, [bridgeReady]);

  const toggleSkill = useCallback(async (id: string, enabled: boolean) => {
    if (!bridgeReady) { showNotification("演示模式", "连接核心后可启停技能", "warning"); return; }
    const res = await setSkillEnabled(id, enabled);
    if (res.ok && res.skill) {
      setSkills(prev => prev.map(s => s.id === id ? res.skill! : s));
      showNotification("技能已更新", `${res.skill!.name} ${enabled ? "已启用" : "已停用"}`, "success");
    } else {
      showNotification("更新失败", res.error || "未知错误", "danger");
    }
  }, [bridgeReady, showNotification]);

  const saveSkill = useCallback(async () => {
    const name = skillForm.name.trim();
    if (!name) { showNotification("缺少名称", "请填写技能名称", "warning"); return; }
    const keywords = skillForm.keywords.split(/[,，、\s]+/).filter(Boolean);
    const fields = {
      name,
      description: skillForm.description.trim(),
      category: skillForm.category.trim() || "自定义",
      keywords,
      system_prompt: skillForm.system_prompt,
      enabled: skillForm.enabled,
    };
    try {
      const res = skillForm.id
        ? await updateSkill(skillForm.id, fields)
        : await createSkill(fields);
      if (res.ok) {
        showNotification("保存成功", `技能「${name}」已保存`, "success");
        setSkillFormOpen(false);
        setSkillForm({ id: null, name: "", description: "", category: "自定义", keywords: "", system_prompt: "", enabled: true });
        void loadSkills();
      } else {
        showNotification("保存失败", res.error || "未知错误", "danger");
      }
    } catch (e) {
      showNotification("保存失败", e instanceof Error ? e.message : String(e), "danger");
    }
  }, [skillForm, loadSkills, showNotification]);

  const removeSkill = useCallback(async (id: string, name: string) => {
    if (!bridgeReady) { showNotification("演示模式", "连接核心后可删除技能", "warning"); return; }
    const res = await deleteSkill(id);
    if (res.ok) {
      setSkills(prev => prev.filter(s => s.id !== id));
      showNotification("已删除", `技能「${name}」已删除`, "success");
    } else {
      showNotification("删除失败", res.error || "未知错误", "danger");
    }
  }, [bridgeReady, showNotification]);

  /* ================================================================
   *  Tools（MCP 工具管理）
   * ================================================================ */
  const loadTools = useCallback(async () => {
    setToolsLoading(true);
    try {
      if (!bridgeReady) { setManagedTools([]); return; }
      const res = await listTools();
      if (res.ok && res.tools) setManagedTools(res.tools);
    } catch { /* 静默 */ }
    finally { setToolsLoading(false); }
  }, [bridgeReady]);

  const toggleTool = useCallback(async (name: string, enabled: boolean) => {
    if (!bridgeReady) { showNotification("演示模式", "连接核心后可启停工具", "warning"); return; }
    const res = await setToolEnabled(name, enabled);
    if (res.ok) {
      setManagedTools(prev => prev.map(t => t.name === name ? { ...t, enabled } : t));
      showNotification("工具已更新", `${name} ${enabled ? "已启用" : "已停用"}`, "success");
    } else {
      showNotification("更新失败", res.error || "未知错误", "danger");
    }
  }, [bridgeReady, showNotification]);

  const resetAddModelDialog = useCallback(() => {
    setAddModelProvider("");
    setAddModelName("");
    setAddModelApiKey("");
    setAddModelBaseUrl("");
    setAddModelApiType("chat_completions");
    setAddModelThinking(false);
    setAddModelInputText(true);
    setAddModelInputImage(false);
    setAddModelInputAudio(false);
    setAddModelInputVideo(false);
    setAddModelContextWindow(32768);
    setAddModelMaxOutput(4096);
    setAddModelTestResult(null);
    setAddModelPresetModels(null);
  }, []);

  const handleProviderChange = useCallback((providerId: string) => {
    setAddModelProvider(providerId);
    setAddModelName("");
    setAddModelTestResult(null);
    setAddModelPresetModels(null);
    const provider = catalog.find(p => p.id === providerId);
    if (provider) {
      setAddModelBaseUrl(provider.base_url || "");
      if (!addModelApiKey) {
        setAddModelApiKey("");
      }
      if (provider.default_model) {
        setAddModelName(provider.default_model);
      }
      if (provider.models && provider.models.length > 0) {
        setAddModelContextWindow(provider.models[0].context_window || 32768);
      }
      setAddModelApiType(
        provider.category === "local" ? "chat_completions" :
        provider.id === "doubao" ? "responses_api" : "chat_completions"
      );
    } else {
      setAddModelBaseUrl("");
    }
  }, [catalog, addModelApiKey]);

  const handleTestConnection = useCallback(async () => {
    if (!addModelProvider || !addModelApiKey || !addModelBaseUrl) return;
    setAddModelTesting(true);
    setAddModelTestResult(null);
    try {
      const result = await testModelConnection(addModelProvider, addModelApiKey, addModelBaseUrl);
      setAddModelTestResult(result);
      if (result.ok) {
        try {
          setAddModelFetchingModels(true);
          const preset = await listProviderModels(addModelProvider);
          setAddModelPresetModels(preset);
        } finally {
          setAddModelFetchingModels(false);
        }
      }
    } catch (e) {
      setAddModelTestResult({ ok: false, error: String(e) });
    } finally {
      setAddModelTesting(false);
    }
  }, [addModelProvider, addModelApiKey, addModelBaseUrl]);

  // ---- Memory ----
  const loadMemory = useCallback(async () => {
    setMemoryLoading(true);
    try {
      if (!bridgeReady) { setMemories(DEMO_MEMORIES); return; }
      const list = await listMemory();
      setMemories(list);
    } catch { setMemories(DEMO_MEMORIES); }
    finally { setMemoryLoading(false); }
  }, [bridgeReady]);

  const handleSearchMemory = useCallback(async () => {
    const q = memorySearchQuery.trim();
    if (!q) { await loadMemory(); return; }
    setMemoryLoading(true);
    try {
      if (!bridgeReady) {
        await new Promise(r => setTimeout(r, 400));
        const filtered = DEMO_MEMORIES.filter(m => m.text.includes(q));
        setMemories(filtered.length > 0 ? filtered : DEMO_MEMORIES);
        showNotification("演示模式", `找到 ${filtered.length} 条匹配记忆`, "warning");
        return;
      }
      const results = await searchMemory(q, 10);
      setMemories(results);
      showNotification("搜索完成", `找到 ${results.length} 条匹配记忆`, "success");
    } catch (e) { showNotification("搜索失败", e instanceof Error ? e.message : String(e), "danger"); }
    finally { setMemoryLoading(false); }
  }, [memorySearchQuery, bridgeReady, loadMemory, showNotification]);

  const handleAddMemory = useCallback(async () => {
    const text = memoryNewText.trim();
    if (!text) return;
    if (!bridgeReady) {
      const newEntry: MemoryEntry = { id: `mem_demo_${Date.now()}`, text, created_at: new Date().toISOString(), category: "新记忆" };
      setMemories(prev => [newEntry, ...prev]);
      setMemoryNewText("");
      showNotification("演示模式", "记忆已在本地添加", "warning");
      return;
    }
    try {
      const result = await addMemory(text);
      showNotification("记忆已添加", `ID: ${result.id}`, "success");
      setMemoryNewText("");
      await loadMemory();
    } catch (e) { showNotification("添加失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [memoryNewText, bridgeReady, loadMemory, showNotification]);

  /* ================================================================
   *  Knowledge Cards handlers
   * ================================================================ */
  const loadKnowledge = useCallback(async () => {
    setKLoading(true);
    try {
      if (!bridgeReady) { setKCards([]); return; }
      const params: Record<string, unknown> = { sort: kSort };
      if (kCategory) params.category = kCategory;
      if (kTag) params.tag = kTag;
      if (kFavOnly) params.favorite_only = true;
      const cards = await listKnowledge(params as any);
      setKCards(cards);
      const stats = await getKnowledgeStats();
      setKStats(stats);
    } catch { setKCards([]); }
    finally { setKLoading(false); }
  }, [bridgeReady, kSort, kCategory, kTag, kFavOnly]);

  const handleKSearch = useCallback(async () => {
    const q = kSearch.trim();
    setKLoading(true);
    try {
      if (!bridgeReady) { setKCards([]); return; }
      if (!q) { await loadKnowledge(); return; }
      const cards = await searchKnowledge(q, 30);
      setKCards(cards);
    } catch (e) { showNotification("搜索失败", e instanceof Error ? e.message : String(e), "danger"); }
    finally { setKLoading(false); }
  }, [kSearch, bridgeReady, loadKnowledge, showNotification]);

  const handleKCreate = useCallback(async () => {
    const title = kEditForm.title.trim();
    if (!title) { showNotification("提示", "请输入卡片标题", "warning"); return; }
    try {
      if (!bridgeReady) { showNotification("演示模式", "连接核心后创建", "warning"); return; }
      await createKnowledge({
        title, summary: kEditForm.summary.trim(), content: kEditForm.content.trim(),
        category: kEditForm.category || "其他",
        tags: kEditForm.tags.split(/[,，\s]+/).filter(Boolean),
      } as any);
      setKShowNew(false);
      setKEditForm({ title: "", summary: "", content: "", category: "其他", tags: "" });
      showNotification("知识卡片已创建", title, "success");
      await loadKnowledge();
    } catch (e) { showNotification("创建失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [kEditForm, bridgeReady, loadKnowledge, showNotification]);

  const handleKUpdate = useCallback(async (id: string) => {
    try {
      if (!bridgeReady) return;
      await updateKnowledge(id, {
        title: kEditForm.title, summary: kEditForm.summary, content: kEditForm.content,
        category: kEditForm.category, tags: kEditForm.tags.split(/[,，\s]+/).filter(Boolean),
      } as any);
      setKEditId(null);
      showNotification("卡片已更新", kEditForm.title, "success");
      await loadKnowledge();
    } catch (e) { showNotification("更新失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [kEditForm, bridgeReady, loadKnowledge, showNotification]);

  const handleKDelete = useCallback(async (id: string, title: string) => {
    try {
      if (!bridgeReady) return;
      await deleteKnowledge(id);
      showNotification("卡片已删除", title, "success");
      await loadKnowledge();
    } catch (e) { showNotification("删除失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [bridgeReady, loadKnowledge, showNotification]);

  const handleKFav = useCallback(async (id: string) => {
    try {
      if (!bridgeReady) return;
      await toggleKnowledgeFavorite(id);
      await loadKnowledge();
    } catch (e) { showNotification("操作失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [bridgeReady, loadKnowledge, showNotification]);

  const handleKExpand = useCallback(async (card: KnowledgeCardType) => {
    setKExpanded(prev => ({ ...prev, [card.id]: !prev[card.id] }));
    // 展开时加载关联卡片
    if (!kRelated[card.id] && card.links.length > 0 && bridgeReady) {
      try {
        const related: KnowledgeCardType[] = [];
        for (const lid of card.links.slice(0, 5)) {
          const c = await getKnowledge(lid);
          if (c && !("error" in c)) related.push(c);
        }
        setKRelated(prev => ({ ...prev, [card.id]: related }));
      } catch { /* ignore */ }
    }
  }, [kRelated, bridgeReady]);

  const handleKEdit = useCallback((card: KnowledgeCardType) => {
    setKEditId(card.id);
    setKEditForm({
      title: card.title, summary: card.summary || "", content: card.content || "",
      category: card.category, tags: card.tags.join(", "),
    });
  }, []);

  const handleKBackup = useCallback(async () => {
    try {
      if (!bridgeReady) { showNotification("演示模式", "连接核心后备份", "warning"); return; }
      const r = await backupKnowledge();
      showNotification("备份完成", r.path, "success");
    } catch (e) { showNotification("备份失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [bridgeReady, showNotification]);

  // 知识图谱
  const handleKGraph = useCallback(async () => {
    try {
      if (!bridgeReady) { showNotification("演示模式", "连接核心后查看图谱", "warning"); return; }
      const g = await getKnowledgeGraph();
      setKGraph(g);
      setKShowGraph(true);
    } catch (e) { showNotification("图谱加载失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [bridgeReady, showNotification]);

  // 手动建立关联
  const handleKLink = useCallback(async (cardId: string, targetId: string) => {
    if (!targetId || targetId === cardId) { showNotification("提示", "请选择要关联的卡片", "warning"); return; }
    try {
      if (!bridgeReady) return;
      await linkKnowledge(cardId, targetId);
      setKLinkTarget("");
      showNotification("已建立关联", "卡片已互相关联", "success");
      await loadKnowledge();
      // 刷新当前展开卡片的关联列表
      const card = kCards.find(c => c.id === cardId);
      if (card) await handleKExpand(card);
    } catch (e) { showNotification("关联失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [bridgeReady, loadKnowledge, kCards, handleKExpand, showNotification]);

  // 导出/分享
  const handleKExport = useCallback(async (card: KnowledgeCardType, fmt: "markdown" | "json") => {
    try {
      if (!bridgeReady) { showNotification("演示模式", "连接核心后导出", "warning"); return; }
      const r = await exportKnowledge(card.id, fmt);
      setKExportText(r.text);
    } catch (e) { showNotification("导出失败", e instanceof Error ? e.message : String(e), "danger"); }
  }, [bridgeReady, showNotification]);

  const handleKCopy = useCallback((text: string) => {
    try {
      navigator.clipboard?.writeText(text);
      showNotification("已复制", "分享文本已复制到剪贴板", "success");
    } catch {
      showNotification("复制失败", "请手动选择文本复制", "warning");
    }
  }, [showNotification]);

  /* ================================================================
   *  Screen navigation → trigger data loading
   * ================================================================ */
  useEffect(() => {
    switch (nav) {
      case "voice": loadVoiceStatus(); break;
      case "task": loadTasks(); break;
      case "sched": loadSchedules(); break;
      case "boot": runBoot(); break;
      case "voiceset": loadVoiceSettings(); break;
      case "models": loadModels(); break;
      case "memory": loadMemory(); loadKnowledge(); break;
      case "skills": loadSkills(); break;
      case "tools": loadTools(); break;
      default: break;
    }
  }, [nav, loadVoiceStatus, loadTasks, loadSchedules, runBoot, loadVoiceSettings, loadModels, loadMemory, loadKnowledge, loadSkills, loadTools]);

  useEffect(() => {
    if (nav !== "voice" || bridgeReady) return;
    const timer = setInterval(() => { setDemoVoiceIdx(prev => (prev + 1) % DEMO_VOICE_TEXTS.length); }, 4000);
    return () => clearInterval(timer);
  }, [nav, bridgeReady]);

  const handleNav = (id: NavId) => {
    // 自检进行中：仅允许停留自检页或查看结果后手动进入（跳过其它导航）
    if (bootLoading && id !== "boot") {
      showNotification("系统自检中", "请等待自检完成", "warning");
      return;
    }
    // 离开语音页时打断播报
    if (id !== "voice") stopVoicePlayback();
    setNav(id);
  };

  const currentTitle: Record<NavId, string> = {
    chat: "对话", voice: "语音模式", task: "自主任务", sched: "定时任务",
    vibe: "Vibe Coding", memory: "知识卡片", boot: "系统自检",
    voiceset: "语音设置", models: "模型管理", settings: "设置",
    skills: "技能管理", tools: "工具管理",
  };

  /* ================================================================
   *  Render helpers
   * ================================================================ */
  const voiceAsrText = voiceTurnResult?.text || DEMO_VOICE_TEXTS[demoVoiceIdx];
  const voiceReplyText = voiceTurnResult?.reply || (bridgeReady ? "点击下方按钮开始语音对话..." : "好的，我正在帮您处理。完成后会通知您~");
  const voiceIsFallback = voiceTurnResult?.fallback || voiceStatus?.fallback || false;
  const activeTask = tasks.find(t => t.id === activeTaskId) || null;
  const activeSched = schedules[activeSchedIdx] || null;
  const bootProgressVal = bootResult?.progress || 0;

  const voiceOptions = [
    { name: "温柔女声", desc: "晓晓 · 自然亲切" },
    { name: "活力女声", desc: "晓涵 · 清脆明亮" },
    { name: "沉稳男声", desc: "云扬 · 低沉磁性" },
    { name: "少年音", desc: "晓辰 · 阳光活力" },
  ];

  const featureCards = [
    { id: "voice" as NavId, label: "语音模式", desc: "语音对话、唤醒词配置", icon: "🎙️" },
    { id: "task" as NavId, label: "自主任务", desc: "AI 自动执行复杂任务", icon: "⚡" },
    { id: "sched" as NavId, label: "定时任务", desc: "周期定时与触发器配置", icon: "⏰" },
    { id: "vibe" as NavId, label: "Vibe Coding", desc: "AI 辅助代码生成与预览", icon: "💻" },
    { id: "memory" as NavId, label: "知识卡片", desc: "知识自动沉淀、管理与调用", icon: "🧠" },
    { id: "boot" as NavId, label: "系统自检", desc: "启动时自动检测各模块状态", icon: "🔒" },
    { id: "voiceset" as NavId, label: "语音设置", desc: "TTS 音色选择与 ASR 引擎", icon: "🎛️" },
    { id: "models" as NavId, label: "模型管理", desc: "模型部署、路由与切换策略", icon: "🧩" },
    { id: "skills" as NavId, label: "技能管理", desc: "配置艾薇的专属技能与提示词", icon: "🎯" },
    { id: "tools" as NavId, label: "工具管理", desc: "MCP 工具开关与权限查看", icon: "🔧" },
  ];

  /* ================================================================
   *  Main render
   * ================================================================ */
  return (
    <>
      <audio ref={audioRef} style={{ position: "absolute", left: "-9999px", top: "-9999px", width: 1, height: 1, opacity: 0 }} preload="auto" />
      <div className="bg-layer">
        <div className="bg-blob b1" />
        <div className="bg-blob b2" />
        <div className="bg-blob b3" />
      </div>

      <div className="window">
        <div className="titlebar">
          <div className="titlebar-left">
            {nav !== "chat" && nav !== "settings" && (
              <div className="titlebar-btn" onClick={() => setNav("settings")} title="返回设置">
                <svg viewBox="0 0 24 24"><polyline points="15 6 9 12 15 18" /></svg>
              </div>
            )}
            {nav === "settings" && (
              <div className="titlebar-btn" onClick={() => setNav("chat")} title="返回对话">
                <svg viewBox="0 0 24 24"><polyline points="15 6 9 12 15 18" /></svg>
              </div>
            )}
            <div className="titlebar-logo" onClick={() => setNav("chat")}>A</div>
            <div className="titlebar-title">{currentTitle[nav]}</div>
          </div>
          <div className="titlebar-right">
            <div className="titlebar-status">
              <div className="status-dot" style={{ background: trayState === "error" ? "var(--danger)" : trayState === "working" ? "var(--warning)" : "var(--success)" }} />
              <span>
                {TRAY_LABEL[trayState]} · {status ? `后端 ${status.backend}` : "检测中..."}
                {!bridgeReady && <span style={{ color: "var(--warning)", marginLeft: 6 }}>· 演示模式</span>}
              </span>
            </div>
            <div className="theme-switcher" title="切换主题">
              {THEMES.map(t => (
                <button
                  key={t.id}
                  className={`theme-switcher-btn ${currentTheme === t.id ? "active" : ""}`}
                  style={{ background: t.colors[1] }}
                  onClick={() => applyTheme(t.id)}
                  title={`${t.name} — ${t.desc}`}
                />
              ))}
            </div>
            <div className={`titlebar-btn settings-btn ${nav === "settings" ? "active" : ""}`} onClick={() => setNav(nav === "settings" ? "chat" : "settings")} title="设置">
              <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></svg>
            </div>
          </div>
        </div>

        <div className="main">
          <div className="content">

            {/* ============ 1. 对话 (chat) ============ */}
            <div className={`screen ${nav === "chat" ? "active" : ""}`}>
              <div className="chat-layout">
                <div className="chat-messages">
                  {/* 对话中自动调用的知识卡片 */}
                  {kKnowledgeHits.length > 0 && (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                      <span style={{ fontSize: 11, color: "var(--muted2)", alignSelf: "center" }}>🧠 相关知识：</span>
                      {kKnowledgeHits.map((hit, idx) => (
                        <div key={idx} className="kcard" style={{ minWidth: 200, maxWidth: 260, padding: 10, cursor: "pointer" }}
                          onClick={() => handleNav("memory")} title="点击查看知识卡片">
                          <div className="kcard-title" style={{ fontSize: 13 }}>{hit.card.title}</div>
                          <div className="kcard-summary" style={{ fontSize: 11 }}>{hit.card.summary || hit.card.content?.slice(0, 40)}</div>
                          <div className="kcard-meta" style={{ fontSize: 9 }}>相似度 {(hit.score * 100).toFixed(0)}% · {hit.card.category}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  {messages.map((m, i) => (
                    <div key={i} className={`msg-row ${m.role === "user" ? "user" : ""}`}>
                      {m.role === "assistant" && <div className="msg-avatar">薇</div>}
                      <div className={`msg-bubble ${m.role}`}>
                        {m.image && (
                          <img
                            src={m.image}
                            alt="附件"
                            className="msg-image"
                            style={{ display: "block", maxWidth: 220, maxHeight: 160, borderRadius: 8, marginBottom: 6, objectFit: "cover" }}
                          />
                        )}
                        {m.text}
                      </div>
                    </div>
                  ))}
                  <div ref={chatEndRef} />
                </div>
                <div className="chat-input-area">
                  {pendingImage && (
                    <div className="chat-attach">
                      <img src={pendingImage.dataUrl} alt="待发送图片" className="chat-attach-img" />
                      <span className="chat-attach-name">{pendingImage.name}</span>
                      <button className="chat-attach-remove" onClick={() => setPendingImage(null)} title="移除图片">✕</button>
                    </div>
                  )}
                  <div className="chat-input-row">
                    <input
                      className="chat-input"
                      placeholder="输入消息、拖入图片让艾薇看图，或按 Alt+V 语音对话..."
                      value={input}
                      onChange={e => setInput(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter") handleSend(); }}
                    />
                    <div className="voice-model-stack">
                      <button className="btn-voice" onClick={() => handleNav("voice")} title="语音模式">🎙️</button>
                      <select
                        className="chat-model-select"
                        value={activeModelName ?? ""}
                        title="选择当前模型（热切换）"
                        onChange={async e => {
                          const picked = e.target.value;
                          if (!bridgeReady) {
                            showNotification("演示模式", "连接核心后可切换模型", "warning");
                            return;
                          }
                          try {
                            if (!picked) {
                              const result = await setActiveModel(null);
                              if (result.ok) {
                                setActiveModelName(null);
                                showNotification("已恢复", "自动路由模式已启用", "success");
                              } else {
                                showNotification("切换失败", result.message || "未知错误", "danger");
                              }
                            } else {
                              const result = await setActiveModel(picked);
                              if (result.ok) {
                                setActiveModelName(picked);
                                showNotification("模型已切换", `当前使用 ${picked}`, "success");
                              } else {
                                showNotification("切换失败", result.message || "未知错误", "danger");
                              }
                            }
                          } catch (err) {
                            showNotification("切换失败", err instanceof Error ? err.message : String(err), "danger");
                          }
                        }}
                      >
                        <option value="">🤖 自动路由</option>
                        {models.map((m, i) => (
                          <option key={`${m.model}-${i}`} value={m.model}>
                            {m.available ? "🟢" : "⚪"} {m.mode === "local" ? "本地" : "云端"} · {m.model}
                            {m.active ? "（当前）" : ""}
                          </option>
                        ))}
                      </select>
                    </div>
                    <button className="btn-send" onClick={handleSend}>➤</button>
                  </div>
                  <div className="chat-quick">
                    <div className="quick-chip" onClick={() => quickSend("帮我查一下明天的日程安排")}>📅 查日程</div>
                    <div className="quick-chip" onClick={() => quickSend("帮我处理一下邮件")}>📧 处理邮件</div>
                    <div className="quick-chip" onClick={() => quickSend("整理本周工作周报")}>📊 生成周报</div>
                    <div className="quick-chip" onClick={() => quickSend("设置每天晚上9点检查邮箱")}>⏰ 设定时任务</div>
                    <div className="quick-chip" onClick={() => showNotification("测试通知", "这是一条测试通知消息。", "success")}>🔔 测试通知</div>
                  </div>
                </div>
              </div>
            </div>

            {/* ============ 2. 语音 (voice) ============ */}
            <div className={`screen ${nav === "voice" ? "active" : ""}`}>
              <div className="voice-screen">
                {/* Voice orb with listening indicator */}
                <div className="voice-orb" style={{
                  boxShadow: voiceListening
                    ? "0 0 60px rgba(239,68,68,0.6), 0 0 120px rgba(239,68,68,0.3)"
                    : undefined,
                  transition: "box-shadow 0.3s ease",
                }}>
                  <div className="voice-rings">
                    <div className="voice-ring" style={voiceListening ? { borderColor: "rgba(239,68,68,0.6)" } : undefined} />
                    <div className="voice-ring" style={voiceListening ? { borderColor: "rgba(239,68,68,0.4)" } : undefined} />
                    <div className="voice-ring" style={voiceListening ? { borderColor: "rgba(239,68,68,0.2)" } : undefined} />
                  </div>
                  <div className="voice-orb-inner" style={{ fontSize: 48 }}>
                    {voiceListening ? "🔴" : (voiceLoading ? "⚙️" : "🎙️")}
                  </div>
                </div>
                <div className="voice-wave" style={{ opacity: voiceListening || voiceLoading ? 1 : 0.3 }}>
                  {Array.from({ length: 12 }, (_, i) => (
                    <div key={i} className="voice-bar" style={{
                      animationDelay: `${i * 0.08}s`,
                      animationPlayState: voiceListening ? "running" : (voiceLoading ? "running" : "paused"),
                    }} />
                  ))}
                </div>
                <div className="voice-text">
                  <div className="voice-asr">{voiceAsrText}</div>
                  <div className="voice-ai-reply">{voiceReplyText}</div>
                </div>
                {voiceStatus && (
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center", marginTop: 8 }}>
                    <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "rgba(59,130,246,0.12)", color: "var(--accent)" }}>ASR: {voiceStatus.asr}</span>
                    <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "rgba(16,185,129,0.12)", color: "var(--success)" }}>TTS: {voiceStatus.tts}</span>
                    <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "rgba(139,92,246,0.12)", color: "var(--accent3)" }}>VAD: {voiceStatus.vad}</span>
                    {voiceStatus.wake_words && voiceStatus.wake_words.length > 0 && (
                      <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "rgba(245,158,11,0.12)", color: "var(--warning)" }}>
                        唤醒词: {voiceStatus.wake_words.join(", ")}
                      </span>
                    )}
                    {voiceIsFallback && (
                      <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "rgba(239,68,68,0.12)", color: "var(--danger)" }}>降级模式</span>
                    )}
                    {wakeLoopActive && (
                      <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "rgba(34,197,94,0.15)", color: "#22c55e" }}>
                        🎙️ 后台监听中 ({wakeLoopCount})
                      </span>
                    )}
                  </div>
                )}

                {/* Microphone button - large circular PTT（按住说话） */}
                <div style={{ marginTop: 20, display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
                  {(!bridgeReady || voiceStatus?.asr_ready === false) ? (
                    <div style={{ padding: "24px 32px", borderRadius: 12, background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.3)", textAlign: "center" }}>
                      <div style={{ fontSize: 20, marginBottom: 6 }}>⏳</div>
                      <div style={{ fontSize: 14, color: "var(--warning)", fontWeight: 500 }}>核心加载中（模型预热中）</div>
                      <div style={{ fontSize: 11, color: "var(--muted2)", marginTop: 4 }}>
                        {!bridgeReady ? "正在连接 Python 核心..." : "正在加载语音识别模型（FunASR），首次约需 10-30 秒"}
                      </div>
                    </div>
                  ) : (
                    <>
                  <button
                    onMouseDown={(e) => { e.preventDefault(); if (!voiceLoading) void handlePttStart(); }}
                    onMouseUp={() => void handlePttStop()}
                    onMouseLeave={() => { if (pttActiveRef.current) void handlePttStop(); }}
                    onTouchStart={(e) => { e.preventDefault(); if (!voiceLoading) void handlePttStart(); }}
                    onTouchEnd={() => void handlePttStop()}
                    disabled={voiceLoading}
                    title="按住说话（按住空格或按住本按钮，松开结束）"
                    style={{
                      width: 80, height: 80,
                      borderRadius: "50%",
                      border: "none",
                      cursor: voiceLoading ? "not-allowed" : "pointer",
                      background: voiceListening
                        ? "linear-gradient(135deg, #ef4444, #dc2626)"
                        : (voiceLoading
                          ? "linear-gradient(135deg, #6b7280, #4b5563)"
                          : "linear-gradient(135deg, #6c8cff, #4f6ef7)"),
                      color: "#fff",
                      fontSize: 28,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      boxShadow: voiceListening
                        ? "0 0 30px rgba(239,68,68,0.5), 0 0 60px rgba(239,68,68,0.25)"
                        : "0 4px 20px rgba(79,110,247,0.4), 0 2px 6px rgba(0,0,0,0.3)",
                      transition: "all 0.2s ease",
                      transform: voiceListening ? "scale(1.05)" : "scale(1)",
                      animation: voiceListening ? "pulse-red 1s infinite" : undefined,
                    }}
                  >
                    {voiceListening ? "⏺" : (voiceLoading ? "⏳" : "🎙️")}
                  </button>
                  <div style={{ fontSize: 12, color: "var(--muted2)" }}>
                    {voiceListening ? "正在聆听...松开结束" : (voiceLoading ? "处理中..." : "按住空格或按住按钮说话")}
                  </div>
                    </>
                  )}
                </div>

                {voiceTurnResult && !voiceLoading && (
                  <div style={{ marginTop: 12, padding: "10px 16px", borderRadius: 8, background: "rgba(0,0,0,0.2)", fontSize: 12, color: "var(--muted2)" }}>
                    <div>模型: {voiceTurnResult.model || "N/A"} · 耗时: {Math.round(voiceTurnResult.latency_ms || 0)}ms</div>
                    {voiceTurnResult.asr_backend && <div>ASR: {voiceTurnResult.asr_backend} · TTS: {voiceTurnResult.tts_backend}</div>}
                    {voiceTurnResult.breakdown_ms && (
                      <div style={{ marginTop: 4, fontSize: 11, opacity: 0.85 }}>
                        细分: ASR {Math.round(voiceTurnResult.breakdown_ms.asr)}ms · LLM {Math.round(voiceTurnResult.breakdown_ms.llm)}ms · TTS {Math.round(voiceTurnResult.breakdown_ms.tts)}ms · 播放 {Math.round(voiceTurnResult.breakdown_ms.playback)}ms
                      </div>
                    )}
                  </div>
                )}
                <div className="voice-hint">
                  {bridgeReady
                    ? "点击或按空格键 → 说话 → 自动识别并回复（唤醒词已启用：" + (voiceStatus?.wake_words?.join(", ") || "Aivy") + "）"
                    : "演示模式：连接 Python 核心后即可使用真实麦克风语音对话"}
                </div>
                {bridgeReady && (
                  <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                    <span style={{ color: wakeLoopActive ? "#22c55e" : "var(--muted2)" }}>
                      {wakeLoopActive ? "●" : "○"} 后台语音唤醒
                    </span>
                    <button
                      onClick={async () => {
                        if (wakeLoopActive) {
                          await stopWakeLoop();
                          setWakeLoopActive(false);
                          wakeUnlistenRef.current?.();
                          wakeUnlistenRef.current = null;
                          showNotification("后台唤醒", "已停止监听", "success");
                        } else {
                          const r = await startWakeLoop();
                          if (r.ok) {
                            setWakeLoopActive(true);
                            showNotification("后台唤醒", "已启动，随时可以说唤醒词", "success");
                          }
                        }
                      }}
                      style={{
                        padding: "4px 12px",
                        borderRadius: 12,
                        border: `1px solid ${wakeLoopActive ? "#22c55e" : "var(--border)"}`,
                        background: wakeLoopActive ? "rgba(34,197,94,0.1)" : "transparent",
                        color: wakeLoopActive ? "#22c55e" : "var(--muted2)",
                        cursor: "pointer",
                        fontSize: 11,
                      }}
                    >
                      {wakeLoopActive ? "停止" : "启动"}
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* ============ 3. 任务 (task) ============ */}
            <div className={`screen ${nav === "task" ? "active" : ""}`}>
              <div className="task-layout">
                <div className="task-header">
                  <div>
                    <div className="task-title">AI 自主任务中心</div>
                    <div className="task-source">{bridgeReady ? "已连接 Python 核心" : "演示模式 · 核心未连接"}</div>
                  </div>
                </div>
                <div className="glass-card" style={{ padding: 16, marginBottom: 16 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, color: "var(--accent)" }}>➕ 创建新任务</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input
                      className="chat-input"
                      style={{ flex: 1, height: 36 }}
                      placeholder="描述您想让 AI 执行的任务，如：帮我处理今天的邮件并生成周报"
                      value={taskDescInput}
                      onChange={e => setTaskDescInput(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter") handleCreateTask(); }}
                    />
                    <button className="btn btn-approve" style={{ height: 36 }} onClick={handleCreateTask}>
                      {tasksLoading ? "创建中..." : "⚡ 创建任务"}
                    </button>
                  </div>
                </div>
                <div className="task-body">
                  <div className="task-sidebar">
                    <div className="glass-card" style={{ padding: 14 }}>
                      <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--accent)", marginBottom: 8 }}>
                        任务列表 ({tasks.length})
                      </div>
                      {tasksLoading && <div style={{ fontSize: 12, color: "var(--muted)" }}>加载中...</div>}
                      {!tasksLoading && tasks.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)" }}>暂无任务，创建一个开始吧</div>}
                      {!tasksLoading && tasks.map(task => (
                        <div
                          key={task.id}
                          className={`task-list-item ${activeTaskId === task.id ? "active" : ""}`}
                          style={{
                            padding: "10px", borderRadius: 8, marginBottom: 6, cursor: "pointer",
                            background: activeTaskId === task.id ? "rgba(59,130,246,0.12)" : "rgba(0,0,0,0.15)",
                            border: activeTaskId === task.id ? "1px solid rgba(59,130,246,0.3)" : "1px solid transparent",
                          }}
                          onClick={() => setActiveTaskId(task.id)}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <span style={{ fontSize: 13, fontWeight: 500 }}>{task.title}</span>
                            <span style={{
                              fontSize: 10, padding: "2px 6px", borderRadius: 3,
                              color: task.status === "completed" ? "var(--success)" : task.status === "error" ? "var(--danger)" : "var(--accent)"
                            }}>
                              {task.status === "working" ? "执行中" : task.status === "completed" ? "已完成" : task.status === "error" ? "异常" : "待执行"}
                            </span>
                          </div>
                          <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4 }}>
                            步骤 {task.current_step}/{task.steps.length}
                          </div>
                        </div>
                      ))}
                    </div>
                    {activeTask && (
                      <div className="glass-card" style={{ padding: 14 }}>
                        <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 10, color: "var(--muted2)" }}>执行进度</div>
                        <div className="task-steps">
                          {activeTask.steps.map((step, i) => {
                            const done = i < activeTask.current_step || activeTask.status === "completed";
                            const current = i === activeTask.current_step - 1 && activeTask.status === "working";
                            return (
                              <div key={i} className={`task-step ${done ? "done" : current ? "active" : "pending"}`}>
                                <div className={`step-icon ${done ? "done" : current ? "active" : "pending"}`}>
                                  {done ? "✓" : current ? "" : i + 1}
                                </div>
                                <span>{step.title}</span>
                              </div>
                            );
                          })}
                        </div>
                        <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid rgba(255,255,255,0.06)" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 4 }}>
                            <span style={{ color: "var(--muted)" }}>进度</span>
                            <span style={{ color: "var(--accent)" }}>
                              {activeTask.status === "completed" ? 100 : Math.round((activeTask.current_step / activeTask.steps.length) * 100)}%
                            </span>
                          </div>
                          <div className="progress-bar">
                            <div className="progress-fill" style={{ width: `${activeTask.status === "completed" ? 100 : Math.round((activeTask.current_step / activeTask.steps.length) * 100)}%` }} />
                          </div>
                          {activeTask.status !== "completed" && (
                            <button
                              className="btn btn-approve"
                              style={{ width: "100%", marginTop: 10, fontSize: 12, padding: "6px" }}
                              onClick={() => handleExecuteTask(activeTask.id)}
                              disabled={taskExecuting === activeTask.id}
                            >
                              {taskExecuting === activeTask.id ? "执行中..." : `▶ 执行下一步`}
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="task-detail">
                    {activeTask ? (
                      <>
                        <div className="glass-card" style={{ padding: 14 }}>
                          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: "var(--accent)" }}>{activeTask.title}</div>
                          {activeTask.steps.map((step, i) => (
                            <div key={i} style={{
                              padding: 10, borderRadius: 6, marginBottom: 6,
                              background: i < activeTask.current_step || activeTask.status === "completed"
                                ? "rgba(16,185,129,0.08)"
                                : i === activeTask.current_step - 1 && activeTask.status === "working"
                                ? "rgba(59,130,246,0.08)"
                                : "rgba(0,0,0,0.12)",
                            }}>
                              <div style={{ fontSize: 13, fontWeight: 500 }}>
                                {i + 1}. {step.title}
                                {i < activeTask.current_step || activeTask.status === "completed" ? " ✓" : ""}
                              </div>
                              <div style={{ fontSize: 11, color: "var(--muted2)", marginTop: 2 }}>{step.detail}</div>
                            </div>
                          ))}
                        </div>
                        <div className="glass-card" style={{ padding: 14 }}>
                          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 8, color: "var(--muted2)" }}>实时日志</div>
                          <div className="task-log">
                            {activeTask.logs.slice(-8).map((log, i) => (
                              <div key={i} className={`log-entry ${i === activeTask.logs.slice(-8).length - 1 ? "log-active" : ""}`}>
                                <span className="log-time">[{String(i + 1).padStart(2, "0")}]</span> {log}
                              </div>
                            ))}
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="glass-card" style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>选择一个任务查看详情，或创建新任务</div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* ============ 4. 定时 (sched) ============ */}
            <div className={`screen ${nav === "sched" ? "active" : ""}`}>
              <div className="sched-layout">
                <div className="sched-header">
                  <div style={{ fontSize: 18, fontWeight: 700 }}>定时任务中心</div>
                  <button className="btn btn-approve" style={{ padding: "6px 16px" }} onClick={() => setShowAddSched(v => !v)}>+ 新建任务</button>
                </div>
                {showAddSched && (
                  <div className="glass-card" style={{ padding: 16, marginBottom: 16 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, color: "var(--accent)" }}>➕ 创建定时任务</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <label style={{ width: 100, fontSize: 12, color: "var(--muted)" }}>任务名称</label>
                        <input className="chat-input" style={{ flex: 1, height: 32 }} placeholder="如：每日邮件检查" value={schedNameInput} onChange={e => setSchedNameInput(e.target.value)} />
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <label style={{ width: 100, fontSize: 12, color: "var(--muted)" }}>Cron 表达式</label>
                        <input className="chat-input" style={{ flex: 1, height: 32 }} placeholder="如：0 21 * * * (每天 21:00)" value={schedCronInput} onChange={e => setSchedCronInput(e.target.value)} />
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <label style={{ width: 100, fontSize: 12, color: "var(--muted)" }}>执行指令</label>
                        <input className="chat-input" style={{ flex: 1, height: 32 }} placeholder="如：检查并处理未读邮件" value={schedHandlerInput} onChange={e => setSchedHandlerInput(e.target.value)} onKeyDown={e => { if (e.key === "Enter") handleCreateSchedule(); }} />
                      </div>
                      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 4 }}>
                        <button className="btn btn-skip" style={{ padding: "6px 14px" }} onClick={() => setShowAddSched(false)}>取消</button>
                        <button className="btn btn-approve" style={{ padding: "6px 14px" }} onClick={handleCreateSchedule}>
                          {schedLoading ? "创建中..." : "✓ 创建"}
                        </button>
                      </div>
                    </div>
                  </div>
                )}
                <div className="sched-body">
                  <div className="sched-list stagger">
                    {schedLoading && <div style={{ fontSize: 12, color: "var(--muted)", padding: 20 }}>加载中...</div>}
                    {!schedLoading && schedules.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)", padding: 20 }}>暂无定时任务</div>}
                    {!schedLoading && schedules.map((item, i) => (
                      <div
                        key={i}
                        className={`sched-item glass-card ${activeSchedIdx === i ? "active" : ""}`}
                        onClick={() => setActiveSchedIdx(i)}
                      >
                        <div className="sched-item-top">
                          <div className="sched-item-name">
                            <div className={`sched-dot ${item.error ? "paused" : "active"}`} />
                            {item.name}
                          </div>
                          <span style={{ color: item.error ? "var(--danger)" : "var(--success)", fontSize: 10 }}>
                            {item.error ? "异常" : "活跃"}
                          </span>
                        </div>
                        <div className="sched-item-desc">
                          {item.kind} · 已执行 {item.runs} 次
                          {item.last_run && <span style={{ color: "var(--muted)", marginLeft: 8 }}>上次: {item.last_run}</span>}
                        </div>
                        {item.error && <div style={{ fontSize: 10, color: "var(--danger)", marginTop: 6 }}>⚠ {item.error}</div>}
                      </div>
                    ))}
                  </div>
                  <div className="sched-detail">
                    {activeSched && (
                      <div className="glass-card" style={{ padding: 16 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                          <span style={{ fontSize: 15, fontWeight: 600 }}>{activeSched.name}</span>
                          <div className="btn-group">
                            <button className="btn btn-skip" style={{ fontSize: 10, padding: "3px 10px" }}>编辑</button>
                            <button className="btn btn-skip" style={{ fontSize: 10, padding: "3px 10px", color: activeSched.error ? "var(--success)" : "var(--danger)" }}>
                              {activeSched.error ? "恢复" : "暂停"}
                            </button>
                          </div>
                        </div>
                        <div className="sched-stats">
                          <div className="sched-stat"><div className="sched-stat-label">Cron</div><div className="sched-stat-value">{activeSched.kind}</div></div>
                          <div className="sched-stat"><div className="sched-stat-label">上次执行</div><div className="sched-stat-value" style={{ color: "var(--accent)" }}>{activeSched.last_run || "未执行"}</div></div>
                          <div className="sched-stat"><div className="sched-stat-label">执行次数</div><div className="sched-stat-value">{activeSched.runs}</div></div>
                          <div className="sched-stat"><div className="sched-stat-label">状态</div><div className="sched-stat-value" style={{ color: activeSched.error ? "var(--danger)" : "var(--success)" }}>{activeSched.error ? "异常" : "正常"}</div></div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* ============ 5. Vibe Coding (vibe) ============ */}
            <div className={`screen ${nav === "vibe" ? "active" : ""}`}>
              <div className="vibe-layout">
                <div style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>Vibe Coding — AI 实时代码生成</div>
                  <button className="btn btn-approve" onClick={handleRunVibe} disabled={vibeLoading}>
                    {vibeLoading ? "生成中..." : "▶ 运行"}
                  </button>
                </div>
                <div className="glass-card" style={{ padding: 14, marginBottom: 12 }}>
                  <div style={{ fontSize: 12, color: "var(--muted2)", marginBottom: 8 }}>描述您想要 AI 生成的代码/产品</div>
                  <textarea
                    className="chat-input"
                    style={{ width: "100%", minHeight: 60, resize: "vertical", fontFamily: "inherit" }}
                    value={vibeRequest}
                    onChange={e => setVibeRequest(e.target.value)}
                    placeholder="如：创建一个项目周会 PPT 大纲，包含封面、里程碑、关键指标和下季度规划"
                  />
                </div>
                {vibeResult ? (
                  <div className="vibe-editor">
                    <div className="vibe-code">
                      <span style={{ color: "var(--muted)" }}>// AI 生成结果</span><br />
                      {vibeResult.ok && vibeResult.files ? (
                        Object.entries(vibeResult.files).map(([fname, content]) => (
                          <div key={fname} style={{ marginTop: 8 }}>
                            <span style={{ color: "var(--accent3)" }}>// 文件: {fname}</span><br />
                            <span style={{ color: "var(--ink)", whiteSpace: "pre-wrap", fontSize: 12 }}>
                              {typeof content === "string" ? content.slice(0, 300) + (content.length > 300 ? "..." : "") : JSON.stringify(content)}
                            </span><br />
                          </div>
                        ))
                      ) : (
                        <span style={{ color: "var(--danger)" }}>{vibeResult.error || "生成失败"}</span>
                      )}
                    </div>
                    <div className="vibe-preview">
                      <div className="vibe-preview-bar">
                        <div className="vibe-preview-dot" style={{ background: "#ff5f57" }} />
                        <div className="vibe-preview-dot" style={{ background: "#febc2e" }} />
                        <div className="vibe-preview-dot" style={{ background: "#28c840" }} />
                      </div>
                      <div style={{ padding: 20 }}>
                        {vibeResult.ok ? (
                          <>
                            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: "var(--success)" }}>✓ 构建完成</div>
                            {vibeResult.preview_url && <div style={{ fontSize: 11, color: "var(--muted2)", marginBottom: 8 }}>预览 URL: {vibeResult.preview_url}</div>}
                            {vibeResult.steps && <div style={{ fontSize: 11, color: "var(--muted2)" }}>工作流步骤: {Object.keys(vibeResult.steps).join(" → ")}</div>}
                            {vibeResult.delivered_to && <div style={{ fontSize: 11, color: "var(--accent)", marginTop: 6 }}>交付至: {vibeResult.delivered_to}</div>}
                          </>
                        ) : (
                          <div style={{ fontSize: 14, color: "var(--danger)" }}>✗ 生成失败: {vibeResult.error}</div>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="glass-card" style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>
                    {vibeLoading ? "AI 正在生成代码..." : "点击「运行」开始 Vibe Coding 流程"}
                  </div>
                )}
              </div>
            </div>

            {/* ============ 6. 知识卡片 (memory) ============ */}
            <div className={`screen ${nav === "memory" ? "active" : ""}`}>
              <div className="memory-layout">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>🧠 知识卡片</div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--muted2)" }}>
                    <span>共 {kStats.total} 张 · 收藏 {kStats.favorites}</span>
                    <button className="btn btn-skip" style={{ padding: "4px 10px", fontSize: 11 }} onClick={handleKGraph} title="知识图谱可视化">🕸️ 图谱</button>
                    <button className="btn btn-skip" style={{ padding: "4px 10px", fontSize: 11 }} onClick={handleKBackup} title="备份全部卡片">💾 备份</button>
                    <button className="btn btn-approve" style={{ padding: "4px 12px", fontSize: 12 }} onClick={() => { setKShowNew(true); setKEditForm({ title: "", summary: "", content: "", category: "其他", tags: "" }); }}>＋ 新建卡片</button>
                  </div>
                </div>

                {/* 知识图谱视图 */}
                {kShowGraph && (
                  <div className="glass-card" style={{ padding: 14, marginBottom: 14 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--accent)" }}>🕸️ 知识图谱（{kGraph.nodes.length} 节点 · {kGraph.edges.length} 关联）</div>
                      <button className="kcard-btn" onClick={() => setKShowGraph(false)}>✕ 关闭</button>
                    </div>
                    {kGraph.nodes.length === 0 ? (
                      <div style={{ fontSize: 12, color: "var(--muted)", padding: 20, textAlign: "center" }}>暂无节点，创建卡片或建立关联后显示</div>
                    ) : (
                      <KnowledgeGraphView nodes={kGraph.nodes} edges={kGraph.edges}
                        onNodeClick={(id) => {
                          const card = kCards.find(c => c.id === id);
                          if (card) handleKExpand(card);
                        }}
                        onNodeDoubleClick={(id) => {
                          const card = kCards.find(c => c.id === id);
                          if (card) handleKEdit(card);
                        }}
                      />
                    )}
                  </div>
                )}

                {/* 导出/分享模态 */}
                {kExportText && (
                  <div className="glass-card" style={{ padding: 14, marginBottom: 14, border: "1px solid var(--accent)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--accent)" }}>📤 卡片分享</div>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button className="btn btn-approve" style={{ padding: "4px 10px", fontSize: 11 }} onClick={() => handleKCopy(kExportText)}>📋 复制</button>
                        <button className="kcard-btn" onClick={() => setKExportText(null)}>✕ 关闭</button>
                      </div>
                    </div>
                    <textarea className="chat-input" readOnly style={{ width: "100%", minHeight: 160, fontSize: 12, fontFamily: "monospace" }} value={kExportText} />
                  </div>
                )}

                {/* 筛选与搜索栏 */}
                <div className="glass-card" style={{ padding: 12, marginBottom: 14 }}>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <input className="chat-input" style={{ flex: 1, minWidth: 180, height: 34 }} placeholder="搜索知识卡片（标题/内容/标签）..."
                      value={kSearch} onChange={e => setKSearch(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter") handleKSearch(); }} />
                    <button className="btn btn-approve" style={{ height: 34, padding: "0 14px" }} onClick={handleKSearch}>🔍 搜索</button>
                    <select className="chat-input" style={{ height: 34, width: 130 }} value={kCategory} onChange={e => { setKCategory(e.target.value); }}>
                      <option value="">全部分类</option>
                      {kStats.categories.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                    <select className="chat-input" style={{ height: 34, width: 130 }} value={kTag} onChange={e => { setKTag(e.target.value); }}>
                      <option value="">全部标签</option>
                      {kStats.tags.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                    <select className="chat-input" style={{ height: 34, width: 120 }} value={kSort} onChange={e => { setKSort(e.target.value); }}>
                      <option value="updated">按更新时间</option>
                      <option value="created">按创建时间</option>
                      <option value="favorite">按收藏优先</option>
                      <option value="usage">按使用频率</option>
                    </select>
                    <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--muted2)", cursor: "pointer" }}>
                      <input type="checkbox" checked={kFavOnly} onChange={e => setKFavOnly(e.target.checked)} /> 仅收藏
                    </label>
                  </div>
                </div>

                {/* 新建卡片表单 */}
                {kShowNew && (
                  <div className="glass-card" style={{ padding: 14, marginBottom: 14, border: "1px solid var(--accent)" }}>
                    <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, color: "var(--accent)" }}>新建知识卡片</div>
                    <div style={{ display: "grid", gap: 8 }}>
                      <input className="chat-input" style={{ height: 34 }} placeholder="标题 *" value={kEditForm.title} onChange={e => setKEditForm(p => ({ ...p, title: e.target.value }))} />
                      <input className="chat-input" style={{ height: 34 }} placeholder="摘要（一句话）" value={kEditForm.summary} onChange={e => setKEditForm(p => ({ ...p, summary: e.target.value }))} />
                      <textarea className="chat-input" style={{ minHeight: 70, resize: "vertical" }} placeholder="详细内容" value={kEditForm.content} onChange={e => setKEditForm(p => ({ ...p, content: e.target.value }))} />
                      <div style={{ display: "flex", gap: 8 }}>
                        <select className="chat-input" style={{ height: 34, flex: 1 }} value={kEditForm.category} onChange={e => setKEditForm(p => ({ ...p, category: e.target.value }))}>
                          {["其他", "个人偏好", "概念定义", "个人信息", "要点", "知识总结", "习惯日程"].map(c => <option key={c} value={c}>{c}</option>)}
                        </select>
                        <input className="chat-input" style={{ height: 34, flex: 2 }} placeholder="标签（逗号分隔）" value={kEditForm.tags} onChange={e => setKEditForm(p => ({ ...p, tags: e.target.value }))} />
                      </div>
                      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                        <button className="btn btn-skip" style={{ padding: "6px 14px" }} onClick={() => setKShowNew(false)}>取消</button>
                        <button className="btn btn-approve" style={{ padding: "6px 14px" }} onClick={handleKCreate}>创建</button>
                      </div>
                    </div>
                  </div>
                )}

                {/* 编辑卡片表单 */}
                {kEditId && (() => {
                  const card = kCards.find(c => c.id === kEditId);
                  if (!card) return null;
                  return (
                    <div className="glass-card" style={{ padding: 14, marginBottom: 14, border: "1px solid var(--accent)" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, color: "var(--accent)" }}>编辑卡片（v{card.version}）</div>
                      <div style={{ display: "grid", gap: 8 }}>
                        <input className="chat-input" style={{ height: 34 }} value={kEditForm.title} onChange={e => setKEditForm(p => ({ ...p, title: e.target.value }))} />
                        <input className="chat-input" style={{ height: 34 }} value={kEditForm.summary} onChange={e => setKEditForm(p => ({ ...p, summary: e.target.value }))} />
                        <textarea className="chat-input" style={{ minHeight: 70 }} value={kEditForm.content} onChange={e => setKEditForm(p => ({ ...p, content: e.target.value }))} />
                        <div style={{ display: "flex", gap: 8 }}>
                          <select className="chat-input" style={{ height: 34, flex: 1 }} value={kEditForm.category} onChange={e => setKEditForm(p => ({ ...p, category: e.target.value }))}>
                            {["其他", "个人偏好", "概念定义", "个人信息", "要点", "知识总结", "习惯日程"].map(c => <option key={c} value={c}>{c}</option>)}
                          </select>
                          <input className="chat-input" style={{ height: 34, flex: 2 }} value={kEditForm.tags} onChange={e => setKEditForm(p => ({ ...p, tags: e.target.value }))} />
                        </div>
                        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                          <button className="btn btn-skip" style={{ padding: "6px 14px" }} onClick={() => setKEditId(null)}>取消</button>
                          <button className="btn btn-approve" style={{ padding: "6px 14px" }} onClick={() => handleKUpdate(card.id)}>保存</button>
                        </div>
                      </div>
                    </div>
                  );
                })()}

                {kLoading && <div style={{ fontSize: 12, color: "var(--muted)", padding: 20, textAlign: "center" }}>加载知识卡片...</div>}
                {!kLoading && kCards.length === 0 && (
                  <div style={{ fontSize: 13, color: "var(--muted)", padding: 30, textAlign: "center" }}>
                    暂无知识卡片。对话中会自动沉淀知识，或点击「＋ 新建卡片」手动创建。
                  </div>
                )}
                {!kLoading && kCards.length > 0 && (
                  <div className="memory-grid stagger">
                    {kCards.map(card => {
                      const colors = getMemoryColor(card.category);
                      const expanded = !!kExpanded[card.id];
                      const related = kRelated[card.id] || [];
                      return (
                        <div key={card.id} className={`memory-card kcard ${card.favorite ? "fav" : ""}`} style={{ borderTop: `3px solid ${colors.color}` }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 6 }}>
                            <span className="memory-card-type" style={{ background: colors.bg, color: colors.color }}>{card.category}</span>
                            <div style={{ display: "flex", gap: 4 }}>
                              <button className="kcard-btn" onClick={() => handleKFav(card.id)} title={card.favorite ? "取消收藏" : "收藏"}>{card.favorite ? "⭐" : "☆"}</button>
                              <button className="kcard-btn" onClick={() => handleKEdit(card)} title="编辑">✏️</button>
                              <button className="kcard-btn" onClick={() => handleKDelete(card.id, card.title)} title="删除">🗑️</button>
                            </div>
                          </div>
                          <div className="kcard-title" onClick={() => handleKExpand(card)} style={{ cursor: "pointer" }}>{card.title}</div>
                          {!expanded ? (
                            <div className="kcard-summary">{card.summary || card.content?.slice(0, 60) || "（无摘要）"}</div>
                          ) : (
                            <div className="kcard-body">
                              <div className="kcard-content">{card.content || "（无详细内容）"}</div>
                              {card.tags.length > 0 && (
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
                                  {card.tags.map(t => <span key={t} className="kcard-tag">{t}</span>)}
                                </div>
                              )}
                              {related.length > 0 && (
                                <div style={{ marginTop: 10, fontSize: 11, color: "var(--muted2)" }}>
                                  🔗 关联：{related.map(r => (
                                    <span key={r.id} style={{ color: "var(--accent)", cursor: "pointer", marginRight: 8 }} onClick={() => handleKExpand(r)}>{r.title}</span>
                                  ))}
                                </div>
                              )}
                              {/* 手动建立关联 + 分享 */}
                              <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
                                <button className="btn btn-skip" style={{ padding: "3px 10px", fontSize: 11 }} onClick={() => setKLinkTarget(kLinkTarget === card.id ? "" : card.id)}>
                                  {kLinkTarget === card.id ? "✕ 取消关联" : "🔗 建立关联"}
                                </button>
                                <button className="btn btn-skip" style={{ padding: "3px 10px", fontSize: 11 }} onClick={() => handleKExport(card, "markdown")}>📤 分享</button>
                              </div>
                              {kLinkTarget === card.id && (
                                <div style={{ marginTop: 8, display: "flex", gap: 6, alignItems: "center" }}>
                                  <select className="chat-input" style={{ height: 28, flex: 1, fontSize: 11 }} value="" onChange={e => handleKLink(card.id, e.target.value)}>
                                    <option value="">选择要关联的卡片...</option>
                                    {kCards.filter(c => c.id !== card.id && !card.links.includes(c.id)).map(c => (
                                      <option key={c.id} value={c.id}>{c.title}</option>
                                    ))}
                                  </select>
                                </div>
                              )}
                              {card.versions.length > 0 && (
                                <div style={{ marginTop: 10, fontSize: 11, color: "var(--muted2)" }}>
                                  📜 历史 {card.versions.length} 个版本（当前 v{card.version}）
                                </div>
                              )}
                            </div>
                          )}
                          <div className="kcard-meta">
                            <span>创建 {card.created_at?.slice(0, 16).replace("T", " ")}</span>
                            <span>更新 {card.updated_at?.slice(0, 16).replace("T", " ")}</span>
                            {card.usage > 0 && <span>调用 {card.usage} 次</span>}
                            <span style={{ marginLeft: "auto" }}>{expanded ? "▾ 收起" : "▸ 展开"}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* ============ 7. 自检 (boot) ============ */}
            <div className={`screen ${nav === "boot" ? "active" : ""}`}>
              <div className="boot-screen">
                <div className="boot-logo">薇</div>
                <div>
                  <div className="boot-title">AivyOS 系统自检</div>
                  <div className="boot-subtitle">{bootLoading ? "正在检查系统环境与核心组件..." : bootResult?.summary || "点击重新自检"}</div>
                </div>
                {bootResult && (
                  <div className="boot-checklist">
                    {bootResult.checks.map((item, i) => (
                      <div key={i} className={`boot-check-item ${item.ok ? "ok" : "warn"}`}>
                        <div className={`boot-check-icon ${item.ok ? "ok" : "warn"}`}>{item.ok ? "✓" : "⚠"}</div>
                        <div className="boot-check-name">{item.name}</div>
                        <div className={`boot-check-status ${item.ok ? "ok" : "warn"}`}>{item.detail}</div>
                      </div>
                    ))}
                  </div>
                )}
                {!bootResult && !bootLoading && (
                  <div style={{ fontSize: 13, color: "var(--muted)", padding: 20 }}>尚未执行自检，点击下方按钮开始</div>
                )}
                <div className="boot-progress">
                  <div className="boot-progress-bar"><div className="boot-progress-fill" style={{ width: `${bootLoading ? 30 : bootProgressVal}%` }} /></div>
                  <div className="boot-progress-text">
                    <span>{bootLoading ? "正在检查..." : bootProgressVal < 100 && bootResult ? "检查完成" : `${bootProgressVal}%`}</span>
                    <span>{bootLoading ? "30%" : `${bootProgressVal}%`}</span>
                  </div>
                </div>
                <div className="boot-actions">
                  <button className="btn btn-approve" onClick={() => runBoot(false)} disabled={bootLoading}>{bootLoading ? "检查中..." : "▶ 深度自检"}</button>
                  <button className="btn btn-skip" onClick={() => handleNav("chat")}>进入主界面 →</button>
                </div>
              </div>
            </div>

            {/* ============ 8. 语音设置 (voiceset) ============ */}
            <div className={`screen ${nav === "voiceset" ? "active" : ""}`}>
              <div className="voiceset-screen">
                <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>语音设置 — ASR、TTS 与设备</div>
                {vsetLoading && <div style={{ fontSize: 12, color: "var(--muted)", padding: 20, textAlign: "center" }}>加载中...</div>}
                {!vsetLoading && (
                  <>
                    {/* 0. 语音唤醒 */}
                    <div className="glass-card" style={{ padding: 16, marginBottom: 16 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                        <span style={{ fontSize: 14 }}>🔊</span>
                        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--accent)" }}>语音唤醒</span>
                      </div>
                      <div style={{ marginBottom: 14 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                          <span style={{ fontSize: 12, color: "var(--muted)" }}>唤醒词</span>
                        </div>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <input
                            className="chat-input" style={{ flex: 1, height: 32 }}
                            placeholder="说出唤醒词激活语音模式"
                            value={vsetWakeWord}
                            onChange={e => setVsetWakeWord(e.target.value)}
                          />
                          <button className="btn btn-approve" style={{ height: 32, padding: "0 14px", whiteSpace: "nowrap" }} onClick={handleSaveWakeWord}>保存</button>
                        </div>
                      </div>
                      <div style={{ marginBottom: 14 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                          <span style={{ fontSize: 12, color: "var(--muted)" }}>唤醒灵敏度</span>
                          <span style={{ fontSize: 13, color: "var(--accent)", fontWeight: 700 }}>{Math.round((1 - vsetSensitivity / 0.05) * 100)}%</span>
                        </div>
                        <input
                          type="range"
                          min="0"
                          max="100"
                          step="1"
                          value={Math.round((1 - vsetSensitivity / 0.05) * 100)}
                          onChange={e => {
                            const pct = parseFloat(e.target.value);
                            setVsetSensitivity(0.05 * (1 - pct / 100));
                          }}
                          style={{ width: "100%", accentColor: "var(--accent)" }}
                        />
                        <div style={{ fontSize: 11, color: "var(--muted2)", marginTop: 4 }}>
                          值越高越容易唤醒，但可能误触发
                        </div>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div>
                          <div style={{ fontSize: 12, color: "var(--ink)", fontWeight: 500 }}>连续对话模式</div>
                          <div style={{ fontSize: 11, color: "var(--muted2)" }}>唤醒后保持 listening，无需重复唤醒</div>
                        </div>
                        <div className={`toggle ${vsetContinuous ? "on" : ""}`} onClick={() => setVsetContinuous(v => !v)}>
                          <div className="toggle-thumb" />
                        </div>
                      </div>
                    </div>

                    {/* 1. 语音识别配置 */}
                    <div className="glass-card" style={{ padding: 16, marginBottom: 16 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: "var(--accent)" }}>语音识别配置</div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
                        <label style={{ width: 80, fontSize: 12, color: "var(--muted)" }}>服务商</label>
                        <select
                          className="chat-input" style={{ flex: 1, height: 32 }}
                          value={vsetAsrProvider}
                          onChange={e => setVsetAsrProvider(e.target.value)}
                        >
                          {ASR_PROVIDERS.map(p => (
                            <option key={p.id} value={p.id}>{p.name}</option>
                          ))}
                        </select>
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
                        <label style={{ width: 80, fontSize: 12, color: "var(--muted)" }}>API Key</label>
                        <input
                          className="chat-input" style={{ flex: 1, height: 32 }}
                          placeholder="留空则不修改"
                          type="password"
                          value={vsetAsrApiKey}
                          onChange={e => setVsetAsrApiKey(e.target.value)}
                        />
                        <button className="btn btn-approve" style={{ height: 32 }} onClick={() => {
                          showNotification("保存成功", `ASR 服务商已保存：${vsetAsrProvider}`, "success");
                        }}>保存</button>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--muted2)" }}>
                        选择云端 ASR 服务商并配置 API Key，留空则保持原有设置不变
                      </div>
                    </div>

                    {/* 2. 语音识别灵敏度 */}
                    <div className="glass-card" style={{ padding: 16, marginBottom: 16 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: "var(--accent)" }}>语音识别灵敏度</div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <span style={{ fontSize: 12, color: "var(--muted)" }}>触发阈值 (VAD Threshold)</span>
                        <span style={{ fontSize: 12, color: "var(--accent)", fontWeight: 600 }}>{vsetSensitivity.toFixed(3)}</span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="0.05"
                        step="0.001"
                        value={vsetSensitivity}
                        onChange={e => setVsetSensitivity(parseFloat(e.target.value))}
                        style={{ width: "100%", accentColor: "var(--accent)" }}
                      />
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--muted2)", marginTop: 2 }}>
                        <span>0 (最灵敏)</span><span>0.025</span><span>0.05 (最严格)</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
                        <button
                          className="btn btn-skip"
                          style={{ fontSize: 11, padding: "4px 12px" }}
                          onClick={() => setVsetSensitivity(0.008)}
                        >重置</button>
                      </div>
                    </div>

                    {/* 3. 语音合成(TTS) */}
                    <div className="glass-card" style={{ padding: 16, marginBottom: 16 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: "var(--accent)" }}>语音合成 (TTS)</div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
                        <label style={{ width: 80, fontSize: 12, color: "var(--muted)" }}>服务商</label>
                        <select
                          className="chat-input" style={{ flex: 1, height: 32 }}
                          value={vsetTtsProvider}
                          onChange={e => {
                            const newProvider = e.target.value;
                            setVsetTtsProvider(newProvider);
                            const voices = TTS_VOICES[newProvider];
                            if (voices && voices.length > 0) setVsetTtsVoice(voices[0].id);
                          }}
                        >
                          {TTS_PROVIDERS.map(p => (
                            <option key={p.id} value={p.id}>{p.name}</option>
                          ))}
                        </select>
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
                        <label style={{ width: 80, fontSize: 12, color: "var(--muted)" }}>音色</label>
                        <select
                          className="chat-input" style={{ flex: 1, height: 32 }}
                          value={vsetTtsVoice}
                          onChange={e => setVsetTtsVoice(e.target.value)}
                        >
                          {(TTS_VOICES[vsetTtsProvider] || []).map(v => (
                            <option key={v.id} value={v.id}>{v.name}</option>
                          ))}
                        </select>
                      </div>
                      <div style={{ marginBottom: 10 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                          <span style={{ fontSize: 12, color: "var(--muted)" }}>语速</span>
                          <span style={{ fontSize: 12, color: "var(--accent)", fontWeight: 600 }}>{vsetTtsSpeed.toFixed(1)}x</span>
                        </div>
                        <input
                          type="range"
                          min="0.5"
                          max="2.0"
                          step="0.1"
                          value={vsetTtsSpeed}
                          onChange={e => setVsetTtsSpeed(parseFloat(e.target.value))}
                          style={{ width: "100%", accentColor: "var(--accent)" }}
                        />
                        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--muted2)" }}>
                          <span>0.5x</span><span>1.0x</span><span>2.0x</span>
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 10 }}>
                        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--muted)", cursor: "pointer" }}>
                          <input
                            type="checkbox"
                            checked={vsetPlaybackLive}
                            onChange={e => setVsetPlaybackLive(e.target.checked)}
                            style={{ accentColor: "var(--accent)" }}
                          />
                          边合成边播放
                        </label>
                        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: vsetRobotUnlocked ? "var(--muted)" : "var(--muted2)", cursor: vsetRobotUnlocked ? "pointer" : "not-allowed", opacity: vsetRobotUnlocked ? 1 : 0.5 }}>
                          <input
                            type="checkbox"
                            checked={vsetRobotEffect}
                            disabled={!vsetRobotUnlocked}
                            onChange={e => setVsetRobotEffect(e.target.checked)}
                            style={{ accentColor: "var(--accent)" }}
                          />
                          机器人音效 {!vsetRobotUnlocked && "🔒"}
                        </label>
                      </div>
                      {!vsetRobotUnlocked && (
                        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, padding: "8px 10px", borderRadius: 6, background: "rgba(139,92,246,0.08)", border: "1px solid rgba(139,92,246,0.2)" }}>
                          <span style={{ fontSize: 11, color: "var(--accent3)" }}>解锁机器人音效：</span>
                          <input
                            className="chat-input"
                            style={{ flex: 1, height: 28, fontSize: 11 }}
                            placeholder="输入解锁密码（至少 4 位）"
                            type="password"
                            value={vsetRobotPwd}
                            onChange={e => setVsetRobotPwd(e.target.value)}
                          />
                          <button
                            className="btn btn-approve"
                            style={{ height: 28, fontSize: 11 }}
                            onClick={handleUnlockRobot}
                          >解锁</button>
                        </div>
                      )}
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
                        <label style={{ width: 80, fontSize: 12, color: "var(--muted)" }}>API Key</label>
                        <input
                          className="chat-input" style={{ flex: 1, height: 32 }}
                          placeholder="留空则不修改"
                          type="password"
                          value={vsetTtsApiKey}
                          onChange={e => setVsetTtsApiKey(e.target.value)}
                        />
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
                        <label style={{ width: 80, fontSize: 12, color: "var(--muted)" }}>资源 ID</label>
                        <input
                          className="chat-input" style={{ flex: 1, height: 32 }}
                          placeholder="自动匹配..."
                          value={vsetTtsResourceId}
                          onChange={e => setVsetTtsResourceId(e.target.value)}
                        />
                      </div>
                      {vsetTestResult && (
                        <div style={{ fontSize: 11, color: vsetTestResult.includes("失败") ? "var(--danger)" : "var(--success)", padding: "8px 10px", borderRadius: 6, background: vsetTestResult.includes("失败") ? "rgba(239,68,68,0.1)" : "rgba(16,185,129,0.1)", marginBottom: 10 }}>
                          {vsetTestResult}
                        </div>
                      )}
                      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                        <button
                          className="btn btn-skip"
                          style={{ fontSize: 11, padding: "6px 14px" }}
                          disabled={vsetTesting}
                          onClick={handleTestVoice}
                        >{vsetTesting ? "试听中..." : "试听"}</button>
                        <button
                          className="btn btn-approve"
                          style={{ fontSize: 11, padding: "6px 14px" }}
                          onClick={handleSaveTts}
                        >保存</button>
                      </div>
                    </div>

                    {/* 4. 设备设置 */}
                    <div className="glass-card" style={{ padding: 16 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: "var(--accent)" }}>设备设置</div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
                        <label style={{ width: 80, fontSize: 12, color: "var(--muted)" }}>识别语言</label>
                        <select
                          className="chat-input" style={{ flex: 1, height: 32 }}
                          value={vsetListeningLang}
                          onChange={e => setVsetListeningLang(e.target.value)}
                        >
                          <option value="zh-CN">中文普通话</option>
                          <option value="en-US">English</option>
                          <option value="ja-JP">日本語</option>
                        </select>
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
                        <label style={{ width: 80, fontSize: 12, color: "var(--muted)" }}>麦克风</label>
                        <select
                          className="chat-input" style={{ flex: 1, height: 32 }}
                          value={vsetMicDevice}
                          onChange={e => setVsetMicDevice(e.target.value)}
                        >
                          {MIC_DEVICES.map((d, i) => (
                            <option key={i} value={d}>{d}</option>
                          ))}
                        </select>
                        <button className="btn btn-skip" style={{ height: 32 }} onClick={handleRefreshDevices}>刷新</button>
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <label style={{ width: 80, fontSize: 12, color: "var(--muted)" }}>输出设备</label>
                        <select
                          className="chat-input" style={{ flex: 1, height: 32 }}
                          value={vsetOutputDevice}
                          onChange={e => setVsetOutputDevice(e.target.value)}
                        >
                          {OUTPUT_DEVICES.map((d, i) => (
                            <option key={i} value={d}>{d}</option>
                          ))}
                        </select>
                        <button className="btn btn-skip" style={{ height: 32 }} onClick={handleRefreshDevices}>刷新</button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* ============ 9. 模型管理 (models) ============ */}
            <div className={`screen ${nav === "models" ? "active" : ""}`}>
              <div className="models-screen">
                {/* Header 状态栏 */}
                <div className="models-header">
                  <div>
                    <h2>🧩 模型管理</h2>
                    <div className="sub">
                      {bridgeReady
                        ? "模型部署 · 路由策略 · 成本与健康监控"
                        : "演示模式 · 连接核心后显示真实状态"}
                    </div>
                  </div>
                  {activeModelName && (
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <span className="models-lock-badge">🔒 锁定: {activeModelName}</span>
                      <button
                        className="btn btn-skip"
                        style={{ fontSize: 10, padding: "4px 10px" }}
                        onClick={async () => {
                          if (!bridgeReady) return;
                          try {
                            const result = await setActiveModel(null);
                            if (result.ok) {
                              setActiveModelName(null);
                              showNotification("已恢复", "自动路由模式已启用", "success");
                            }
                          } catch {}
                        }}
                      >恢复自动</button>
                    </div>
                  )}
                </div>

                {/* 卡片化 Tab 导航 */}
                <div className="models-tabs">
                  {([
                    { id: "health", label: "🩺 健康仪表盘" },
                    { id: "cost", label: "💰 成本追踪" },
                    { id: "list", label: "📋 模型列表" },
                  ] as const).map(tab => (
                    <button
                      key={tab.id}
                      className={`models-tab ${modelsTab === tab.id ? "active" : ""}`}
                      onClick={() => setModelsTab(tab.id)}
                    >{tab.label}</button>
                  ))}
                </div>

                {/* Tab: 健康仪表盘 */}
                {modelsTab === "health" && modelHealth.length > 0 && (
                  <div className="models-section">
                    <div className="models-section-title">
                      <h3>🩺 后端健康状态</h3>
                      <span className="hint">{modelHealth.length} 个后端 · 断路器 + 可用性</span>
                    </div>
                    <div className="models-health-grid">
                      {modelHealth.map((h, i) => (
                        <div key={i} className={`models-health-card ${h.available ? "ok" : "bad"}`}>
                          <div className="name">{h.model}</div>
                          <div className="provider">{h.provider}</div>
                          <div className="badges">
                            <span className={`models-badge ${h.breaker_state === "closed" ? "ok" : "bad"}`}>
                              {h.breaker_state === "closed" ? "✓ 熔断关闭" : "⚠ 熔断打开"}
                            </span>
                            <span className={`models-badge ${h.available ? "ok" : "bad"}`}>
                              {h.available ? "已就绪" : "不可用"}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {modelsTab === "health" && modelHealth.length === 0 && !modelsLoading && (
                  <div className="models-empty">
                    <div className="big">🩺</div>
                    {bridgeReady ? "健康数据加载中..." : "连接核心后显示后端状态"}
                  </div>
                )}

                {/* Tab: 成本追踪 */}
                {modelsTab === "cost" && modelCost && (
                  <>
                    <div className="models-stats">
                      <div className="models-stat">
                        <div className="label">总请求</div>
                        <div className="value" style={{ color: "var(--accent)" }}>{modelCost.total_requests}</div>
                      </div>
                      <div className="models-stat">
                        <div className="label">总 Token</div>
                        <div className="value" style={{ color: "var(--accent2)" }}>{modelCost.total_tokens.toLocaleString()}</div>
                      </div>
                      <div className="models-stat">
                        <div className="label">总成本</div>
                        <div className="value" style={{ color: "var(--warning)" }}>${modelCost.total_cost_usd.toFixed(4)}</div>
                      </div>
                      <div className="models-stat">
                        <div className="label">后端数</div>
                        <div className="value" style={{ color: "var(--accent3)" }}>{modelCost.backend_count}</div>
                      </div>
                    </div>
                    {Object.entries(modelCost.backends).length > 0 && (
                      <div className="models-section" style={{ marginTop: 12 }}>
                        <div className="models-section-title">
                          <h3>📊 每后端成本明细</h3>
                          <span className="hint">请求 · Token · 成本</span>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          {Object.entries(modelCost.backends).map(([name, stats]) => (
                            <div key={name} className="models-table-row" style={{ gridTemplateColumns: "2fr 1fr 1fr 1fr" }}>
                              <span className="row-title">{name}</span>
                              <span style={{ color: "var(--muted2)" }}>请求: {stats.total_requests}</span>
                              <span style={{ color: "var(--muted2)" }}>Token: {(stats.total_input_tokens + stats.total_output_tokens).toLocaleString()}</span>
                              <span style={{ color: "var(--warning)", textAlign: "right" }}>${stats.total_cost_usd.toFixed(4)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
                {modelsTab === "cost" && !modelCost && !modelsLoading && (
                  <div className="models-empty">
                    <div className="big">💰</div>
                    {bridgeReady ? "成本数据加载中..." : "连接核心后显示成本统计"}
                  </div>
                )}

                {/* Tab: 模型列表 */}
                {modelsTab === "list" && (
                  <>
                {/* 标题与描述 */}
                <div className="ml-header">
                  <div className="ml-header-left">
                    <h2>模型</h2>
                    <p className="ml-subtitle">填入各提供方的 API 密钥即可使用其模型。</p>
                  </div>
                  <button
                    className="btn btn-skip ml-config-btn"
                    onClick={() => {
                      showNotification("配置文件", "路径: ~/.aivyos/config.yaml", "success");
                    }}
                  >打开配置文件</button>
                </div>

                {/* 工具栏: 搜索 + 筛选 + 排序 + 添加按钮 */}
                <div className="ml-toolbar">
                  <div className="ml-search">
                    <input
                      type="text"
                      className="ml-search-input"
                      placeholder="搜索提供方名称或ID..."
                      value={providerSearch}
                      onChange={e => { setProviderSearch(e.target.value); }}
                    />
                  </div>
                  <div className="ml-toolbar-actions">
                    <select
                      className="ml-select"
                      value={providerFilter}
                      onChange={e => { setProviderFilter(e.target.value as any); }}
                    >
                      <option value="all">全部 ({catalog.length})</option>
                      <option value="configured">已配置</option>
                      <option value="unconfigured">未配置</option>
                      <option value="local">本地</option>
                      <option value="cloud">云端</option>
                    </select>
                    <select
                      className="ml-select"
                      value={providerSort}
                      onChange={e => setProviderSort(e.target.value as any)}
                    >
                      <option value="name">按名称排序</option>
                      <option value="status">按状态排序</option>
                      <option value="category">按类型排序</option>
                    </select>
                  </div>
                  <div className="ml-toolbar-buttons">
                    {/* 添加提供方按钮 + 下拉列表 */}
                    <div className="ml-dropdown-wrapper">
                      <button
                        className="btn btn-skip ml-add-btn"
                        onClick={() => {
                          setShowAddProviderDropdown(!showAddProviderDropdown);
                          setShowCustomProviderForm(false);
                        }}
                      >+ 添加提供方</button>
                      {showAddProviderDropdown && (
                        <div className="ml-dropdown-menu">
                          {catalog
                            .filter(p => {
                              const keyEntry = apiKeys[p.api_key_env] || apiKeys[p.id];
                              return !keyEntry?.has_key;
                            })
                            .map(p => (
                              <div
                                key={p.id}
                                className="ml-dropdown-item"
                                onClick={() => {
                                  setEditingProviderId(p.id);
                                  setEditingForm({
                                    providerId: p.id,
                                    apiKey: "",
                                    baseUrl: p.base_url,
                                    fetchedModels: [],
                                    fetching: false,
                                    customSettingsOpen: false,
                                    addedModels: [],
                                    testing: false,
                                    testResult: null,
                                  });
                                  setShowAddProviderDropdown(false);
                                }}
                              >
                                <span className="ml-dropdown-name">{p.name}</span>
                                <span className="ml-dropdown-status muted">未配置</span>
                              </div>
                            ))}
                          {catalog.filter(p => {
                            const keyEntry = apiKeys[p.api_key_env] || apiKeys[p.id];
                            return !keyEntry?.has_key;
                          }).length === 0 && (
                            <div className="ml-dropdown-empty">所有提供方均已配置</div>
                          )}
                        </div>
                      )}
                    </div>
                    {/* 添加自定义提供方按钮 */}
                    <button
                      className="btn btn-skip ml-add-btn"
                      onClick={() => {
                        setShowCustomProviderForm(!showCustomProviderForm);
                        setShowAddProviderDropdown(false);
                      }}
                    >+ 添加自定义提供方</button>
                  </div>
                </div>

                {/* 提供方列表 */}
                {(() => {
                  const getConfiguredCount = (p: ProviderCatalogEntry) => {
                    const key = apiKeys[p.api_key_env] || apiKeys[p.id];
                    return key?.has_key ? 1 : 0;
                  };
                  const isConfigured = (p: ProviderCatalogEntry) => getConfiguredCount(p) > 0;

                  let filtered = catalog.filter(p => {
                    if (providerSearch) {
                      const s = providerSearch.toLowerCase();
                      if (!p.name.toLowerCase().includes(s) && !p.id.toLowerCase().includes(s)) return false;
                    }
                    switch (providerFilter) {
                      case "configured": return isConfigured(p);
                      case "unconfigured": return !isConfigured(p);
                      case "local": return p.category === "local";
                      case "cloud": return p.category !== "local";
                      default: return true;
                    }
                  });

                  filtered.sort((a, b) => {
                    if (providerSort === "name") return a.name.localeCompare(b.name);
                    if (providerSort === "status") return (isConfigured(b) ? 1 : 0) - (isConfigured(a) ? 1 : 0);
                    if (providerSort === "category") return a.category.localeCompare(b.category);
                    return 0;
                  });

                  // 分组：本地模型 / 云端模型（category=local 归本地，其余归云端）
                  const localList = filtered.filter(p => p.category === "local");
                  const cloudList = filtered.filter(p => p.category !== "local");
                  const groups = [
                    { key: "local", icon: "🖥️", title: "本地模型", items: localList, cloud: false },
                    { key: "cloud", icon: "☁️", title: "云端模型", items: cloudList, cloud: true },
                  ];

                  return (
                    <>
                      {filtered.length === 0 ? (
                        <div className="models-empty">
                          <div className="big">📭</div>
                          {providerSearch || providerFilter !== "all" ? "未找到匹配的提供方" : "暂无提供方"}
                        </div>
                      ) : (
                        <div className="ml-groups">
                          {groups.map(group => (
                            <div key={group.key} className="ml-group">
                              {/* 分组标题栏 */}
                              <div className="ml-group-header">
                                <span className="ml-group-title">{group.icon} {group.title}</span>
                                <span className="ml-group-count">{group.items.length} 个</span>
                                {group.cloud && (
                                  <button
                                    className="btn btn-skip ml-test-cloud-btn"
                                    disabled={cloudTesting}
                                    onClick={handleTestCloud}
                                  >{cloudTesting ? "测试中..." : "🔍 测试云端连通性"}</button>
                                )}
                              </div>

                              {/* 组内提供方列表 */}
                              {group.items.length === 0 ? (
                                <div className="ml-group-empty">
                                  {group.cloud ? "暂无云端提供商，点击「+ 添加提供方」配置 API Key" : "暂无本地提供商"}
                                </div>
                              ) : (
                                <div className="ml-provider-list">
                                  {group.items.map(provider => {
                            const configured = isConfigured(provider);
                            const isEditing = editingProviderId === provider.id;
                            const keyEntry = apiKeys[provider.api_key_env] || apiKeys[provider.id];

                            return (
                              <div key={provider.id} className={`ml-provider-item ${isEditing ? "expanded" : ""} ${configured ? "configured" : ""}`}>
                                {/* 提供方行 */}
                                <div className="ml-provider-row" onClick={() => {
                                  if (isEditing) {
                                    setEditingProviderId(null);
                                    setEditingForm(null);
                                  } else {
                                    setEditingProviderId(provider.id);
                                    setEditingForm({
                                      providerId: provider.id,
                                      apiKey: keyEntry?.has_key ? "********" : "",
                                      baseUrl: provider.base_url,
                                      fetchedModels: [],
                                      fetching: false,
                                      customSettingsOpen: false,
                                      addedModels: [],
                                      testing: false,
                                      testResult: null,
                                    });
                                  }
                                }}>
                                  <div className="ml-provider-info">
                                    <span className="ml-status-dot" style={{ background: configured ? "#10b981" : "#6b7280" }}></span>
                                    <span className="ml-provider-name">{provider.name}</span>
                                    {configured && <span className="ml-config-tag">已配置</span>}
                                    {!configured && <span className="ml-config-tag muted">未配置</span>}
                                    {provider.category === "local" && <span className="ml-cat-tag local">本地</span>}
                                    {provider.category !== "local" && <span className="ml-cat-tag cloud">云端</span>}
                                  </div>
                                  <div className="ml-provider-actions">
                                    <button
                                      className="btn btn-approve ml-edit-btn"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        if (isEditing) {
                                          setEditingProviderId(null);
                                          setEditingForm(null);
                                        } else {
                                          setEditingProviderId(provider.id);
                                          setEditingForm({
                                            providerId: provider.id,
                                            apiKey: keyEntry?.has_key ? "********" : "",
                                            baseUrl: provider.base_url,
                                            fetchedModels: [],
                                            fetching: false,
                                            customSettingsOpen: false,
                                            addedModels: [],
                                            testing: false,
                                            testResult: null,
                                          });
                                        }
                                      }}
                                    >{isEditing ? "收起" : "编辑"}</button>
                                  </div>
                                </div>

                                {/* 展开编辑面板 */}
                                {isEditing && editingForm && (
                                  <div className="ml-edit-panel">
                                    {/* 提供方选择 */}
                                    <div className="ml-form-group">
                                      <label className="ml-label">提供方</label>
                                      <select
                                        className="ml-input"
                                        value={editingForm.providerId}
                                        onChange={e => {
                                          const p = catalog.find(c => c.id === e.target.value);
                                          if (p) {
                                            setEditingForm({
                                              ...editingForm,
                                              providerId: e.target.value,
                                              baseUrl: p.base_url,
                                              fetchedModels: [],
                                              addedModels: [],
                                              testResult: null,
                                            });
                                          }
                                        }}
                                      >
                                        {catalog.map(c => (
                                          <option key={c.id} value={c.id}>{c.name} ({c.id})</option>
                                        ))}
                                      </select>
                                    </div>

                                    {/* API 密钥 */}
                                    <div className="ml-form-group">
                                      <label className="ml-label">API 密钥</label>
                                      <input
                                        className="ml-input"
                                        type="password"
                                        placeholder="输入 API 密钥，或留空使用环境认证"
                                        value={editingForm.apiKey}
                                        onChange={e => setEditingForm({ ...editingForm, apiKey: e.target.value, testResult: null })}
                                      />
                                    </div>

                                    {/* 自定义设置 - 折叠 (API 地址 + 测试连接) */}
                                    <div className="ml-form-group">
                                      <button
                                        className="ml-collapse-toggle"
                                        onClick={() => setEditingForm({ ...editingForm, customSettingsOpen: !editingForm.customSettingsOpen })}
                                      >
                                        {editingForm.customSettingsOpen ? "▼" : "▶"} 自定义设置
                                      </button>
                                      {editingForm.customSettingsOpen && (
                                        <div className="ml-collapse-content">
                                          <div className="ml-form-group">
                                            <div className="ml-section-header">
                                              <label className="ml-label">API 地址</label>
                                              <button
                                                className="btn btn-skip ml-fetch-btn"
                                                style={{ fontSize: 11, padding: "4px 12px" }}
                                                disabled={editingForm.testing || !editingForm.baseUrl}
                                                onClick={async () => {
                                                  setEditingForm({ ...editingForm, testing: true, testResult: null });
                                                  try {
                                                    const keyToTest = editingForm.apiKey === "********" ? "" : editingForm.apiKey;
                                                    const result = await testModelConnection(
                                                      editingForm.providerId,
                                                      keyToTest,
                                                      editingForm.baseUrl
                                                    );
                                                    setEditingForm({
                                                      ...editingForm,
                                                      testing: false,
                                                      testResult: result,
                                                    });
                                                    if (result.ok) {
                                                      showNotification("连接成功", `发现 ${result.model_count} 个模型`, "success");
                                                    } else {
                                                      showNotification("连接失败", result.error || "未知错误", "danger");
                                                    }
                                                  } catch (e) {
                                                    setEditingForm({
                                                      ...editingForm,
                                                      testing: false,
                                                      testResult: { ok: false, error: e instanceof Error ? e.message : String(e), model_count: 0, models: [] },
                                                    });
                                                    showNotification("连接失败", e instanceof Error ? e.message : String(e), "danger");
                                                  }
                                                }}
                                              >{editingForm.testing ? "测试中..." : "测试连接"}</button>
                                            </div>
                                            <input
                                              className="ml-input"
                                              placeholder="提供方默认"
                                              value={editingForm.baseUrl}
                                              onChange={e => setEditingForm({ ...editingForm, baseUrl: e.target.value, testResult: null })}
                                            />
                                            {editingForm.testResult && (
                                              <div className={`ml-test-result ${editingForm.testResult.ok ? "ok" : "fail"}`}>
                                                {editingForm.testResult.ok
                                                  ? `✓ 连接成功 · 发现 ${editingForm.testResult.model_count} 个模型`
                                                  : `✗ ${editingForm.testResult.error}`}
                                              </div>
                                            )}
                                          </div>
                                        </div>
                                      )}
                                    </div>

                                    {/* 模型目录 */}
                                    <div className="ml-form-group">
                                      <div className="ml-section-header">
                                        <label className="ml-label">模型目录</label>
                                        <button
                                          className="btn btn-skip ml-fetch-btn"
                                          style={{ fontSize: 11, padding: "4px 12px" }}
                                          disabled={editingForm.fetching}
                                          onClick={async () => {
                                            if (!bridgeReady) {
                                              showNotification("演示模式", "连接核心后才能获取模型列表", "warning");
                                              return;
                                            }
                                            setEditingForm({ ...editingForm, fetching: true });
                                            try {
                                              const models = await listProviderModels(editingForm.providerId);
                                              setEditingForm({
                                                ...editingForm,
                                                fetchedModels: models.models || [],
                                                fetching: false,
                                              });
                                              showNotification("获取成功", `发现 ${models.models?.length || 0} 个模型`, "success");
                                            } catch {
                                              setEditingForm({ ...editingForm, fetching: false });
                                              showNotification("获取失败", "无法获取模型列表", "danger");
                                            }
                                          }}
                                        >{editingForm.fetching ? "获取中..." : "获取可用模型"}</button>
                                      </div>
                                      <div className="ml-model-status">
                                        {editingForm.fetchedModels.length > 0
                                          ? `已获取 ${editingForm.fetchedModels.length} 个模型`
                                          : "正在使用适配器默认模型"}
                                      </div>
                                      {editingForm.fetchedModels.length > 0 && (
                                        <div className="ml-model-list">
                                          {editingForm.fetchedModels.slice(0, 8).map((m: any, i: number) => (
                                            <div key={i} className="ml-model-item">
                                              <span className="ml-model-name">{m.id || m.name || `模型 ${i + 1}`}</span>
                                              <button
                                                className="btn btn-skip"
                                                style={{ fontSize: 10, padding: "2px 8px" }}
                                                disabled={!bridgeReady}
                                                onClick={async () => {
                                                  try {
                                                    const result = await setActiveModel(m.id || m.name);
                                                    if (result.ok) {
                                                      setActiveModelName(m.id || m.name);
                                                      showNotification("切换成功", `已切换到 ${m.id || m.name}`, "success");
                                                    } else {
                                                      showNotification("切换失败", result.message || "未知错误", "danger");
                                                    }
                                                  } catch (e) {
                                                    showNotification("切换失败", e instanceof Error ? e.message : String(e), "danger");
                                                  }
                                                }}
                                              >切换</button>
                                            </div>
                                          ))}
                                          {editingForm.fetchedModels.length > 8 && (
                                            <span className="ml-model-more">还有 {editingForm.fetchedModels.length - 8} 个模型...</span>
                                          )}
                                        </div>
                                      )}
                                      {editingForm.fetchedModels.length === 0 && (
                                        <div className="ml-model-hint">
                                          模型选择器中将不显示任何模型；目录外 ID 仍可直接发送。
                                        </div>
                                      )}
                                      {editingForm.addedModels.length > 0 && (
                                        <div className="ml-added-models">
                                          <span className="ml-added-label">已添加:</span>
                                          {editingForm.addedModels.map((m, i) => (
                                            <span key={i} className="ml-added-tag">{m}</span>
                                          ))}
                                        </div>
                                      )}
                                      <button
                                        className="btn btn-skip ml-add-model-btn"
                                        style={{ fontSize: 11, padding: "4px 12px" }}
                                        onClick={() => {
                                          const newModel = prompt("输入模型名称 (ID)", "");
                                          if (newModel && !editingForm.addedModels.includes(newModel)) {
                                            setEditingForm({
                                              ...editingForm,
                                              addedModels: [...editingForm.addedModels, newModel],
                                            });
                                          }
                                        }}
                                      >添加模型</button>
                                    </div>

                                    {/* 操作按钮 */}
                                    <div className="ml-edit-actions">
                                      <button
                                        className="btn btn-skip"
                                        onClick={() => {
                                          setEditingProviderId(null);
                                          setEditingForm(null);
                                        }}
                                      >取消</button>
                                      <button
                                        className="btn btn-skip"
                                        style={{ color: "#ef4444", borderColor: "rgba(239,68,68,0.4)" }}
                                        onClick={async () => {
                                          if (!bridgeReady) {
                                            showNotification("操作失败", "核心服务未连接", "danger");
                                            return;
                                          }
                                          const backendName = `${editingForm.providerId}-${editingForm.providerId}`;
                                          const result = await removeBackend(backendName);
                                          if (result.ok) {
                                            showNotification("移除成功", `后端 ${backendName} 已移除`, "success");
                                            const backends = await getModelsBackends();
                                            setModelHealth(backends);
                                          } else {
                                            showNotification("移除失败", result.error || "后端可能不存在", "warning");
                                          }
                                        }}
                                      >删除</button>
                                      <button
                                        className="btn btn-approve"
                                        onClick={async () => {
                                          try {
                                            const provider = catalog.find(p => p.id === editingForm.providerId);
                                            if (!provider) return;
                                            const envVar = provider.api_key_env || `API_KEY_${provider.id.toUpperCase()}`;
                                            if (editingForm.apiKey && editingForm.apiKey !== "********") {
                                              const result = await setApiKey(
                                                editingForm.providerId,
                                                envVar,
                                                editingForm.apiKey,
                                                editingForm.providerId
                                              );
                                              if (result.ok) {
                                                showNotification(
                                                  "保存成功",
                                                  `${provider.name} · ${result.masked_preview}`,
                                                  "success"
                                                );
                                                const keys = await listApiKeys();
                                                setApiKeys(keys.api_keys || {});
                                                apiKeyStorage.save(keys.api_keys || {});
                                              } else {
                                                showNotification("保存失败", result.error || "未知错误", "danger");
                                                return;
                                              }
                                            }
                                            if (bridgeReady) {
                                              try {
                                                const backendName = `${provider.id}-${Date.now().toString(36)}`;
                                                const addResult = await addBackend(
                                                  backendName,
                                                  provider.id,
                                                  provider.default_model || (editingForm.fetchedModels[0]?.id) || "",
                                                  editingForm.baseUrl || provider.base_url,
                                                  envVar
                                                );
                                                if (!addResult.ok) {
                                                  showNotification("后端注册警告", `API Key 已保存，但后端注册失败: ${addResult.error}`, "warning");
                                                }
                                              } catch (addErr) {
                                                showNotification("后端注册警告", `API Key 已保存，但后端注册异常: ${addErr instanceof Error ? addErr.message : String(addErr)}`, "warning");
                                              }
                                              const backends = await getModelsBackends();
                                              setModelHealth(backends);
                                            }
                                            setEditingProviderId(null);
                                            setEditingForm(null);
                                            loadModels();
                                          } catch (e) {
                                            showNotification("保存失败", e instanceof Error ? e.message : String(e), "danger");
                                          }
                                        }}
                                      >保存并启用</button>
                                    </div>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                                </div>
                              )}

                              {/* 云端测试结果面板 */}
                              {group.cloud && cloudTestSummary && (
                                <div className="ml-cloud-test">
                                  <div className={`ml-cloud-test-summary ${cloudTestSummary.failed === 0 ? "ok" : "fail"}`}>
                                    <span>
                                      {cloudTestSummary.ok
                                        ? `云端连通性：${cloudTestSummary.passed}/${cloudTestSummary.total} 可用`
                                        : "云端测试异常"}
                                    </span>
                                    {cloudTestSummary.error && <span className="ml-cloud-test-err">{cloudTestSummary.error}</span>}
                                  </div>
                                  {cloudTestSummary.results.length > 0 && (
                                    <div className="ml-cloud-test-list">
                                      {cloudTestSummary.results.map(r => (
                                        <div key={r.provider} className={`ml-cloud-test-row ${r.ok ? "ok" : "fail"}`}>
                                          <span className="ml-cloud-test-name">{r.ok ? "✓" : "✗"} {r.name}</span>
                                          <span className="ml-cloud-test-detail">
                                            {r.ok ? `可用 · ${r.model_count} 个模型` : (r.error || "不可用")}
                                          </span>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  );
                })()}

                {/* 自定义提供方表单 */}
                {showCustomProviderForm && (
                  <div className="ml-custom-form">
                    <div className="ml-custom-form-header">
                      <h3>添加自定义提供方</h3>
                      <button
                        className="btn btn-skip"
                        style={{ fontSize: 11, padding: "3px 10px" }}
                        onClick={() => setShowCustomProviderForm(false)}
                      >关闭</button>
                    </div>
                    <div className="ml-custom-form-body">
                      <div className="ml-form-group">
                        <label className="ml-label">后端类型</label>
                        <select
                          className="ml-input"
                          value={customProvider.backendType}
                          onChange={e => {
                            const providerInfo = catalog.find(c => c.id === e.target.value);
                            setCustomProvider({
                              ...customProvider,
                              backendType: e.target.value,
                              baseUrl: providerInfo?.base_url || "",
                              defaultModel: providerInfo?.default_model || "",
                            });
                          }}
                        >
                          <option value="">选择后端类型...</option>
                          {catalog.map(c => (
                            <option key={c.id} value={c.id}>{c.name} ({c.id})</option>
                          ))}
                        </select>
                      </div>
                      <div className="ml-form-group">
                        <label className="ml-label">实例名称</label>
                        <input
                          className="ml-input"
                          placeholder="唯一标识符，如: my-deepseek"
                          value={customProvider.name}
                          onChange={e => setCustomProvider({ ...customProvider, name: e.target.value })}
                        />
                      </div>
                      <div className="ml-form-group">
                        <label className="ml-label">API 地址</label>
                        <input
                          className="ml-input"
                          placeholder="https://api.example.com/v1"
                          value={customProvider.baseUrl}
                          onChange={e => setCustomProvider({ ...customProvider, baseUrl: e.target.value })}
                        />
                      </div>
                      <div className="ml-form-group">
                        <label className="ml-label">API 密钥</label>
                        <input
                          className="ml-input"
                          type="password"
                          placeholder="输入API密钥"
                          value={customProvider.apiKey}
                          onChange={e => setCustomProvider({ ...customProvider, apiKey: e.target.value })}
                        />
                      </div>
                      <div className="ml-form-group">
                        <label className="ml-label">默认模型</label>
                        <input
                          className="ml-input"
                          placeholder="如: deepseek-chat"
                          value={customProvider.defaultModel}
                          onChange={e => setCustomProvider({ ...customProvider, defaultModel: e.target.value })}
                        />
                      </div>
                      <div className="ml-edit-actions">
                        <button
                          className="btn btn-skip"
                          onClick={() => {
                            setShowCustomProviderForm(false);
                            setCustomProvider({ backendType: "", name: "", baseUrl: "", apiKey: "", defaultModel: "" });
                          }}
                        >取消</button>
                        <button
                          className="btn btn-approve"
                          disabled={!customProvider.backendType || !customProvider.name || !customProvider.defaultModel}
                          onClick={async () => {
                            try {
                              if (!bridgeReady) {
                                showNotification("操作失败", "核心服务未连接", "danger");
                                return;
                              }
                              const result = await addBackend(
                                customProvider.name,
                                customProvider.backendType,
                                customProvider.defaultModel,
                                customProvider.baseUrl,
                                customProvider.apiKey ? `API_KEY_${customProvider.backendType.toUpperCase()}` : ""
                              );
                              if (!result.ok) {
                                showNotification("添加失败", result.error || "未知错误", "danger");
                                return;
                              }
                              if (customProvider.apiKey) {
                                const keyResult = await setApiKey(
                                  customProvider.backendType,
                                  `API_KEY_${customProvider.backendType.toUpperCase()}`,
                                  customProvider.apiKey,
                                  customProvider.backendType
                                );
                                if (keyResult.ok) {
                                  const keys = await listApiKeys();
                                  setApiKeys(keys.api_keys || {});
                                  apiKeyStorage.save(keys.api_keys || {});
                                }
                              }
                              const backends = await getModelsBackends();
                              setModelHealth(backends);
                              const syntheticEntry: ProviderCatalogEntry = {
                                id: customProvider.name,
                                name: customProvider.name,
                                category: "cloud-native",
                                description: `自定义提供方 (${customProvider.backendType})`,
                                base_url: customProvider.baseUrl,
                                api_key_env: `API_KEY_${customProvider.backendType.toUpperCase()}`,
                                auth_type: "api_key",
                                website: "",
                                default_model: customProvider.defaultModel,
                                models: [],
                              };
                              setCatalog(prev => [...prev.filter(p => p.id !== customProvider.name), syntheticEntry]);
                              showNotification(
                                "添加成功",
                                `后端 ${result.name} 已注册，模型: ${result.model}`,
                                "success"
                              );
                              setShowCustomProviderForm(false);
                              setCustomProvider({ backendType: "", name: "", baseUrl: "", apiKey: "", defaultModel: "" });
                            } catch (e) {
                              showNotification("添加失败", e instanceof Error ? e.message : String(e), "danger");
                            }
                          }}
                        >保存并注册</button>
                      </div>
                    </div>
                  </div>
                )}
                  </>
                )}

                {/* ============ 语音引擎仪表盘（仅模型列表 Tab 显示） ============ */}
                {modelsTab === "list" && (
                <div className="models-section">
                  <div className="models-section-title">
                    <h3>🎙️ 语音引擎仪表盘</h3>
                    <button
                      className="btn btn-approve"
                      style={{ fontSize: 10, padding: "4px 12px" }}
                      onClick={async () => {
                        try {
                          const eng = await getVoiceEngines();
                          setVoiceEngines(eng);
                        } catch {}
                      }}
                    >刷新</button>
                  </div>
                  {voiceEngines ? (
                    <>
                      <div className="models-stats" style={{ marginBottom: 12 }}>
                        <div className="models-stat">
                          <div className="label">ASR 引擎</div>
                          <div className="value" style={{ color: "var(--accent)" }}>{voiceEngines.asr_count ?? 0}</div>
                        </div>
                        <div className="models-stat">
                          <div className="label">TTS 引擎</div>
                          <div className="value" style={{ color: "var(--accent3)" }}>{voiceEngines.tts_count ?? 0}</div>
                        </div>
                        <div className="models-stat">
                          <div className="label">引擎总数</div>
                          <div className="value" style={{ color: "var(--success)" }}>{voiceEngines.total_engines ?? 0}</div>
                        </div>
                      </div>
                      {voiceEngines.engines && voiceEngines.engines.length > 0 && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                          {voiceEngines.engines.map((eng: any, i: number) => (
                            <div key={i} className="models-table-row" style={{ gridTemplateColumns: "2fr 1fr 1fr" }}>
                              <span className="row-title">{eng.name || eng.id || "未知引擎"}</span>
                              <span style={{ color: "var(--muted2)" }}>{eng.type || eng.role || "N/A"}</span>
                              <span className={`models-badge ${eng.available ? "ok" : "bad"}`} style={{ justifySelf: "start" }}>
                                {eng.available ? "✓ 就绪" : "⚠ 不可用"}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="models-empty">
                      <div className="big">🎙️</div>
                      {bridgeReady ? "点击刷新加载引擎状态" : "演示模式：连接核心后显示语音引擎"}
                    </div>
                  )}
                </div>
                )}
              </div>
            </div>

            {/* ============ 10. 技能管理 (skills) ============ */}
            <div className={`screen ${nav === "skills" ? "active" : ""}`}>
              <div className="models-screen">
                <div className="models-header">
                  <div>
                    <h2>🎯 技能管理</h2>
                    <div className="sub">
                      {bridgeReady
                        ? "为艾薇配置专属技能：对话命中触发词时自动注入对应提示词"
                        : "演示模式 · 连接核心后显示技能列表"}
                    </div>
                  </div>
                  <button
                    className="btn btn-approve"
                    style={{ fontSize: 11, padding: "6px 14px" }}
                    onClick={() => {
                      setSkillForm({ id: null, name: "", description: "", category: "自定义", keywords: "", system_prompt: "", enabled: true });
                      setSkillFormOpen(true);
                    }}
                  >➕ 新建技能</button>
                </div>

                {/* 新建/编辑表单 */}
                {skillFormOpen && (
                  <div className="ml-edit-panel" style={{ marginBottom: 14 }}>
                    <div className="ml-form-group">
                      <label className="ml-label">技能名称 *</label>
                      <input
                        className="ml-input"
                        placeholder="如：邮件起草"
                        value={skillForm.name}
                        onChange={e => setSkillForm({ ...skillForm, name: e.target.value })}
                      />
                    </div>
                    <div className="ml-form-group">
                      <label className="ml-label">描述</label>
                      <input
                        className="ml-input"
                        placeholder="这个技能是做什么的？"
                        value={skillForm.description}
                        onChange={e => setSkillForm({ ...skillForm, description: e.target.value })}
                      />
                    </div>
                    <div className="ml-form-group">
                      <label className="ml-label">分类</label>
                      <input
                        className="ml-input"
                        placeholder="办公 / 开发 / 自动化 / 智能 / 自定义"
                        value={skillForm.category}
                        onChange={e => setSkillForm({ ...skillForm, category: e.target.value })}
                      />
                    </div>
                    <div className="ml-form-group">
                      <label className="ml-label">触发词（逗号分隔）</label>
                      <input
                        className="ml-input"
                        placeholder="邮件, 起草, email"
                        value={skillForm.keywords}
                        onChange={e => setSkillForm({ ...skillForm, keywords: e.target.value })}
                      />
                    </div>
                    <div className="ml-form-group">
                      <label className="ml-label">系统提示词（注入 LLM 上下文）</label>
                      <textarea
                        className="ml-input"
                        rows={4}
                        placeholder="你是邮件助手。处理邮件请求时：1) ..."
                        value={skillForm.system_prompt}
                        onChange={e => setSkillForm({ ...skillForm, system_prompt: e.target.value })}
                      />
                    </div>
                    <div className="ml-form-group" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <label className="ml-label" style={{ margin: 0 }}>启用</label>
                      <div className={`toggle ${skillForm.enabled ? "on" : ""}`} onClick={() => setSkillForm({ ...skillForm, enabled: !skillForm.enabled })}>
                        <div className="toggle-thumb" />
                      </div>
                    </div>
                    <div className="ml-edit-actions">
                      <button className="btn btn-skip" onClick={() => setSkillFormOpen(false)}>取消</button>
                      <button className="btn btn-approve" onClick={saveSkill}>保存技能</button>
                    </div>
                  </div>
                )}

                {skillsLoading ? (
                  <div className="models-empty"><div className="big">⏳</div>加载技能中...</div>
                ) : skills.length === 0 ? (
                  <div className="models-empty">
                    <div className="big">🎯</div>
                    {bridgeReady ? "暂无技能，点击「➕ 新建技能」创建" : "演示模式：连接核心后显示技能"}
                  </div>
                ) : (
                  <div className="ml-groups">
                    {(["办公", "开发", "自动化", "智能", "自定义"] as const).map(cat => {
                      const items = skills.filter(s => (s.category || "自定义") === cat);
                      if (items.length === 0) return null;
                      return (
                        <div key={cat} className="ml-group">
                          <div className="ml-group-header">
                            <span className="ml-group-title">{cat}</span>
                            <span className="ml-group-count">{items.length} 个</span>
                          </div>
                          <div className="ml-provider-list">
                            {items.map(s => (
                              <div key={s.id} className="ml-provider-item configured">
                                <div className="ml-provider-row">
                                  <div className="ml-provider-info">
                                    <span className="ml-status-dot" style={{ background: s.enabled ? "#10b981" : "#6b7280" }}></span>
                                    <span className="ml-provider-name">{s.name}</span>
                                    {s.builtin && <span className="ml-config-tag">内置</span>}
                                    <span className="ml-config-tag" style={{ background: s.enabled ? "rgba(16,185,129,0.12)" : "rgba(107,114,128,0.12)", color: s.enabled ? "#10b981" : "#8b93a7" }}>
                                      {s.enabled ? "已启用" : "已停用"}
                                    </span>
                                  </div>
                                  <div className="ml-provider-actions">
                                    <button
                                      className="btn btn-skip"
                                      style={{ fontSize: 10, padding: "3px 10px" }}
                                      onClick={() => {
                                        setSkillForm({
                                          id: s.id,
                                          name: s.name,
                                          description: s.description || "",
                                          category: s.category || "自定义",
                                          keywords: (s.keywords || []).join(", "),
                                          system_prompt: s.system_prompt || "",
                                          enabled: s.enabled,
                                        });
                                        setSkillFormOpen(true);
                                      }}
                                    >编辑</button>
                                    <button
                                      className="btn btn-skip"
                                      style={{ fontSize: 10, padding: "3px 10px" }}
                                      onClick={() => toggleSkill(s.id, !s.enabled)}
                                    >{s.enabled ? "停用" : "启用"}</button>
                                    {!s.builtin && (
                                      <button
                                        className="btn btn-skip"
                                        style={{ fontSize: 10, padding: "3px 10px", color: "#ef4444", borderColor: "rgba(239,68,68,0.4)" }}
                                        onClick={() => removeSkill(s.id, s.name)}
                                      >删除</button>
                                    )}
                                  </div>
                                </div>
                                <div style={{ padding: "0 16px 12px 16px", fontSize: 11, color: "var(--muted2)" }}>
                                  {s.description || "（无描述）"}
                                  {s.keywords && s.keywords.length > 0 && (
                                    <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                                      {s.keywords.map((k, i) => (
                                        <span key={i} className="ml-added-tag">{k}</span>
                                      ))}
                                    </div>
                                  )}
                                  {s.system_prompt && (
                                    <div style={{ marginTop: 6, padding: 8, borderRadius: 6, background: "rgba(255,255,255,0.03)", fontFamily: "monospace", fontSize: 10, whiteSpace: "pre-wrap" }}>
                                      {s.system_prompt}
                                    </div>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* ============ 11. 工具管理 (tools) ============ */}
            <div className={`screen ${nav === "tools" ? "active" : ""}`}>
              <div className="models-screen">
                <div className="models-header">
                  <div>
                    <h2>🔧 工具管理</h2>
                    <div className="sub">
                      {bridgeReady
                        ? `MCP 工具注册表 · ${managedTools.length} 个工具（权限级别 L0 只读 ~ L3 危险）`
                        : "演示模式 · 连接核心后显示工具列表"}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <select
                      className="ml-select"
                      value={toolFilter}
                      onChange={e => setToolFilter(e.target.value as any)}
                    >
                      <option value="all">全部</option>
                      <option value="enabled">已启用</option>
                      <option value="disabled">已停用</option>
                    </select>
                    <button className="btn btn-approve" style={{ fontSize: 11, padding: "6px 14px" }} onClick={loadTools}>刷新</button>
                  </div>
                </div>

                {toolsLoading ? (
                  <div className="models-empty"><div className="big">⏳</div>加载工具中...</div>
                ) : managedTools.length === 0 ? (
                  <div className="models-empty">
                    <div className="big">🔧</div>
                    {bridgeReady ? "暂无可用工具" : "演示模式：连接核心后显示工具"}
                  </div>
                ) : (
                  <div className="ml-groups">
                    {(() => {
                      const servers = Array.from(new Set(managedTools.map(t => t.server || "其他")));
                      return servers.map(srv => {
                        const items = managedTools.filter(t => (t.server || "其他") === srv).filter(t => {
                          if (toolFilter === "enabled") return t.enabled;
                          if (toolFilter === "disabled") return !t.enabled;
                          return true;
                        });
                        if (items.length === 0) return null;
                        return (
                          <div key={srv} className="ml-group">
                            <div className="ml-group-header">
                              <span className="ml-group-title">📦 {srv}</span>
                              <span className="ml-group-count">{items.length} 个</span>
                            </div>
                            <div className="ml-provider-list">
                              {items.map(t => (
                                <div key={t.name} className="ml-provider-item configured">
                                  <div className="ml-provider-row">
                                    <div className="ml-provider-info">
                                      <span className="ml-status-dot" style={{ background: t.enabled ? "#10b981" : "#6b7280" }}></span>
                                      <span className="ml-provider-name" style={{ fontFamily: "monospace" }}>{t.name}</span>
                                      <span className={`ml-cat-tag ${t.permission === "L0" ? "local" : "cloud"}`} style={{ fontSize: 9 }}>
                                        L{t.permission.replace("L", "")}
                                      </span>
                                      <span className="ml-config-tag" style={{ background: t.enabled ? "rgba(16,185,129,0.12)" : "rgba(107,114,128,0.12)", color: t.enabled ? "#10b981" : "#8b93a7" }}>
                                        {t.enabled ? "已启用" : "已停用"}
                                      </span>
                                    </div>
                                    <div className="ml-provider-actions">
                                      <button
                                        className="btn btn-skip"
                                        style={{ fontSize: 10, padding: "3px 10px" }}
                                        onClick={() => toggleTool(t.name, !t.enabled)}
                                      >{t.enabled ? "停用" : "启用"}</button>
                                    </div>
                                  </div>
                                  <div style={{ padding: "0 16px 12px 16px", fontSize: 11, color: "var(--muted2)" }}>
                                    {t.description}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      });
                    })()}
                  </div>
                )}
              </div>
            </div>

            {/* ============ 12. 设置 (settings) ============ */}
            <div className={`screen ${nav === "settings" ? "active" : ""}`}>
              <div className="settings-screen">
                <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>设置</div>
                <div style={{ fontSize: 12, color: "var(--muted2)", marginBottom: 16 }}>
                  {bridgeReady ? "核心已连接 · 所有功能可用" : "演示模式 · 核心未连接"}
                </div>
                <div className="settings-section-title">功能模块</div>
                <div className="feature-grid">
                  {featureCards.map(card => (
                    <div
                      key={card.id}
                      className="glass-card feature-card"
                      style={{ padding: 16, cursor: "pointer", opacity: bridgeReady ? 1 : 0.7 }}
                      onClick={() => handleNav(card.id)}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                        <div style={{
                          width: 38, height: 38, borderRadius: 10,
                          background: "rgba(59,130,246,0.15)",
                          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20,
                        }}>{card.icon}</div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 13, fontWeight: 600 }}>{card.label}</div>
                          <div style={{ fontSize: 10, color: "var(--muted2)" }}>{card.desc}</div>
                        </div>
                        <span style={{
                          fontSize: 9, padding: "2px 6px", borderRadius: 3,
                          color: bridgeReady ? "var(--success)" : "var(--warning)",
                          background: bridgeReady ? "rgba(16,185,129,0.12)" : "rgba(245,158,11,0.12)",
                        }}>{bridgeReady ? "已连接" : "演示模式"}</span>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="settings-section-title">外观主题</div>
                <div className="glass-card" style={{ padding: 16, marginBottom: 10 }}>
                  <div style={{ fontSize: 12, color: "var(--muted2)", marginBottom: 12 }}>选择适合你的主题方案，所有方案均通过 WCAG 2.1 AA 级可访问性标准</div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
                    {THEMES.map(t => (
                      <div
                        key={t.id}
                        className={`theme-card ${currentTheme === t.id ? "active" : ""}`}
                        onClick={() => applyTheme(t.id)}
                        style={{
                          padding: 12,
                          borderRadius: 10,
                          border: `1px solid ${currentTheme === t.id ? "var(--accent)" : "var(--glass-border)"}`,
                          background: currentTheme === t.id ? "var(--accent-light)" : "var(--glass-bg2)",
                          cursor: "pointer",
                          transition: "all 0.2s",
                          textAlign: "center",
                        }}
                      >
                        <div style={{ display: "flex", gap: 4, justifyContent: "center", marginBottom: 8 }}>
                          {t.colors.map((c, i) => (
                            <div key={i} style={{ width: 18, height: 18, borderRadius: 4, background: c, border: "1px solid rgba(255,255,255,0.15)" }} />
                          ))}
                        </div>
                        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>{t.name}</div>
                        <div style={{ fontSize: 10, color: "var(--muted2)" }}>{t.desc}</div>
                        {currentTheme === t.id && (
                          <div style={{ fontSize: 10, color: "var(--accent)", marginTop: 4, fontWeight: 600 }}>✓ 当前</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
                <div className="settings-section-title">系统</div>
                <div className="glass-card" style={{ padding: 14, marginBottom: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>开机自启动</div>
                      <div style={{ fontSize: 11, color: "var(--muted2)" }}>启动时自动运行 AivyOS</div>
                    </div>
                    <div className={`toggle ${vsetContinuous ? "on" : ""}`} onClick={() => setVsetContinuous(v => !v)}>
                      <div className="toggle-thumb" />
                    </div>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>连续对话模式</div>
                      <div style={{ fontSize: 11, color: "var(--muted2)" }}>关闭后每次对话需唤醒</div>
                    </div>
                    <div className={`toggle ${vsetContinuous ? "on" : ""}`} onClick={() => setVsetContinuous(v => !v)}>
                      <div className="toggle-thumb" />
                    </div>
                  </div>
                </div>
                <div className="glass-card" style={{ padding: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>连接状态</div>
                      <div style={{ fontSize: 11, color: "var(--muted2)" }}>
                        {bridgeReady ? `已连接 · ${status?.backend || "Python 核心"}` : "未连接 · 演示模式"}
                      </div>
                    </div>
                    <button className="btn btn-approve" style={{ fontSize: 11, padding: "4px 12px" }} onClick={() => { setBridgeReady(false); showNotification("重连中", "正在尝试重新连接核心...", "warning"); setTimeout(() => window.location.reload(), 500); }}>重连</button>
                  </div>
                </div>
              </div>
            </div>

          </div>

          {/* ---- Notifications ---- */}
          <div className="notif-stack">
            {notifs.map(n => (
              <div key={n.id} className={`notif-card ${n.type} ${n.removing ? "removing" : ""}`}>
                <div className="notif-title">{n.title}</div>
                <div className="notif-body">{n.body}</div>
              </div>
            ))}
          </div>

        </div>
      </div>
    </>
  );
}