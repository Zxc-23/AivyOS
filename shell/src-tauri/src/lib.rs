// AivyOS 壳层 Rust 侧（Tauri 2.0）— 对齐 §12-15 桌面端设计
//
// 已接入：全局热键（§12.3）、原生通知（§12.6）、开机自启（§12.5）、自动更新（§13）、
//         系统托盘 8 状态机（§12.2/§15，tray.rs：图标切换/左键双击/右键菜单/拖拽文件）
// 桥接：bridge 命令将前端调用转发 Python 核心（§12.1 IPC，Named Pipe/TCP）

mod tray;

use serde_json::{json, Value};

/// 桥接命令：前端 invoke("bridge", {method, params}) → Python 核心
/// 当前为占位实现；Phase 2 接通 Named Pipe/TCP（aivyos_core.server_entry）。
#[tauri::command]
fn bridge(method: String, params: Value) -> Result<Value, String> {
    let _ = params;
    Err(format!(
        "IPC bridge 尚未接通 Python 核心（method={method}）。请先启动 `python -m aivyos_core.server_entry`。"
    ))
}

#[tauri::command]
fn ping() -> Value {
    json!({ "pong": true, "shell": "aivyos-shell" })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // §12.5 开机自启
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        // §12.6 原生通知
        .plugin(tauri_plugin_notification::init())
        // §12.3 全局热键（Alt+Space 等由前端注册）
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        // §13 自动更新（端点见 tauri.conf.json plugins.updater.endpoints）
        .plugin(tauri_plugin_updater::Builder::new().build())
        // §12.2 系统托盘（setup 中创建 TrayIcon；状态切换经 set_tray_state 命令）
        .setup(|app| {
            tray::setup_tray(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![bridge, ping, tray::set_tray_state])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
