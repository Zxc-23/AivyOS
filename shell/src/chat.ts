// AivyOS 前端 ↔ 核心桥接（文档 §12.1 IPC：Named Pipe / UDS）
// Week 1：Tauri invoke → Rust bridge 命令（占位）；后续接通 Python 核心 IPC。

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

/** 是否运行在 Tauri WebView 内 */
export const inTauri =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/**
 * 通用桥接调用：Tauri 内走 invoke("bridge")；
 * 浏览器演示模式（npm run dev 单独跑）抛错并提示。
 */
export async function bridgeCall<T>(
  method: string,
  params: Record<string, unknown>
): Promise<T> {
  if (inTauri) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<T>("bridge", { method, params });
  }
  throw new Error(
    `演示模式：请通过 \`npm run tauri dev\`（需 Rust）或先启动 Python 核心。bridge(${method}) 未接通。`
  );
}

export async function sendChat(text: string, sessionId?: string): Promise<ChatReply> {
  return bridgeCall<ChatReply>("chat.send", { text, session_id: sessionId ?? null });
}

export async function fetchStatus(): Promise<StatusInfo> {
  return bridgeCall<StatusInfo>("status", {});
}
