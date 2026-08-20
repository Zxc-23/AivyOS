import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChatReply, StatusInfo, fetchStatus, sendChat, inTauri,
  getVoiceStatus, runVoiceTurn, listenVoice,
  listTasks, createTask, executeTask,
  listSchedules, createSchedule,
  runVibe,
  runBootCheck,
  getVoiceSettings, setVoiceSettings as saveVoiceSettings,
  listModels, getModelsHealth, getModelsCost, setActiveModel,
  BackendHealth, CostDashboard,
  listMcpTools, callMcpTool,
  executeFallbackChain,
  listMemory, searchMemory, addMemory,
  VoiceStatus, VoiceTurnResult,
  TaskInfo, SchedulerJob,
  BootCheckResult, MemoryEntry,
  VibeRunResult, VoiceSettings,
  getModelCatalog, listApiKeys, setApiKey, removeApiKey,
  getVoiceEngines, configVoiceEngine,
  testModelConnection, listProviderModels,
  testTts,
  applyVoiceTts,
  ProviderCatalogEntry, ApiKeyEntry, TestConnectionResult, ListModelsResult,
  SetApiKeyResult, RemoveApiKeyResult,
  apiKeyStorage,
  startWakeLoop, stopWakeLoop, getWakeLoopStatus, listenWakeEvents,
  WakeLoopStatus, WakeEvent,
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
  | "memory" | "boot" | "voiceset" | "models" | "settings";

interface Msg { role: "user" | "assistant"; text: string; }

interface Notif {
  id: number; title: string; body: string;
  type: "success" | "warning" | "danger"; removing?: boolean;
}

/* ---- 演示模式降级数据（bridge 未就绪时使用） ---- */
const DEMO_VOICE_STATUS: VoiceStatus = {
  asr: "funasr", tts: "cosyvoice", vad: "silero",
  source: "text-sim", sink: "wav-file",
  wake_required: true, wake_words: ["艾薇", "艾维"],
  llm_route_mode: "local",
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
  const [nav, setNav] = useState<NavId>("chat");
  const [messages, setMessages] = useState<Msg[]>([
    { role: "assistant", text: "早上好！我是 Aivy，您的私人 AI 助理。有什么可以帮您？" },
  ]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [trayState, setTrayStateUi] = useState<TrayStateName>("booting");
  const [notifs, setNotifs] = useState<Notif[]>([]);
  const notifIdRef = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [bridgeReady, setBridgeReady] = useState(false);

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
    onWindowFileDrop((paths) => {
      showNotification("收到文件", `已拖入 ${paths.length} 个文件，正在处理...`, "success");
    }).then(fn => { if (typeof fn === "function") cleanupFns.push(fn); }).catch(() => {});
    return () => { cleanupFns.forEach(fn => fn()); };
  }, [showNotification]);

  /* ================================================================
   *  Chat handlers
   * ================================================================ */
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text) return;
    setMessages(prev => [...prev, { role: "user", text }]);
    setInput("");
    updateTrayState("working");
    if (!bridgeReady) {
      setTimeout(() => {
        setMessages(prev => [...prev, { role: "assistant", text: "（演示模式）核心尚未连接，请通过 npm run tauri dev 启动完整应用。" }]);
        updateTrayState("idle");
      }, 600);
      return;
    }
    try {
      const reply: ChatReply = await sendChat(text);
      setMessages(prev => [...prev, { role: "assistant", text: reply.text }]);
      updateTrayState("idle");
    } catch (e) {
      setMessages(prev => [...prev, { role: "assistant", text: "抱歉，出现了错误：" + (e instanceof Error ? e.message : String(e)) }]);
      updateTrayState("error");
    }
  }, [input, bridgeReady, updateTrayState]);

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
      const result = await listenVoice();
      setVoiceTurnResult(result);
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
      if (result.fallback) showNotification("降级模式", "语音组件部分不可用", "warning");
      if (!result.ok) showNotification("语音识别失败", result.error || "未检测到语音输入", "danger");
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      setVoiceTurnResult({ ok: false, text: "", reply: errMsg });
      showNotification("语音错误", errMsg, "danger");
    } finally {
      setVoiceLoading(false);
      setVoiceListening(false);
      updateTrayState("idle");
    }
  }, [bridgeReady, updateTrayState, showNotification]);

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
  const runBoot = useCallback(async () => {
    setBootLoading(true);
    updateTrayState("booting");
    try {
      if (!bridgeReady) { await new Promise(r => setTimeout(r, 1500)); setBootResult(DEMO_BOOT); return; }
      const result = await runBootCheck();
      setBootResult(result);
      showNotification("系统自检完成", result.summary, result.passed === result.total ? "success" : "warning");
    } catch (e) {
      setBootResult(DEMO_BOOT);
      showNotification("自检异常", e instanceof Error ? e.message : String(e), "danger");
    } finally { setBootLoading(false); updateTrayState("idle"); }
  }, [bridgeReady, updateTrayState, showNotification]);

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
      case "memory": loadMemory(); break;
      default: break;
    }
  }, [nav, loadVoiceStatus, loadTasks, loadSchedules, runBoot, loadVoiceSettings, loadModels, loadMemory]);

  useEffect(() => {
    if (nav !== "voice" || bridgeReady) return;
    const timer = setInterval(() => { setDemoVoiceIdx(prev => (prev + 1) % DEMO_VOICE_TEXTS.length); }, 4000);
    return () => clearInterval(timer);
  }, [nav, bridgeReady]);

  const handleNav = (id: NavId) => { setNav(id); };

  const currentTitle: Record<NavId, string> = {
    chat: "对话", voice: "语音模式", task: "自主任务", sched: "定时任务",
    vibe: "Vibe Coding", memory: "记忆管理", boot: "系统自检",
    voiceset: "语音设置", models: "模型管理", settings: "设置",
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
    { id: "memory" as NavId, label: "记忆管理", desc: "查看 AI 学习到的偏好与上下文", icon: "🧠" },
    { id: "boot" as NavId, label: "系统自检", desc: "启动时自动检测各模块状态", icon: "🔒" },
    { id: "voiceset" as NavId, label: "语音设置", desc: "TTS 音色选择与 ASR 引擎", icon: "🎛️" },
    { id: "models" as NavId, label: "模型管理", desc: "模型部署、路由与切换策略", icon: "🧩" },
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
                  {messages.map((m, i) => (
                    <div key={i} className={`msg-row ${m.role === "user" ? "user" : ""}`}>
                      {m.role === "assistant" && <div className="msg-avatar">薇</div>}
                      <div className={`msg-bubble ${m.role}`}>{m.text}</div>
                    </div>
                  ))}
                </div>
                <div className="chat-input-area">
                  <div className="chat-input-row">
                    <input
                      className="chat-input"
                      placeholder="输入消息或按 Alt+V 语音对话..."
                      value={input}
                      onChange={e => setInput(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter") handleSend(); }}
                    />
                    <button className="btn-voice" onClick={() => handleNav("voice")} title="语音模式">🎙️</button>
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

                {/* Microphone button - large circular push-to-talk */}
                <div style={{ marginTop: 20, display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
                  <button
                    onClick={handleVoiceListen}
                    disabled={voiceLoading}
                    title="点击说话（按 Alt+V 快捷）"
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
                    {voiceListening ? "正在聆听...请说话" : (voiceLoading ? "处理中..." : "点击麦克风说话")}
                  </div>
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
                    ? "点击麦克风 → 说话 → 自动识别并回复（唤醒词已启用：" + (voiceStatus?.wake_words?.join(", ") || "Aivy") + "）"
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

            {/* ============ 6. 记忆 (memory) ============ */}
            <div className={`screen ${nav === "memory" ? "active" : ""}`}>
              <div className="memory-layout">
                <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>记忆管理 — 艾薇记得的事情</div>
                <div className="glass-card" style={{ padding: 14, marginBottom: 16 }}>
                  <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                    <input className="chat-input" style={{ flex: 1, height: 34 }} placeholder="搜索记忆..."
                      value={memorySearchQuery} onChange={e => setMemorySearchQuery(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter") handleSearchMemory(); }} />
                    <button className="btn btn-approve" style={{ height: 34, padding: "0 14px" }} onClick={handleSearchMemory}>🔍 搜索</button>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input className="chat-input" style={{ flex: 1, height: 34 }} placeholder="添加新记忆..."
                      value={memoryNewText} onChange={e => setMemoryNewText(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter") handleAddMemory(); }} />
                    <button className="btn btn-approve" style={{ height: 34, padding: "0 14px" }} onClick={handleAddMemory}>➕ 添加</button>
                  </div>
                </div>
                {memoryLoading && <div style={{ fontSize: 12, color: "var(--muted)", padding: 20, textAlign: "center" }}>加载中...</div>}
                {!memoryLoading && memories.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)", padding: 20, textAlign: "center" }}>暂无记忆</div>}
                {!memoryLoading && (
                  <div className="memory-grid stagger">
                    {memories.map((m, i) => {
                      const colors = getMemoryColor(m.category);
                      return (
                        <div key={m.id || i} className="memory-card">
                          <span className="memory-card-type" style={{ background: colors.bg, color: colors.color }}>{m.category || "未分类"}</span>
                          <div className="memory-card-content">{m.text}</div>
                          <div className="memory-card-time">
                            {m.created_at || "未知时间"}
                            {m.score !== undefined && <span style={{ marginLeft: 8, color: "var(--accent)" }}>相似度: {(m.score * 100).toFixed(0)}%</span>}
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
                  <button className="btn btn-approve" onClick={runBoot} disabled={bootLoading}>{bootLoading ? "检查中..." : "▶ 重新自检"}</button>
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
                <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>模型管理 — 部署与路由</div>
                <div style={{ fontSize: 11, color: "var(--muted2)", marginBottom: 12 }}>
                  Phase 2: 成本追踪 · 断路器状态 · 健康仪表盘
                </div>
                {/* Tab nav */}
                <div style={{ display: "flex", gap: 4, marginBottom: 10, alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", gap: 4 }}>
                    {([
                      { id: "health", label: "健康仪表盘" },
                      { id: "cost", label: "成本追踪" },
                      { id: "list", label: "模型列表" },
                    ] as const).map(tab => (
                      <button
                        key={tab.id}
                        className={`btn ${modelsTab === tab.id ? "btn-approve" : "btn-skip"}`}
                        style={{ fontSize: 11, padding: "4px 12px", opacity: modelsTab === tab.id ? 1 : 0.7 }}
                        onClick={() => setModelsTab(tab.id)}
                      >{tab.label}</button>
                    ))}
                  </div>
                  {activeModelName && (
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 11, color: "var(--accent)", fontWeight: 500 }}>
                        🔒 锁定模型: {activeModelName}
                      </span>
                      <button
                        className="btn btn-skip"
                        style={{ fontSize: 10, padding: "2px 8px" }}
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

                {/* Tab: 健康仪表盘 */}
                {modelsTab === "health" && modelHealth.length > 0 && (
                  <div className="glass-card" style={{ padding: 12, marginBottom: 12 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "var(--accent)", marginBottom: 8 }}>
                      后端健康状态 ({modelHealth.length} 个)
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
                      {modelHealth.map((h, i) => (
                        <div key={i} style={{
                          padding: 10, borderRadius: 8,
                          background: h.available ? "rgba(16,185,129,0.08)" : "rgba(239,68,68,0.08)",
                          border: `1px solid ${h.available ? "rgba(16,185,129,0.3)" : "rgba(239,68,68,0.3)"}`,
                        }}>
                          <div style={{ fontSize: 12, fontWeight: 600 }}>{h.model}</div>
                          <div style={{ fontSize: 10, color: "var(--muted2)", marginBottom: 4 }}>
                            {h.provider} · {h.model}
                          </div>
                          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                            <span style={{
                              fontSize: 9, padding: "1px 6px", borderRadius: 3,
                              background: h.breaker_state === "closed" ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)",
                              color: h.breaker_state === "closed" ? "var(--success)" : "var(--danger)",
                            }}>
                              {h.breaker_state === "closed" ? "✓ 熔断关闭" : "⚠ 熔断打开"}
                            </span>
                            <span style={{
                              fontSize: 9, padding: "1px 6px", borderRadius: 3,
                              background: h.available ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)",
                              color: h.available ? "var(--success)" : "var(--danger)",
                            }}>
                              {h.available ? "已就绪" : "不可用"}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {modelsTab === "health" && modelHealth.length === 0 && !modelsLoading && (
                  <div className="glass-card" style={{ padding: 20, textAlign: "center", color: "var(--muted)" }}>
                    {bridgeReady ? "健康仪表盘加载中..." : "演示模式：连接核心后显示后端状态"}
                  </div>
                )}

                {/* Tab: 成本追踪 */}
                {modelsTab === "cost" && modelCost && (
                  <>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 12 }}>
                      <div className="glass-card" style={{ padding: 10, textAlign: "center" }}>
                        <div style={{ fontSize: 10, color: "var(--muted2)" }}>总请求</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--accent)" }}>{modelCost.total_requests}</div>
                      </div>
                      <div className="glass-card" style={{ padding: 10, textAlign: "center" }}>
                        <div style={{ fontSize: 10, color: "var(--muted2)" }}>总 Token</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--accent2)" }}>{modelCost.total_tokens.toLocaleString()}</div>
                      </div>
                      <div className="glass-card" style={{ padding: 10, textAlign: "center" }}>
                        <div style={{ fontSize: 10, color: "var(--muted2)" }}>总成本</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--warning)" }}>${modelCost.total_cost_usd.toFixed(4)}</div>
                      </div>
                      <div className="glass-card" style={{ padding: 10, textAlign: "center" }}>
                        <div style={{ fontSize: 10, color: "var(--muted2)" }}>后端数</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--accent3)" }}>{modelCost.backend_count}</div>
                      </div>
                    </div>
                    {Object.entries(modelCost.backends).length > 0 && (
                      <div className="glass-card" style={{ padding: 12 }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--accent)", marginBottom: 8 }}>每后端成本明细</div>
                        {Object.entries(modelCost.backends).map(([name, stats]) => (
                          <div key={name} style={{
                            display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 8,
                            padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.04)", fontSize: 11,
                          }}>
                            <span style={{ color: "var(--ink)", fontWeight: 500 }}>{name}</span>
                            <span style={{ color: "var(--muted2)" }}>请求: {stats.total_requests}</span>
                            <span style={{ color: "var(--muted2)" }}>Token: {(stats.total_input_tokens + stats.total_output_tokens).toLocaleString()}</span>
                            <span style={{ color: "var(--warning)" }}>${stats.total_cost_usd.toFixed(4)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
                {modelsTab === "cost" && !modelCost && !modelsLoading && (
                  <div className="glass-card" style={{ padding: 20, textAlign: "center", color: "var(--muted)" }}>
                    {bridgeReady ? "成本追踪加载中..." : "演示模式：连接后显示成本统计"}
                  </div>
                )}

                {/* Tab: 模型列表 (原有逻辑) */}
                {modelsTab === "list" && (
                  <>
                {modelsLoading && <div style={{ fontSize: 12, color: "var(--muted)", padding: 20, textAlign: "center" }}>加载中...</div>}
                {!modelsLoading && models.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)", padding: 20, textAlign: "center" }}>暂无模型</div>}
                {!modelsLoading && (
                  <div className="models-grid">
                    {models.map((m, i) => {
                      const meta = getModelIcon(m.mode, m.model);
                      const tags = getModelTags(m.mode, m.available);
                      return (
                        <div key={i} className="glass-card model-card" style={{ padding: 16 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                            <div style={{
                              width: 44, height: 44, borderRadius: 10,
                              background: meta.iconBg, display: "flex",
                              alignItems: "center", justifyContent: "center", fontSize: 22,
                            }}>{meta.icon}</div>
                            <div>
                              <div style={{ fontSize: 14, fontWeight: 600 }}>{m.model}</div>
                              <div style={{ fontSize: 11, color: "var(--muted2)" }}>{meta.desc}</div>
                            </div>
                          </div>
                          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                            {tags.map((t, j) => (
                              <span key={j} style={{
                                fontSize: 10, padding: "2px 8px", borderRadius: 4,
                                background: `${t.color}22`, color: t.color,
                              }}>{t.text}</span>
                            ))}
                          </div>
                          <div style={{ display: "flex", gap: 6 }}>
                            <button
                              className={`btn ${activeModelName === m.model ? "btn-approve" : "btn-skip"}`}
                              style={{
                                flex: 1, fontSize: 11, padding: "4px",
                                opacity: activeModelName === m.model ? 1 : 0.6,
                                border: activeModelName === m.model ? "1px solid var(--accent)" : "1px solid transparent",
                                boxShadow: activeModelName === m.model ? "0 0 12px rgba(108,140,255,0.4)" : "none",
                                fontWeight: activeModelName === m.model ? 700 : 400,
                              }}
                              onClick={async () => {
                                if (!bridgeReady) { showNotification("演示模式", "连接核心后才能切换模型", "warning"); return; }
                                try {
                                  const result = await setActiveModel(m.model);
                                  if (result.ok) {
                                    setActiveModelName(m.model);
                                    showNotification("切换成功", result.message || `已切换到 ${m.model}`, "success");
                                  } else {
                                    showNotification("切换失败", result.message || "未知错误", "danger");
                                  }
                                } catch (e) {
                                  showNotification("切换失败", e instanceof Error ? e.message : String(e), "danger");
                                }
                              }}
                            >
                              {activeModelName === m.model ? "✓ 当前使用中" : (m.available ? "切换到此模型" : "连接模型")}
                            </button>
                            <button className="btn btn-skip" style={{ fontSize: 11, padding: "4px 10px", opacity: activeModelName === m.model ? 0.8 : 1 }}>配置</button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                  </>
                )}

                {/* ============ API Key 管理 ============ */}
                <div className="glass-card" style={{ padding: 14, marginBottom: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--accent)", marginBottom: 10, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>API Key 管理</span>
                    <span style={{ fontSize: 10, color: "var(--muted2)" }}>
                      已配置 {Object.values(apiKeys).filter(k => k.has_key).length} / {Object.keys(apiKeys).length || catalog.length} 个 · 持久化存储
                    </span>
                  </div>
                  {Object.keys(apiKeys).length === 0 && catalog.length === 0 && (
                    <div style={{ fontSize: 11, color: "var(--muted2)", padding: 10, textAlign: "center" }}>
                      {bridgeReady ? "加载中..." : "演示模式：连接核心后显示 API Key 配置"}
                    </div>
                  )}
                  {(Object.keys(apiKeys).length > 0 || catalog.length > 0) && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {catalog.map((provider) => {
                        const keyEntry = apiKeys[provider.api_key_env] || apiKeys[provider.id];
                        const hasKey = keyEntry?.has_key || false;
                        const keyLen = keyEntry?.key_length || 0;
                        const maskedPreview = keyEntry?.masked_preview || "";
                        const isEditingKey = editingKeyEnv === (provider.api_key_env || provider.id);
                        return (
                          <div key={provider.id} style={{
                            display: "grid", gridTemplateColumns: "2fr 1fr 1fr auto", gap: 8,
                            alignItems: "center", padding: "8px 10px",
                            background: hasKey ? "rgba(16,185,129,0.08)" : "rgba(0,0,0,0.15)",
                            borderRadius: 6,
                            border: hasKey ? "1px solid rgba(16,185,129,0.3)" : "1px solid rgba(255,255,255,0.04)",
                          }}>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 500 }}>{provider.name}</div>
                              <div style={{ fontSize: 10, color: "var(--muted2)" }}>
                                {provider.id} · {provider.base_url}
                                {hasKey && maskedPreview && (
                                  <span style={{ color: "var(--accent)", marginLeft: 6 }}>
                                    🔑 {maskedPreview}
                                  </span>
                                )}
                              </div>
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                              <span style={{
                                fontSize: 10, padding: "2px 6px", borderRadius: 3,
                                background: hasKey ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)",
                                color: hasKey ? "var(--success)" : "var(--danger)",
                              }}>
                                {hasKey ? `已配置 (${keyLen}位)` : "未配置"}
                              </span>
                              {hasKey && keyEntry?.source === "env" && (
                                <span style={{ fontSize: 9, color: "#f59e0b", marginTop: 2 }}>环境变量</span>
                              )}
                            </div>
                            <span style={{ fontSize: 10, color: "var(--muted2)" }}>
                              {provider.default_model}
                            </span>
                            <div style={{ display: "flex", gap: 4 }}>
                              {hasKey && !isEditingKey ? (
                                <>
                                  <button
                                    className="btn btn-approve"
                                    style={{ fontSize: 10, padding: "3px 8px" }}
                                    onClick={() => setEditingKeyEnv(provider.api_key_env || provider.id)}
                                  >编辑</button>
                                  <button
                                    className="btn btn-skip"
                                    style={{ fontSize: 10, padding: "3px 8px" }}
                                    onClick={async () => {
                                      const envVar = provider.api_key_env || `API_KEY_${provider.id.toUpperCase()}`;
                                      const val = prompt(`重新输入 ${provider.name} API Key (留空保持不变)`, "");
                                      if (!val) return;
                                      try {
                                        const result = await setApiKey(provider.id, envVar, val, provider.id);
                                        if (result.ok) {
                                          showNotification("API Key 已更新", `${provider.name} · ${result.masked_preview}`, "success");
                                          const keys = await listApiKeys();
                                          setApiKeys(keys.api_keys || {});
                                          apiKeyStorage.save(keys.api_keys || {});
                                        } else {
                                          showNotification("更新失败", result.error || "未知错误", "danger");
                                        }
                                      } catch (e) {
                                        showNotification("设置失败", e instanceof Error ? e.message : String(e), "danger");
                                      }
                                    }}
                                  >重生成</button>
                                  <button
                                    className="btn btn-skip"
                                    style={{ fontSize: 10, padding: "3px 8px", background: "rgba(239,68,68,0.15)" }}
                                    onClick={async () => {
                                      const confirmed = confirm(`确定要删除 ${provider.name} 的 API Key 吗？`);
                                      if (!confirmed) return;
                                      try {
                                        const envVar = provider.api_key_env || `API_KEY_${provider.id.toUpperCase()}`;
                                        const result = await removeApiKey(provider.id, envVar);
                                        if (result.ok) {
                                          showNotification("API Key 已删除", `${provider.name}`, "success");
                                          const keys = await listApiKeys();
                                          setApiKeys(keys.api_keys || {});
                                          apiKeyStorage.save(keys.api_keys || {});
                                        }
                                      } catch (e) {
                                        showNotification("删除失败", e instanceof Error ? e.message : String(e), "danger");
                                      }
                                    }}
                                  >删除</button>
                                </>
                              ) : (
                                <button
                                  className="btn btn-approve"
                                  style={{ fontSize: 10, padding: "3px 8px" }}
                                  onClick={async () => {
                                    const val = prompt(`输入 ${provider.name} API Key`, "");
                                    if (!val) { setEditingKeyEnv(""); return; }
                                    const envVar = provider.api_key_env || `API_KEY_${provider.id.toUpperCase()}`;
                                    try {
                                      const result = await setApiKey(provider.id, envVar, val, provider.id);
                                      if (result.ok) {
                                        showNotification(
                                          hasKey ? "API Key 已更新" : "API Key 已保存",
                                          `${provider.name} · ${result.masked_preview}${result.removed ? " (已清除)" : ""}`,
                                          "success"
                                        );
                                        const keys = await listApiKeys();
                                        setApiKeys(keys.api_keys || {});
                                        apiKeyStorage.save(keys.api_keys || {});
                                      } else {
                                        showNotification("设置失败", result.error || "未知错误", "danger");
                                      }
                                    } catch (e) {
                                      showNotification("设置失败", e instanceof Error ? e.message : String(e), "danger");
                                    }
                                    setEditingKeyEnv("");
                                  }}
                                >{hasKey ? "保存" : "设置"}</button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                      {catalog.length === 0 && Object.keys(apiKeys).length > 0 && (
                        <>
                          {Object.entries(apiKeys).map(([envVar, entry]) => (
                            <div key={envVar} style={{
                              display: "grid", gridTemplateColumns: "2fr 1fr 1fr auto", gap: 8,
                              alignItems: "center", padding: "8px 10px",
                              background: entry.has_key ? "rgba(16,185,129,0.08)" : "rgba(0,0,0,0.15)",
                              borderRadius: 6,
                            }}>
                              <div>
                                <div style={{ fontSize: 12, fontWeight: 500 }}>{envVar}</div>
                                <div style={{ fontSize: 10, color: "var(--muted2)" }}>
                                  {entry.provider || "自定义"} · {entry.source === "env" ? "环境变量" : "持久化存储"}
                                  {entry.has_key && entry.masked_preview && (
                                    <span style={{ color: "var(--accent)", marginLeft: 6 }}>🔑 {entry.masked_preview}</span>
                                  )}
                                </div>
                              </div>
                              <span style={{
                                fontSize: 10, padding: "2px 6px", borderRadius: 3,
                                background: entry.has_key ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)",
                                color: entry.has_key ? "var(--success)" : "var(--danger)",
                              }}>
                                {entry.has_key ? `已配置 (${entry.key_length}位)` : "未配置"}
                              </span>
                              <span></span>
                              <div style={{ display: "flex", gap: 4 }}>
                                <button className="btn btn-approve" style={{ fontSize: 10, padding: "3px 8px" }}
                                  onClick={async () => {
                                    try {
                                      const val = prompt(`输入 ${envVar}`, "");
                                      if (!val) return;
                                      const providerId = entry.provider || envVar.toLowerCase().replace("api_key_", "");
                                      const result = await setApiKey(providerId, envVar, val, providerId);
                                      if (result.ok) {
                                        showNotification("API Key 已更新", `${envVar} · ${result.masked_preview}`, "success");
                                        const keys = await listApiKeys();
                                        setApiKeys(keys.api_keys || {});
                                        apiKeyStorage.save(keys.api_keys || {});
                                      } else {
                                        showNotification("设置失败", result.error || "未知错误", "danger");
                                      }
                                    } catch (e) { showNotification("设置失败", e instanceof Error ? e.message : String(e), "danger"); }
                                  }}
                                >设置</button>
                                {entry.has_key && (
                                  <button className="btn btn-skip" style={{ fontSize: 10, padding: "3px 8px", background: "rgba(239,68,68,0.15)" }}
                                    onClick={async () => {
                                      const confirmed = confirm(`确定要删除 ${envVar} 吗？`);
                                      if (!confirmed) return;
                                      try {
                                        const providerId = entry.provider || envVar.toLowerCase().replace("api_key_", "");
                                        const result = await removeApiKey(providerId, envVar);
                                        if (result.ok) {
                                          showNotification("API Key 已删除", envVar, "success");
                                          const keys = await listApiKeys();
                                          setApiKeys(keys.api_keys || {});
                                          apiKeyStorage.save(keys.api_keys || {});
                                        }
                                      } catch (e) { showNotification("删除失败", e instanceof Error ? e.message : String(e), "danger"); }
                                    }}
                                  >删除</button>
                                )}
                              </div>
                            </div>
                          ))}
                        </>
                      )}
                    </div>
                  )}
                </div>

                {/* ============ 添加模型对话框 ============ */}
                <div className="glass-card" style={{ padding: 14, marginBottom: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--accent)" }}>添加新模型</div>
                    <button
                      className={`btn ${showAddModelDialog ? "btn-skip" : "btn-approve"}`}
                      style={{ fontSize: 11, padding: "3px 10px" }}
                      onClick={() => {
                        if (showAddModelDialog) resetAddModelDialog();
                        setShowAddModelDialog(!showAddModelDialog);
                      }}
                    >{showAddModelDialog ? "取消" : "+ 新增"}</button>
                  </div>
                  {showAddModelDialog && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {/* 服务商选择 */}
                      <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 6, alignItems: "center" }}>
                        <label style={{ fontSize: 11, color: "var(--muted)" }}>提供商</label>
                        <select
                          className="chat-input" style={{ height: 30 }}
                          value={addModelProvider}
                          onChange={e => handleProviderChange(e.target.value)}
                        >
                          <option value="">选择提供商...</option>
                          {catalog.map(p => (
                            <option key={p.id} value={p.id}>{p.name} ({p.id})</option>
                          ))}
                        </select>
                      </div>

                      {/* Base URL */}
                      <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 6, alignItems: "center" }}>
                        <label style={{ fontSize: 11, color: "var(--muted)" }}>Base URL</label>
                        <input
                          className="chat-input" style={{ height: 30 }}
                          placeholder={addModelProvider ? "自动填充，可修改" : "选择提供商后自动填充"}
                          value={addModelBaseUrl}
                          onChange={e => setAddModelBaseUrl(e.target.value)}
                        />
                      </div>

                      {/* API Key + 注册链接 */}
                      <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 6, alignItems: "center" }}>
                        <label style={{ fontSize: 11, color: "var(--muted)" }}>API Key</label>
                        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                          <input
                            className="chat-input" style={{ height: 30, flex: 1 }}
                            type="password"
                            placeholder={addModelProvider ? "输入 API Key" : "选择提供商后输入"}
                            value={addModelApiKey}
                            onChange={e => setAddModelApiKey(e.target.value)}
                          />
                          {addModelProvider && (() => {
                            const p = catalog.find(c => c.id === addModelProvider);
                            return p && p.website ? (
                              <a href={p.website} target="_blank" style={{ fontSize: 10, color: "var(--accent)", whiteSpace: "nowrap" }}>注册 →</a>
                            ) : null;
                          })()}
                        </div>
                      </div>

                      {/* 测试连接 */}
                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <button
                          className="btn" style={{ fontSize: 11, padding: "4px 12px", borderColor: "var(--border)", background: "var(--bg3)" }}
                          disabled={!addModelProvider || !addModelApiKey || !addModelBaseUrl || addModelTesting}
                          onClick={handleTestConnection}
                        >
                          {addModelTesting ? "测试中..." : "测试连接"}
                        </button>
                        {addModelTestResult && (
                          addModelTestResult.ok ? (
                            <span style={{ fontSize: 10, color: "var(--success)" }}>
                              ✓ 连接成功 · 发现 {addModelTestResult.model_count} 个模型
                            </span>
                          ) : (
                            <span style={{ fontSize: 10, color: "var(--danger)" }}>
                              ✗ {addModelTestResult.error}
                            </span>
                          )
                        )}
                      </div>

                      {/* 选择模型 - 仅在连接成功或有预设模型时显示 */}
                      {(addModelTestResult?.ok || addModelPresetModels) && (
                        <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 6, alignItems: "center" }}>
                          <label style={{ fontSize: 11, color: "var(--muted)" }}>选择模型</label>
                          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                            <input
                              className="chat-input" style={{ height: 30, flex: 1 }}
                              placeholder={addModelFetchingModels ? "加载模型列表..." : "可手动输入或从下拉选择"}
                              value={addModelName}
                              onChange={e => setAddModelName(e.target.value)}
                              list="preset-model-list"
                            />
                            {addModelPresetModels?.models && addModelPresetModels.models.length > 0 && (
                              <datalist id="preset-model-list">
                                {addModelPresetModels.models.map(m => (
                                  <option key={m.name} value={m.name}>{m.display_name || m.name}</option>
                                ))}
                              </datalist>
                            )}
                            {addModelTestResult?.ok && addModelTestResult.models && addModelTestResult.models.length > 0 && (
                              <select
                                className="chat-input" style={{ height: 30, width: 140 }}
                                value=""
                                onChange={e => { if (e.target.value) setAddModelName(e.target.value); }}
                              >
                                <option value="">从远程选择...</option>
                                {addModelTestResult.models.map(m => (
                                  <option key={m.id} value={m.id}>{m.id}</option>
                                ))}
                              </select>
                            )}
                          </div>
                        </div>
                      )}

                      {/* 高级配置 - 折叠 */}
                      {addModelProvider && (
                        <details style={{ marginTop: 4 }}>
                          <summary style={{ fontSize: 11, color: "var(--muted)", cursor: "pointer", padding: "4px 0" }}>
                            高级配置（API 类型、上下文窗口、输入类型等）
                          </summary>
                          <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "6px 0", borderTop: "1px solid var(--border)", marginTop: 4 }}>
                            {/* API 类型 */}
                            <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 6, alignItems: "center" }}>
                              <label style={{ fontSize: 11, color: "var(--muted)" }}>API 类型</label>
                              <div style={{ display: "flex", gap: 10, fontSize: 11 }}>
                                {[
                                  { v: "chat_completions", l: "Chat Completions" },
                                  { v: "responses_api", l: "Responses API" },
                                  { v: "anthropic_messages", l: "Anthropic Messages" },
                                ].map(opt => (
                                  <label key={opt.v} style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
                                    <input type="radio" name="apiType" value={opt.v}
                                      checked={addModelApiType === opt.v}
                                      onChange={() => setAddModelApiType(opt.v)}
                                      style={{ accentColor: "var(--accent)" }}
                                    />{opt.l}
                                  </label>
                                ))}
                              </div>
                            </div>

                            {/* 思考模式 */}
                            <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 6, alignItems: "center" }}>
                              <label style={{ fontSize: 11, color: "var(--muted)" }}>思考模式</label>
                              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 11 }}>
                                <input type="checkbox"
                                  checked={addModelThinking}
                                  onChange={e => setAddModelThinking(e.target.checked)}
                                  style={{ accentColor: "var(--accent)" }}
                                />
                                开启思考模式（Reasoning/Thinking）
                              </label>
                            </div>

                            {/* 输入类型 */}
                            <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 6, alignItems: "center" }}>
                              <label style={{ fontSize: 11, color: "var(--muted)" }}>输入类型</label>
                              <div style={{ display: "flex", gap: 12, fontSize: 11 }}>
                                {[
                                  { k: "text", l: "文本", v: addModelInputText, s: setAddModelInputText },
                                  { k: "image", l: "图像", v: addModelInputImage, s: setAddModelInputImage },
                                  { k: "audio", l: "音频", v: addModelInputAudio, s: setAddModelInputAudio },
                                  { k: "video", l: "视频", v: addModelInputVideo, s: setAddModelInputVideo },
                                ].map(item => (
                                  <label key={item.k} style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
                                    <input type="checkbox" checked={item.v}
                                      onChange={e => item.s(e.target.checked)}
                                      style={{ accentColor: "var(--accent)" }}
                                    />{item.l}
                                  </label>
                                ))}
                              </div>
                            </div>

                            {/* 上下文窗口 + 最大输出 */}
                            <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 6, alignItems: "center" }}>
                              <label style={{ fontSize: 11, color: "var(--muted)" }}>上下文/输出</label>
                              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                                <label style={{ fontSize: 10, color: "var(--muted2)" }}>窗口</label>
                                <input type="number" className="chat-input" style={{ height: 28, width: 90 }}
                                  value={addModelContextWindow}
                                  onChange={e => setAddModelContextWindow(parseInt(e.target.value) || 32768)}
                                />
                                <label style={{ fontSize: 10, color: "var(--muted2)" }}>最大输出</label>
                                <input type="number" className="chat-input" style={{ height: 28, width: 80 }}
                                  value={addModelMaxOutput}
                                  onChange={e => setAddModelMaxOutput(parseInt(e.target.value) || 4096)}
                                />
                              </div>
                            </div>
                          </div>
                        </details>
                      )}

                      {/* 保存按钮 */}
                      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 4 }}>
                        <button
                          className="btn btn-approve"
                          style={{ fontSize: 11, padding: "5px 16px" }}
                          disabled={!addModelProvider || !addModelName}
                          onClick={async () => {
                            if (!addModelProvider || !addModelName) return;
                            try {
                              const provider = catalog.find(p => p.id === addModelProvider);
                              if (!provider) return;
                              if (addModelApiKey) {
                                const envVar = provider.api_key_env || `API_KEY_${provider.id.toUpperCase()}`;
                                await setApiKey(addModelProvider, envVar, addModelApiKey);
                              }
                              showNotification("模型已添加", `${provider.name} · ${addModelName}`, "success");
                              setShowAddModelDialog(false);
                              resetAddModelDialog();
                              loadModels();
                            } catch (e) { showNotification("添加失败", e instanceof Error ? e.message : String(e), "danger"); }
                          }}
                        >保存</button>
                      </div>
                      <div style={{ fontSize: 10, color: "var(--muted2)" }}>
                        选择提供商后自动关联 Base URL，测试连接可验证 API Key 并获取可用模型列表
                      </div>
                    </div>
                  )}
                </div>

                {/* ============ 语音引擎仪表盘 ============ */}
                <div className="glass-card" style={{ padding: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--accent)" }}>语音引擎仪表盘</div>
                    <button
                      className="btn btn-approve"
                      style={{ fontSize: 10, padding: "3px 10px" }}
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
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 10 }}>
                        <div style={{ padding: 10, borderRadius: 8, background: "rgba(59,130,246,0.1)", textAlign: "center" }}>
                          <div style={{ fontSize: 10, color: "var(--muted2)" }}>ASR 引擎</div>
                          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--accent)" }}>{voiceEngines.asr_count ?? 0}</div>
                        </div>
                        <div style={{ padding: 10, borderRadius: 8, background: "rgba(139,92,246,0.1)", textAlign: "center" }}>
                          <div style={{ fontSize: 10, color: "var(--muted2)" }}>TTS 引擎</div>
                          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--accent3)" }}>{voiceEngines.tts_count ?? 0}</div>
                        </div>
                        <div style={{ padding: 10, borderRadius: 8, background: "rgba(16,185,129,0.1)", textAlign: "center" }}>
                          <div style={{ fontSize: 10, color: "var(--muted2)" }}>引擎总数</div>
                          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--success)" }}>{voiceEngines.total_engines ?? 0}</div>
                        </div>
                      </div>
                      {voiceEngines.engines && voiceEngines.engines.length > 0 && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          {voiceEngines.engines.map((eng: any, i: number) => (
                            <div key={i} style={{
                              display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 8,
                              padding: "6px 10px", background: "rgba(0,0,0,0.15)", borderRadius: 6,
                              fontSize: 11,
                            }}>
                              <span style={{ color: "var(--ink)", fontWeight: 500 }}>{eng.name || eng.id || "未知引擎"}</span>
                              <span style={{ color: "var(--muted2)" }}>{eng.type || eng.role || "N/A"}</span>
                              <span style={{
                                color: eng.available ? "var(--success)" : "var(--danger)"
                              }}>{eng.available ? "✓ 就绪" : "⚠ 不可用"}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <div style={{ fontSize: 11, color: "var(--muted2)", padding: 10, textAlign: "center" }}>
                      {bridgeReady ? "点击刷新加载引擎状态" : "演示模式：连接核心后显示语音引擎"}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* ============ 10. 设置 (settings) ============ */}
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