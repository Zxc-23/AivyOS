// AivyOS 前端 ↔ 核心桥接（文档 §12.1 IPC：Named Pipe / UDS）
// Week 1：Tauri invoke → Rust bridge 命令 → Python 核心 IPC。

export interface RouteDecision {
  mode: "local" | "cloud" | "mock";
  model: string;
  reason: string;
  fallback: boolean;
}

export interface ChatReply {
  text: string;
  session_id: string;
  model: string;
  route: RouteDecision;
  latency_ms: number;
  memory_hits: unknown[];
  knowledge_hits?: { card: KnowledgeCard; score: number }[];
}

export interface SessionInfo {
  session_id: string;
  messages: number;
  updated_at: number;
}

export interface StatusInfo {
  backend: string;
  routes: { mode: string; model: string; available: boolean }[];
  home: string;
  sessions: number;
}

export interface VoiceStatus {
  asr: string;
  tts: string;
  vad: string;
  source: string;
  sink: string;
  wake_required: boolean;
  wake_words: string[];
  llm_route_mode: string;
  auth_enabled?: boolean;
  auth_state?: string;
  current_user?: string;
  error?: string;
  fallback?: boolean;
  asr_ready?: boolean;
  tts_ready?: boolean;
}

export interface VoiceTurnResult {
  ok: boolean;
  text: string;
  reply?: string;
  model?: string;
  route?: RouteDecision;
  latency_ms?: number;
  asr_backend?: string;
  tts_backend?: string;
  wav_len?: number;
  wav_b64?: string;
  sample_rate?: number;
  fallback?: boolean;
  error?: string;
  error_type?: string;
  error_detail?: string;
  source?: string;
  wake?: boolean;
  continuous?: {
    active: boolean;
    turns_left: number;
    window_left_s: number;
  };
  breakdown_ms?: {
    asr: number;
    llm: number;
    tts: number;
    playback: number;
    total: number;
  };
}

export interface TaskInfo {
  id: string;
  title: string;
  status: "pending" | "working" | "completed" | "error";
  steps: { title: string; detail: string }[];
  current_step: number;
  logs: string[];
  created_at?: string;
}

export interface SchedulerJob {
  name: string;
  kind: string;
  runs: number;
  last_run: string | null;
  error: string;
}

export interface BootCheckResult {
  checks: { name: string; ok: boolean; detail: string }[];
  progress: number;
  passed: number;
  total: number;
  summary: string;
}

export interface MemoryEntry {
  id?: string;
  text: string;
  score?: number;
  created_at?: string;
  category?: string;
}

export interface VibeRunResult {
  ok: boolean;
  steps?: Record<string, unknown>;
  files?: Record<string, string>;
  delivered_to?: string;
  preview_url?: string;
  preview_ok?: boolean;
  build_failed?: boolean;
  error?: string;
}

export interface VoiceSettings {
  wake_words: string[];
  wake_required: boolean;
  asr_backend: string;
  asr_model: string;
  tts_backend: string;
  tts_model: string;
  tts_voice?: string;
  tts_speed?: number;
  tts_resource_id?: string;
  language: string;
  silence_timeout_s: number;
}

export interface ApplyVoiceTtsResult {
  ok: boolean;
  backend?: string;
  message?: string;
  error?: string;
}

/** 是否运行在 Tauri WebView 内 */
function detectTauri(): boolean {
  if (typeof window === "undefined") return false;
  const hasInternals = "__TAURI_INTERNALS__" in window;
  const hasTauri = "__TAURI__" in window;
  console.log("[AivyOS] 环境检测: __TAURI_INTERNALS__ =", hasInternals, "__TAURI__ =", hasTauri);
  return hasInternals || hasTauri;
}

export const inTauri = detectTauri();

console.log("[AivyOS] inTauri =", inTauri);

/** Mock 数据（非 Tauri 环境下的演示数据）。 */
const MOCK_DATA: Record<string, any> = {
  "models.catalog": {
    providers: [
      { id: "deepseek", name: "DeepSeek", category: "cloud-compat", description: "深度求索", base_url: "https://api.deepseek.com/v1", api_key_env: "DEEPSEEK_API_KEY", auth_type: "api_key", website: "https://deepseek.com", default_model: "deepseek-v4-flash" },
      { id: "openai", name: "OpenAI", category: "cloud-native", description: "GPT 系列", base_url: "https://api.openai.com/v1", api_key_env: "OPENAI_API_KEY", auth_type: "api_key", website: "https://openai.com", default_model: "gpt-4o" },
      { id: "anthropic", name: "Anthropic", category: "cloud-native", description: "Claude 系列", base_url: "https://api.anthropic.com/v1", api_key_env: "ANTHROPIC_API_KEY", auth_type: "api_key", website: "https://anthropic.com", default_model: "claude-3-sonnet-20240229" },
      { id: "google", name: "Google", category: "cloud-native", description: "Gemini 系列", base_url: "https://generativelanguage.googleapis.com/v1", api_key_env: "GOOGLE_API_KEY", auth_type: "api_key", website: "https://google.com", default_model: "gemini-1.5-pro" },
      { id: "qwen", name: "阿里云百炼", category: "cloud-compat", description: "通义系列", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", api_key_env: "DASHSCOPE_API_KEY", auth_type: "api_key", website: "https://aliyun.com", default_model: "qwen-plus" },
      { id: "siliconflow", name: "SiliconFlow", category: "cloud-compat", description: "硅基流动", base_url: "https://api.siliconflow.cn/v1", api_key_env: "SILICONFLOW_API_KEY", auth_type: "api_key", website: "https://siliconflow.cn", default_model: "deepseek-v4-flash" },
      { id: "doubao", name: "豆包/火山引擎", category: "cloud-native", description: "豆包大模型", base_url: "https://ark.cn-beijing.volces.com/api/v3", api_key_env: "VOLCENGINE_API_KEY", auth_type: "api_key", website: "https://volcengine.com", default_model: "doubao-pro-32k" },
      { id: "mistral", name: "Mistral AI", category: "cloud-native", description: "Mistral 系列", base_url: "https://api.mistral.ai/v1", api_key_env: "MISTRAL_API_KEY", auth_type: "api_key", website: "https://mistral.ai", default_model: "mistral-large-latest" },
      { id: "azure-openai", name: "Azure OpenAI", category: "cloud-native", description: "Azure 托管", base_url: "", api_key_env: "AZURE_OPENAI_API_KEY", auth_type: "api_key", website: "https://azure.microsoft.com", default_model: "gpt-4o" },
      { id: "ollama", name: "Ollama", category: "local", description: "本地运行", base_url: "http://localhost:11434/v1", api_key_env: "", auth_type: "none", website: "https://ollama.com", default_model: "qwen2.5:7b" },
      { id: "vllm", name: "vLLM", category: "local", description: "本地推理服务", base_url: "http://localhost:8000/v1", api_key_env: "", auth_type: "none", website: "https://vllm.ai", default_model: "qwen2.5-7b" },
      { id: "bedrock", name: "AWS Bedrock", category: "cloud-native", description: "亚马逊云", base_url: "", api_key_env: "AWS_ACCESS_KEY_ID", auth_type: "sigv4", website: "https://aws.amazon.com", default_model: "anthropic.claude-3-sonnet" },
    ],
    categories: {
      local: [{ id: "ollama", name: "Ollama" }, { id: "vllm", name: "vLLM" }],
      "cloud-compat": [{ id: "deepseek", name: "DeepSeek" }, { id: "qwen", name: "阿里云百炼" }, { id: "siliconflow", name: "SiliconFlow" }],
      "cloud-native": [{ id: "openai", name: "OpenAI" }, { id: "anthropic", name: "Anthropic" }, { id: "google", name: "Google" }, { id: "doubao", name: "豆包/火山引擎" }, { id: "mistral", name: "Mistral AI" }, { id: "azure-openai", name: "Azure OpenAI" }, { id: "bedrock", name: "AWS Bedrock" }],
    },
  },
  "models.api-key.list": {
    api_keys: {
      DEESEEK_API_KEY: { env_var: "DEEPSEEK_API_KEY", has_key: false, key_length: 0 },
      OPENAI_API_KEY: { env_var: "OPENAI_API_KEY", has_key: false, key_length: 0 },
      ANTHROPIC_API_KEY: { env_var: "ANTHROPIC_API_KEY", has_key: false, key_length: 0 },
      DASHSCOPE_API_KEY: { env_var: "DASHSCOPE_API_KEY", has_key: false, key_length: 0 },
      VOLCENGINE_API_KEY: { env_var: "VOLCENGINE_API_KEY", has_key: false, key_length: 0 },
      SILICONFLOW_API_KEY: { env_var: "SILICONFLOW_API_KEY", has_key: false, key_length: 0 },
      MISTRAL_API_KEY: { env_var: "MISTRAL_API_KEY", has_key: false, key_length: 0 },
      AZURE_OPENAI_API_KEY: { env_var: "AZURE_OPENAI_API_KEY", has_key: false, key_length: 0 },
    },
  },
  "models.api-key.set": { ok: true },
  "models.api-key.remove": { ok: true },
  "voiceset.apply-tts": { ok: true, backend: "cloud-tts", message: "TTS 已切换到 cloud-tts" },
  "voice.engines": {
    total_engines: 3,
    asr_count: 1,
    tts_count: 2,
    engines: [
      { name: "asr-mock", type: "asr", provider: "mock", ready: true },
      { name: "tts-mock", type: "tts", provider: "mock", ready: true },
      { name: "tts-doubao", type: "tts", provider: "doubao", ready: false },
    ],
    breakers: {},
    cost: { total_tokens: 0, total_cost_usd: 0 },
  },
  "voice.engine.config": { ok: true },
  "voice.test-tts": async (params: any) => {
    // 浏览器模式：云端服务商无 API Key 时返回错误
    const cloudNeedKey = ["doubao-tts", "doubao"];
    if (cloudNeedKey.includes(params?.provider) && !params?.api_key) {
      return {
        ok: false,
        error: `服务商 ${params.provider} 需要配置 API Key，请先在上方填写后再试听`,
        backend: params?.provider,
      };
    }
    // 否则生成一段简短的 base64 WAV 提示音
    const duration = Math.min(params?.text?.length || 1, 3) * 0.5;
    const sampleRate = 24000;
    const numSamples = Math.floor(sampleRate * duration);
    const pcm = new Int16Array(numSamples);
    for (let i = 0; i < numSamples; i++) {
      pcm[i] = Math.floor(1200 * Math.sin(2 * Math.PI * 440 * i / sampleRate));
    }
    const wavLen = 44 + pcm.length * 2;
    const buffer = new ArrayBuffer(wavLen);
    const view = new DataView(buffer);
    const writeStr = (offset: number, str: string) => {
      for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
    };
    writeStr(0, "RIFF");
    view.setUint32(4, 36 + pcm.length * 2, true);
    writeStr(8, "WAVE");
    writeStr(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, "data");
    view.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) {
      view.setInt16(44 + i * 2, pcm[i], true);
    }
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + chunk)) as any);
    }
    const wavB64 = btoa(binary);
    return {
      ok: true,
      wav_b64: wavB64,
      sample_rate: sampleRate,
      text: params?.text || "测试",
      backend: "mock-browser",
      pcm_len: pcm.length * 2,
      wav_len: wavLen,
      latency_ms: 50,
    };
  },
  "models.test-connection": {
    ok: true, model_count: 3,
    models: [
      { id: "deepseek-v4-flash", owned_by: "deepseek" },
      { id: "deepseek-v4-pro", owned_by: "deepseek" },
      { id: "deepseek-v3", owned_by: "deepseek" },
    ],
  },
  "models.list": [
    { mode: "ollama", model: "local-default", available: true, provider: "ollama" },
    { mode: "deepseek", model: "cloud-default", available: true, provider: "deepseek" },
    { mode: "mock", model: "mock-default", available: true, provider: "mock" },
  ],
  "models.preset-list": {
    ok: true, provider: "deepseek",
    models: [
      { name: "deepseek-v4-flash", display_name: "DeepSeek V4 Flash", context_window: 1000000, supports_vision: false, supports_tool_use: true, supports_thinking: true, supports_streaming: true, input_price_per_1m: 0.14, output_price_per_1m: 0.28, description: "通用主力，性价比首选" },
      { name: "deepseek-v4-pro", display_name: "DeepSeek V4 Pro", context_window: 1000000, supports_vision: false, supports_tool_use: true, supports_thinking: true, supports_streaming: true, input_price_per_1m: 1.74, output_price_per_1m: 3.48, description: "旗舰推理，高难度任务" },
      { name: "deepseek-v3", display_name: "DeepSeek V3", context_window: 128000, supports_vision: false, supports_tool_use: false, supports_thinking: false, supports_streaming: true, input_price_per_1m: 0.5, output_price_per_1m: 2, description: "低成本版本" },
    ],
  },
};

/**
 * 通用桥接调用：Tauri 内走 invoke("bridge")；
 * 浏览器演示模式（npm run dev 单独跑）使用 Mock 数据。
 */
export async function bridgeCall<T>(
  method: string,
  params: Record<string, unknown>
): Promise<T> {
  if (inTauri) {
    const { invoke } = await import("@tauri-apps/api/core");
    console.log("[AivyOS] bridge.invoke:", method, params);
    try {
      const result = await invoke<T>("bridge", { method, params });
      console.log("[AivyOS] bridge.result:", method, result);
      return result;
    } catch (e) {
      console.error("[AivyOS] bridge.error:", method, e);
      throw e;
    }
  }
  // 非 Tauri 环境：返回 Mock 数据
  if (MOCK_DATA[method]) {
    console.log("[AivyOS] bridge.mock:", method);
    return MOCK_DATA[method] as T;
  }
  console.warn("[AivyOS] 非 Tauri 环境，无 Mock 数据:", method);
  throw new Error(
    `演示模式：请通过 \`npm run tauri dev\`（需 Rust）或先启动 Python 核心。bridge(${method}) 未接通。`
  );
}

// ================================================================
//  基础对话接口
// ================================================================

export interface ChatReply {
  text: string;
  session_id: string;
  model: string;
  route: RouteDecision;
  latency_ms: number;
  memory_hits: unknown[];
  knowledge_hits?: { card: KnowledgeCard; score: number }[];
  vision_used?: boolean;
}

export async function sendChat(
  text: string,
  sessionId?: string,
  image?: { path?: string; b64?: string },
): Promise<ChatReply> {
  const params: Record<string, unknown> = { text, session_id: sessionId ?? null };
  if (image?.path) params.image_path = image.path;
  if (image?.b64) params.image_b64 = image.b64;
  return bridgeCall<ChatReply>("chat.send", params);
}

/** 读取本地图片 → base64（拖拽预览用）。 */
export async function readImagePreview(path: string): Promise<{
  ok: boolean; base64?: string; mime?: string; size?: number; error?: string;
}> {
  return bridgeCall("vision.read-image", { path });
}

/** 主动加载视觉模型（需要时触发；Ollama keep_alive 驻留）。 */
export async function loadVisionModel(): Promise<{ ok: boolean; message: string }> {
  return bridgeCall("vision.load", {});
}

/** 主动释放视觉模型（释放显存）。 */
export async function releaseVisionModel(): Promise<{ ok: boolean; message: string }> {
  return bridgeCall("vision.release", {});
}

export async function fetchStatus(): Promise<StatusInfo> {
  return bridgeCall<StatusInfo>("status", {});
}

// ================================================================
//  Voice
// ================================================================

export async function getVoiceStatus(): Promise<VoiceStatus> {
  return bridgeCall<VoiceStatus>("voice.status", {});
}

export async function runVoiceTurn(text?: string, continuous = false): Promise<VoiceTurnResult> {
  return bridgeCall<VoiceTurnResult>("voice.turn", { text: text ?? null, continuous });
}

export async function listenVoice(continuous = false): Promise<VoiceTurnResult> {
  return bridgeCall<VoiceTurnResult>("voice.turn", { continuous });
}

/** PTT（按住说话）：开始采集（按住空格/鼠标）。 */
export async function pttStart(): Promise<{ ok: boolean; active: boolean; error?: string }> {
  return bridgeCall("voice.ptt.start", {});
}

/** PTT（按住说话）：停止采集并处理（松开空格/鼠标）。 */
export async function pttStop(continuous = false): Promise<VoiceTurnResult> {
  return bridgeCall<VoiceTurnResult>("voice.ptt.stop", { continuous });
}

/** 查询连续对话会话状态（唤醒后窗口期内免唤醒词）。 */
export async function getContinuousStatus(): Promise<{
  ok: boolean; active: boolean; turns: number; turns_left: number;
  window_left_s: number; window_s: number; max_turns: number;
}> {
  return bridgeCall("voice.continuous.status", {});
}

/** 手动结束连续对话会话。 */
export async function resetContinuous(): Promise<{ ok: boolean; active: boolean }> {
  return bridgeCall("voice.continuous.reset", {});
}

// ================================================================
//  Wake Loop (后台唤醒监听)
// ================================================================

export interface WakeLoopStatus {
  ok: boolean;
  running?: boolean;
  already_running?: boolean;
  already_stopped?: boolean;
  wake_count?: number;
  last_wake_time?: number;
  cooldown_remaining?: number;
  status?: WakeLoopStatus;
}

export interface WakeEvent {
  text: string;
  timestamp: number;
}

/** 启动后台唤醒监听循环。 */
export async function startWakeLoop(asrConfig?: Record<string, unknown>): Promise<WakeLoopStatus> {
  return bridgeCall<WakeLoopStatus>("voice.wake_loop.start", { asr_config: asrConfig || {} });
}

/** 停止后台唤醒监听循环。 */
export async function stopWakeLoop(): Promise<WakeLoopStatus> {
  return bridgeCall<WakeLoopStatus>("voice.wake_loop.stop", {});
}

/** 查询后台唤醒监听状态。 */
export async function getWakeLoopStatus(): Promise<WakeLoopStatus> {
  return bridgeCall<WakeLoopStatus>("voice.wake_loop.status", {});
}

/** 订阅唤醒事件（Tauri 事件系统）。 */
export async function listenWakeEvents(
  onWake: (event: WakeEvent) => void
): Promise<() => void> {
  if (!inTauri) {
    return () => {};
  }
  const { listen } = await import("@tauri-apps/api/event");
  const unlisten = await listen<WakeEvent>("ipc:wake-detected", (event) => {
    onWake(event.payload as WakeEvent);
  });
  return unlisten;
}

// ================================================================
//  Memory
// ================================================================

export async function searchMemory(query: string, topK = 5): Promise<MemoryEntry[]> {
  return bridgeCall<MemoryEntry[]>("memory.search", { query, top_k: topK });
}

export async function addMemory(text: string): Promise<{ id: string }> {
  return bridgeCall<{ id: string }>("memory.add", { text });
}

export async function listMemory(): Promise<MemoryEntry[]> {
  return bridgeCall<MemoryEntry[]>("memory.list", {});
}

// ================================================================
//  Knowledge Cards（知识卡片系统）
// ================================================================

export interface KnowledgeCard {
  id: string;
  title: string;
  summary: string;
  content: string;
  category: string;
  tags: string[];
  favorite: boolean;
  source: string;
  created_at: string;
  updated_at: string;
  version: number;
  versions: { title: string; summary: string; content: string; version: number; ts: string }[];
  links: string[];
  usage: number;
}

export interface KnowledgeHit {
  card: KnowledgeCard;
  score: number;
}

export async function listKnowledge(params: {
  sort?: string; category?: string; tag?: string; favorite_only?: boolean;
} = {}): Promise<KnowledgeCard[]> {
  return bridgeCall<KnowledgeCard[]>("knowledge.list", params);
}

export async function getKnowledge(id: string): Promise<KnowledgeCard> {
  return bridgeCall<KnowledgeCard>("knowledge.get", { id });
}

export async function createKnowledge(fields: Partial<KnowledgeCard>): Promise<KnowledgeCard> {
  return bridgeCall<KnowledgeCard>("knowledge.create", fields);
}

export async function updateKnowledge(id: string, changes: Record<string, unknown>): Promise<KnowledgeCard> {
  return bridgeCall<KnowledgeCard>("knowledge.update", { id, changes });
}

export async function deleteKnowledge(id: string): Promise<{ ok: boolean }> {
  return bridgeCall("knowledge.delete", { id });
}

export async function toggleKnowledgeFavorite(id: string): Promise<KnowledgeCard> {
  return bridgeCall<KnowledgeCard>("knowledge.favorite", { id });
}

export async function searchKnowledge(query: string, limit = 20): Promise<KnowledgeCard[]> {
  return bridgeCall<KnowledgeCard[]>("knowledge.search", { query, limit });
}

export async function recallKnowledge(text: string, limit = 3, minScore = 0.05): Promise<KnowledgeHit[]> {
  return bridgeCall<KnowledgeHit[]>("knowledge.recall", { text, limit, min_score: minScore });
}

export async function ingestKnowledge(text: string): Promise<{ action: string; card?: KnowledgeCard }> {
  return bridgeCall("knowledge.ingest", { text });
}

export async function getKnowledgeStats(): Promise<{
  total: number; favorites: number; categories: string[]; tags: string[];
}> {
  return bridgeCall("knowledge.stats", {});
}

export async function linkKnowledge(id: string, otherId: string): Promise<{ ok: boolean }> {
  return bridgeCall("knowledge.link", { id, other_id: otherId });
}

export async function backupKnowledge(path?: string): Promise<{ ok: boolean; path: string }> {
  return bridgeCall("knowledge.backup", { path: path ?? "" });
}

export async function restoreKnowledge(path: string, merge = false): Promise<{ ok: boolean; imported: number }> {
  return bridgeCall("knowledge.restore", { path, merge });
}

/** 知识图谱数据（节点+边，供力导向图渲染）。 */
export async function getKnowledgeGraph(): Promise<{
  nodes: { id: string; title: string; category: string; favorite: boolean; usage: number }[];
  edges: { source: string; target: string }[];
}> {
  return bridgeCall("knowledge.graph", {});
}

/** 导出单卡（markdown/json）。 */
export async function exportKnowledge(id: string, format = "markdown"): Promise<{ format: string; text: string }> {
  return bridgeCall("knowledge.export", { id, format });
}

// ================================================================
//  Autonomous Tasks
// ================================================================

export async function createTask(description: string): Promise<{
  ok: boolean;
  task_id: string;
  steps: { title: string; detail: string }[];
  total_steps: number;
}> {
  return bridgeCall("task.create", { description });
}

export async function listTasks(): Promise<TaskInfo[]> {
  return bridgeCall<TaskInfo[]>("task.list", {});
}

export async function executeTask(taskId: string): Promise<{ ok: boolean; task: TaskInfo }> {
  return bridgeCall("task.execute", { task_id: taskId });
}

// ================================================================
//  Scheduler
// ================================================================

export async function listSchedules(): Promise<SchedulerJob[]> {
  return bridgeCall<SchedulerJob[]>("sched.list", {});
}

export async function createSchedule(
  name: string,
  cronExpr: string,
  handlerText: string
): Promise<{ ok: boolean; name?: string; cron?: string; error?: string }> {
  return bridgeCall("sched.create", { name, cron_expr: cronExpr, handler_text: handlerText });
}

// ================================================================
//  Vibe Coding
// ================================================================

export async function runVibe(
  request: string,
  executor: string = "demo"
): Promise<VibeRunResult> {
  return bridgeCall<VibeRunResult>("vibe.run", { request, executor });
}

// ================================================================
//  Boot / Self-check
// ================================================================

export async function runBootCheck(fast = true): Promise<BootCheckResult> {
  return bridgeCall<BootCheckResult>("boot.check", { fast });
}

// ================================================================
//  Voice Settings
// ================================================================

export async function getVoiceSettings(): Promise<VoiceSettings> {
  return bridgeCall<VoiceSettings>("voiceset.get", {});
}

export async function setVoiceSettings(
  field: string,
  value: unknown
): Promise<{ ok: boolean; field?: string; value?: unknown; error?: string }> {
  return bridgeCall("voiceset.set", { field, value });
}

export async function applyVoiceTts(
  provider: string,
  voice: string,
  speed: number,
  apiKey?: string,
  resourceId?: string,
): Promise<ApplyVoiceTtsResult> {
  return bridgeCall("voiceset.apply-tts", {
    provider, voice, speed,
    api_key: apiKey || "",
    resource_id: resourceId || "",
  });
}

// ================================================================
//  Model Management
// ================================================================

export async function listModels(): Promise<
  { mode: string; model: string; available: boolean; active?: boolean }[]
> {
  return bridgeCall("models.list", {});
}

export async function setActiveModel(model: string | null): Promise<{ ok: boolean; active: string | null; message: string }> {
  return bridgeCall("models.set-active", { model });
}

// ================================================================
//  Model Management — Phase 2: 健康仪表盘 + 成本追踪
// ================================================================

export interface BackendHealth {
  mode: string;
  model: string;
  provider: string;
  available: boolean;
  breaker_state: string;
  priority: number;
  capabilities: Record<string, unknown>;
  latency_ms?: number;
}

export interface CostStats {
  backend_name: string;
  total_requests: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  last_updated: number;
}

export interface CostDashboard {
  total_requests: number;
  total_tokens: number;
  total_cost_usd: number;
  backend_count: number;
  backends: Record<string, CostStats>;
  recent: CostEntry[];
}

export interface CostEntry {
  timestamp: number;
  backend_name: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  cost_usd: number;
}

export async function getModelsHealth(): Promise<{
  backends: BackendHealth[];
  breakers: Record<string, unknown>;
  strategy: Record<string, unknown>;
}> {
  return bridgeCall("models.health", {});
}

export async function getModelsCost(backend?: string, recent = false): Promise<CostDashboard> {
  return bridgeCall("models.cost", { backend: backend ?? null, recent });
}

export async function getModelsBackends(): Promise<BackendHealth[]> {
  return bridgeCall("models.backends", {});
}

// ================================================================
//  Model Catalog & API Keys — Enhanced
// ================================================================

export interface ProviderModel {
  name: string;
  display_name: string;
  context_window: number;
  supports_vision: boolean;
  supports_tool_use: boolean;
  supports_thinking: boolean;
  supports_streaming: boolean;
  input_price_per_1m: number;
  output_price_per_1m: number;
  description: string;
}

export interface ProviderCatalogEntry {
  id: string;
  name: string;
  category: string;
  description: string;
  base_url: string;
  api_key_env: string;
  auth_type: string;
  website: string;
  default_model: string;
  models: ProviderModel[];
}

export interface ApiKeyEntry {
  env_var: string;
  has_key: boolean;
  key_length: number;
  masked_preview?: string;
  provider?: string;
  source?: string;
  updated_at?: number;
}

export interface SetApiKeyResult {
  ok: boolean;
  env_var?: string;
  provider?: string;
  key_length?: number;
  masked_preview?: string;
  error?: string;
  removed?: boolean;
}

export interface RemoveApiKeyResult {
  ok: boolean;
  env_var?: string;
  was_in_cache?: boolean;
  was_in_env?: boolean;
  error?: string;
}

export async function getModelCatalog(keyword?: string): Promise<any> {
  return bridgeCall("models.catalog", { keyword: keyword || "" });
}

export async function listApiKeys(): Promise<{ api_keys: Record<string, ApiKeyEntry> }> {
  return bridgeCall("models.api-key.list", {});
}

export async function setApiKey(
  field: string,
  env_var: string,
  value: string,
  provider?: string,
): Promise<SetApiKeyResult> {
  return bridgeCall("models.api-key.set", { field, env_var, value, provider: provider || "" });
}

export async function removeApiKey(
  field: string,
  env_var: string,
): Promise<RemoveApiKeyResult> {
  return bridgeCall("models.api-key.remove", { field, env_var });
}

// ================================================================
//  API Key 本地缓存 (localStorage) — 加速 UI 渲染
// ================================================================

const API_KEYS_CACHE_KEY = "aivyos_api_keys_cache";

export function loadCachedApiKeys(): Record<string, ApiKeyEntry> {
  try {
    const raw = localStorage.getItem(API_KEYS_CACHE_KEY);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch {}
  return {};
}

export function saveCachedApiKeys(keys: Record<string, ApiKeyEntry>): void {
  try {
    localStorage.setItem(API_KEYS_CACHE_KEY, JSON.stringify(keys));
  } catch {}
}

export function clearCachedApiKeys(): void {
  try {
    localStorage.removeItem(API_KEYS_CACHE_KEY);
  } catch {}
}

/** 前端持久化存储 — 将 API Key 元信息缓存到 localStorage */
export const apiKeyStorage = {
  load: (): Record<string, ApiKeyEntry> => loadCachedApiKeys(),
  save: (keys: Record<string, ApiKeyEntry>): void => saveCachedApiKeys(keys),
  clear: (): void => clearCachedApiKeys(),
};

export interface VoiceEngineStatus {
  total_engines: number;
  asr_count: number;
  tts_count: number;
  engines: any[];
  breakers: any;
  cost: any;
}

export async function getVoiceEngines(): Promise<VoiceEngineStatus> {
  return bridgeCall("voice.engines", {});
}

export async function configVoiceEngine(
  engine: string,
  field: string,
  value: string,
): Promise<{ ok: boolean; engine: string; field: string }> {
  return bridgeCall("voice.engine.config", { engine, field, value });
}

export interface TestTtsResult {
  ok: boolean;
  wav_b64?: string;
  sample_rate?: number;
  text?: string;
  backend?: string;
  pcm_len?: number;
  wav_len?: number;
  latency_ms?: number;
  error?: string;
  warning?: string;
}

export async function testTts(
  text: string,
  provider: string,
  voice: string,
  speed: number,
  apiKey?: string,
  resourceId?: string,
): Promise<TestTtsResult> {
  return bridgeCall("voice.test-tts", {
    text, provider, voice, speed,
    api_key: apiKey || "",
    resource_id: resourceId || "",
  });
}

// ================================================================
//  Model Connection — New
// ================================================================

export interface TestConnectionResult {
  ok: boolean;
  provider?: string;
  model_count?: number;
  models?: { id: string; owned_by: string }[];
  error?: string;
}

export interface ListModelsResult {
  ok: boolean;
  provider?: string;
  models?: ProviderModel[];
  error?: string;
}

export async function testModelConnection(
  provider: string,
  apiKey: string,
  baseUrl: string,
): Promise<TestConnectionResult> {
  return bridgeCall("models.test-connection", { provider, api_key: apiKey, base_url: baseUrl });
}

export interface CloudTestResult {
  provider: string;
  name: string;
  ok: boolean;
  error?: string;
  model_count: number;
  models?: string[];
}

export interface CloudTestSummary {
  ok: boolean;
  total: number;
  passed: number;
  failed: number;
  error?: string;
  results: CloudTestResult[];
}

/** 批量测试所有已配置 API Key 的云端提供商连通性。 */
export async function testCloudModels(): Promise<CloudTestSummary> {
  return bridgeCall<CloudTestSummary>("models.test-cloud", {});
}

export async function listProviderModels(
  provider: string,
  keyword?: string,
): Promise<ListModelsResult> {
  return bridgeCall("models.preset-list", { provider, keyword: keyword || "" });
}

export interface AddBackendResult {
  ok: boolean;
  name?: string;
  provider?: string;
  model?: string;
  error?: string;
}

export interface RemoveBackendResult {
  ok: boolean;
  name?: string;
  error?: string;
}

export async function addBackend(
  name: string,
  provider: string,
  model: string,
  baseUrl?: string,
  apiKeyEnv?: string,
): Promise<AddBackendResult> {
  return bridgeCall("models.add", {
    name,
    provider,
    model,
    base_url: baseUrl || "",
    api_key_env: apiKeyEnv || "",
  });
}

export async function removeBackend(name: string): Promise<RemoveBackendResult> {
  return bridgeCall("models.remove", { name });
}

// ================================================================
//  MCP Server — Phase 3
// ================================================================

export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export async function listMcpTools(): Promise<{ tools: McpTool[] }> {
  return bridgeCall("mcp.tools", {});
}

// ================================================================
//  Skills（技能管理）
// ================================================================

export interface Skill {
  id: string;
  name: string;
  description: string;
  category: string;
  keywords: string[];
  system_prompt: string;
  enabled: boolean;
  builtin?: boolean;
  created_at?: number;
  updated_at?: number;
}

export interface SkillResult {
  ok: boolean;
  error?: string;
  skills?: Skill[];
  skill?: Skill;
}

export async function listSkills(): Promise<SkillResult> {
  return bridgeCall<SkillResult>("skills.list", {});
}

export async function createSkill(fields: {
  name: string; description?: string; category?: string;
  keywords?: string[]; system_prompt?: string; enabled?: boolean;
}): Promise<SkillResult> {
  return bridgeCall<SkillResult>("skills.create", {
    name: fields.name,
    description: fields.description || "",
    category: fields.category || "自定义",
    keywords: fields.keywords || [],
    system_prompt: fields.system_prompt || "",
    enabled: fields.enabled ?? true,
  });
}

export async function updateSkill(id: string, changes: Record<string, unknown>): Promise<SkillResult> {
  return bridgeCall<SkillResult>("skills.update", { id, changes });
}

export async function deleteSkill(id: string): Promise<SkillResult> {
  return bridgeCall<SkillResult>("skills.delete", { id });
}

export async function setSkillEnabled(id: string, enabled: boolean): Promise<SkillResult> {
  return bridgeCall<SkillResult>("skills.set-enabled", { id, enabled });
}

// ================================================================
//  Tools（MCP 工具管理）
// ================================================================

export interface ManagedTool {
  name: string;
  description: string;
  permission: string;
  server: string;
  input_schema: Record<string, unknown>;
  enabled: boolean;
}

export interface ToolsResult {
  ok: boolean;
  error?: string;
  tools?: ManagedTool[];
  count?: number;
}

export async function listTools(): Promise<ToolsResult> {
  return bridgeCall<ToolsResult>("tools.list", {});
}

export async function setToolEnabled(name: string, enabled: boolean): Promise<{ ok: boolean; name?: string; enabled?: boolean; error?: string }> {
  return bridgeCall("tools.set-enabled", { name, enabled });
}

export async function callMcpTool(tool: string, params: Record<string, unknown>): Promise<unknown> {
  return bridgeCall("mcp.call", { tool, params });
}

// ================================================================
//  Fallback Chain — Phase 3
// ================================================================

export interface FallbackStepConfig {
  name: string;
  model: string;
  provider: string;
  temperature?: number;
  max_retries?: number;
  timeout_s?: number;
  enabled?: boolean;
}

export async function executeFallbackChain(
  steps: FallbackStepConfig[],
  messages: { role: string; content: string }[],
  model = "auto"
): Promise<{
  success: boolean;
  step_used: string;
  text: string;
  error: string;
  total_latency_ms: number;
  steps_attempted: string[];
}> {
  return bridgeCall("fallback.execute", { steps, messages, model });
}

export async function getFallbackStatus(steps: FallbackStepConfig[]): Promise<unknown> {
  return bridgeCall("fallback.status", { steps });
}

// ================================================================
//  Config
// ================================================================

export async function getConfig(): Promise<Record<string, unknown>> {
  return bridgeCall<Record<string, unknown>>("config.get", {});
}

export async function updateConfig(
  path: string,
  value: unknown
): Promise<{ ok: boolean; path?: string }> {
  return bridgeCall("config.update", { path, value });
}