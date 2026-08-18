import { useEffect, useRef, useState } from "react";
import { ChatReply, StatusInfo, fetchStatus, sendChat } from "./chat";
import { inTauri } from "./chat";
import {
  TrayStateName,
  onTrayEvent,
  onWindowFileDrop,
  setTrayState,
  setupAutostart,
  setupCloseToTray,
  setupHotkeys,
} from "./tray";

interface Msg {
  role: "user" | "assistant";
  text: string;
  meta?: string;
}

// 托盘状态 → 展示文案（与 Python aivyos_core.tray 对齐）
const TRAY_LABEL: Record<string, string> = {
  idle: "待命",
  listening: "监听中",
  working: "工作中",
  voice: "语音对话",
  updating: "更新中",
  booting: "启动中",
  error: "异常",
  paused: "已暂停",
};

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([
    { role: "assistant", text: "我是 Aivy，您的私人 AI 助理。（壳层骨架，Python 核心就绪后接通）" },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [trayState, setTrayStateUi] = useState<TrayStateName>("booting");
  const [dropped, setDropped] = useState<string[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchStatus()
      .then(setStatus)
      .catch(() => setStatus(null)); // 浏览器演示模式：无状态
  }, []);

  // §12.2 托盘：状态初始化 + 事件监听（菜单/单击双击/拖拽）
  useEffect(() => {
    if (!inTauri) return;
    void setTrayState("idle"); // 启动完成 → 待命（§3.1 boot_complete）
    const off = onTrayEvent((ev) => {
      if (ev.kind === "menu") {
        // §3.3 右键菜单项 → 触发对应动作
        const actions: Record<string, () => void> = {
          open: () => inputRef.current?.focus(),
          voice: () => void setTrayState("voice"),
          pause: () => void setTrayState("paused"),
          resume: () => void setTrayState("listening"),
          screenshot: () => inputRef.current?.focus(),
          "update-check": () => void setTrayState("updating"),
          diag: () => setError(`AivyOS shell · 托盘状态: ${trayState}`),
        };
        actions[ev.id]?.();
      } else if (ev.kind === "click") {
        // §3.2 左键单击切换窗口可见性；§3.4 双击 → 语音模式
        if (ev.double) {
          if (ev.state !== "booting" && ev.state !== "updating") {
            void setTrayState("voice");
          }
        }
      }
    });
    return () => void off;
  }, [trayState]);

  // §3.5 拖拽文件（窗口级 drop）→ 显示待分析列表（真实分析由 Python 核心完成）
  useEffect(() => {
    const off = onWindowFileDrop((paths) => {
      setDropped(paths.slice(0, 5));
      void setTrayState("working");
      setTimeout(() => void setTrayState("idle"), 2000);
    });
    return () => void off.then((u) => u());
  }, []);

  // §12.5 开机自启（首次启用）
  useEffect(() => {
    void setupAutostart();
  }, []);

  // §1.4 窗口关闭 → 最小化到托盘（后台常驻）
  useEffect(() => {
    const off = setupCloseToTray();
    return () => void off.then((u) => u());
  }, []);

  // §1.3 全局热键：Alt+Space 唤醒 / Alt+V 语音 / Alt+S 截屏 / Alt+Q 退出
  useEffect(() => {
    const off = setupHotkeys({
      wake: () => inputRef.current?.focus(),
      voice: () => void setTrayState("voice"),
      screenshot: () => inputRef.current?.focus(),
      quit: () => void setTrayState("idle"),
    });
    return () => void off.then((u) => u());
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setBusy(true);
    setError(null);
    void setTrayState("working"); // §3.1 收到任务
    try {
      const reply: ChatReply = await sendChat(text);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: reply.text,
          meta: `${reply.model} · ${reply.route.mode}${reply.route.fallback ? " (降级)" : ""} · ${Math.round(reply.latency_ms)}ms`,
        },
      ]);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setMessages((m) => [
        ...m,
        { role: "assistant", text: "（未能连接 Python 核心：请先启动 `python -m aivyos_core.server_entry`）" },
      ]);
    } finally {
      setBusy(false);
      void setTrayState("idle"); // §3.1 任务完成
    }
  }

  return (
    <div className="app">
      <header className="bar">
        <span className="dot" />
        <strong>AivyOS</strong>
        {inTauri && <span className="tray-badge">托盘: {TRAY_LABEL[trayState] ?? trayState}</span>}
        <span className="spacer" />
        {status ? (
          <span className="status">
            记忆: {status.backend} · 会话: {status.sessions} ·{" "}
            {status.routes.map((r) => `${r.mode}${r.available ? "✓" : "✗"}`).join(" ")}
          </span>
        ) : (
          <span className="status dim">演示模式（未连接核心）</span>
        )}
      </header>

      <main className="chat">
        {dropped.length > 0 && (
          <div className="dropbar">
            📂 拖入 {dropped.length} 个文件待分析：{dropped.join(", ")}
            <button onClick={() => setDropped([])}>清除</button>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">{m.text}</div>
            {m.meta && <div className="meta">{m.meta}</div>}
          </div>
        ))}
        {busy && <div className="msg assistant"><div className="bubble typing">Aivy 正在思考…</div></div>}
        {error && <div className="error">{error}</div>}
        <div ref={bottomRef} />
      </main>

      <footer className="inputbar">
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="输入消息，回车发送…（Alt+Space 随时唤醒，Alt+V 语音）"
          disabled={busy}
        />
        <button onClick={handleSend} disabled={busy || !input.trim()}>
          发送
        </button>
      </footer>
    </div>
  );
}
