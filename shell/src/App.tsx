import { useEffect, useRef, useState } from "react";
import { ChatReply, StatusInfo, fetchStatus, sendChat } from "./chat";
import { inTauri } from "./chat";

interface Msg {
  role: "user" | "assistant";
  text: string;
  meta?: string;
}

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([
    { role: "assistant", text: "我是 Aivy，您的私人 AI 助理。（壳层骨架，Python 核心就绪后接通）" },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchStatus()
      .then(setStatus)
      .catch(() => setStatus(null)); // 浏览器演示模式：无状态
  }, []);

  // §12.3 全局热键：Alt+Space 唤醒（聚焦输入框）
  useEffect(() => {
    if (!inTauri) return;
    let cleanup: (() => void) | undefined;
    (async () => {
      const gs = await import("@tauri-apps/plugin-global-shortcut");
      await gs.register("Alt+Space", () => {
        inputRef.current?.focus();
      });
      cleanup = () => {
        void gs.unregister("Alt+Space");
      };
    })();
    return () => cleanup?.();
  }, []);

  // §12.6 原生通知：核心未连接时提示
  useEffect(() => {
    if (!inTauri) return;
    (async () => {
      const { isPermissionGranted, requestPermission, sendNotification } =
        await import("@tauri-apps/plugin-notification");
      let granted = await isPermissionGranted();
      if (!granted) granted = (await requestPermission()) === "granted";
      if (granted) {
        sendNotification({ title: "AivyOS", body: "我还在后台运行，随时呼叫我。" });
      }
    })();
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
    }
  }

  return (
    <div className="app">
      <header className="bar">
        <span className="dot" />
        <strong>AivyOS</strong>
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
          placeholder="输入消息，回车发送…（Alt+Space 随时唤醒）"
          disabled={busy}
        />
        <button onClick={handleSend} disabled={busy || !input.trim()}>
          发送
        </button>
      </footer>
    </div>
  );
}
