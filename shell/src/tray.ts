// AivyOS 前端 ↔ 托盘/桌面端桥接（§12.2 系统托盘 / §12.3 全局热键 / §12.5 自启）
// Rust 侧 tray.rs：8 状态图标切换 + 右键菜单 + 左键/双击 + 拖拽事件

import { inTauri } from "./chat";

/** 托盘 8 状态（§3.1，与 aivyos_core.tray.state_machine 对齐） */
export type TrayStateName =
  | "idle"
  | "listening"
  | "working"
  | "voice"
  | "updating"
  | "booting"
  | "error"
  | "paused";

const TRAY_STATES: TrayStateName[] = [
  "idle", "listening", "working", "voice", "updating", "booting", "error", "paused",
];

/** 设置托盘状态（图标 + tooltip）→ Rust set_tray_state 命令 */
export async function setTrayState(state: TrayStateName): Promise<void> {
  if (!inTauri) return;
  if (!TRAY_STATES.includes(state)) return;
  const { invoke } = await import("@tauri-apps/api/core");
  try {
    await invoke("set_tray_state", { state });
  } catch {
    // 托盘未就绪时静默（演示/浏览器模式）
  }
}

/** 监听托盘事件（右键菜单 / 单击双击），返回取消函数 */
export async function onTrayEvent(handler: (ev: TrayFrontendEvent) => void): Promise<() => void> {
  if (!inTauri) return () => undefined;
  const { listen } = await import("@tauri-apps/api/event");
  const unlisteners = await Promise.all([
    listen("tray-menu", (e) => handler({ kind: "menu", id: String((e.payload as { id?: string })?.id ?? "") })),
    listen("tray-click", (e) => {
      const p = e.payload as { double?: boolean; state?: string };
      handler({ kind: "click", double: p?.double === true, state: p?.state ?? "idle" });
    }),
  ]);
  return () => unlisteners.forEach((u) => u());
}

export type TrayFrontendEvent =
  | { kind: "menu"; id: string }
  | { kind: "click"; double: boolean; state: string };

/** 窗口拖拽文件（§3.5 拖拽交互；Tauri 托盘不提供 drop 事件，用窗口级 onDragDropEvent） */
export async function onWindowFileDrop(handler: (paths: string[]) => void): Promise<() => void> {
  if (!inTauri) return () => undefined;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  const win = getCurrentWindow();
  const unlisten = await win.onDragDropEvent((event) => {
    if (event.payload.type === "drop") {
      handler(event.payload.paths);
    }
  });
  return unlisten;
}

/** 窗口关闭 → 最小化到托盘（§1.4 后台常驻） */
export async function setupCloseToTray(): Promise<() => void> {
  if (!inTauri) return () => undefined;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  const win = getCurrentWindow();
  const unlisten = await win.onCloseRequested(async (event) => {
    event.preventDefault(); // 阻止真正关闭
    await win.hide(); // 隐藏到托盘（§1.4）
    const { isPermissionGranted, requestPermission, sendNotification } =
      await import("@tauri-apps/plugin-notification");
    let granted = await isPermissionGranted();
    if (!granted) granted = (await requestPermission()) === "granted";
    if (granted) {
      sendNotification({ title: "AivyOS", body: "我还在后台运行，随时呼叫我。" });
    }
  });
  return unlisten;
}

/** 开机自启（§1.5）：已启用则保持，否则开启 */
export async function setupAutostart(): Promise<void> {
  if (!inTauri) return;
  const { isEnabled, enable } = await import("@tauri-apps/plugin-autostart");
  try {
    const enabled = await isEnabled();
    if (!enabled) await enable();
  } catch {
    // 平台不支持时静默降级
  }
}

/** 全局热键（§1.3）：Alt+Space 唤醒 / Alt+V 语音 / Alt+S 截屏 / Alt+Q 退出 */
export async function setupHotkeys(handlers: {
  wake?: () => void;
  voice?: () => void;
  screenshot?: () => void;
  quit?: () => void;
}): Promise<() => void> {
  if (!inTauri) return () => undefined;
  const { register, unregister } = await import("@tauri-apps/plugin-global-shortcut");
  const keys: [string, (() => void) | undefined][] = [
    ["Alt+Space", handlers.wake],
    ["Alt+V", handlers.voice],
    ["Alt+S", handlers.screenshot],
    ["Alt+Q", handlers.quit],
  ];
  const registered: string[] = [];
  for (const [key, fn] of keys) {
    if (!fn) continue;
    try {
      await register(key, fn);
      registered.push(key);
    } catch {
      // 单个热键失败不阻断其他
    }
  }
  return () => {
    registered.forEach((k) => void unregister(k));
  };
}
