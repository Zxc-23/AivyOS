// AivyOS 壳层 Rust 侧（Tauri 2.0）— Phase 1 Week 1 骨架
//
// 后续里程碑：
// - Week 2+：启动/守护 Python 核心子进程（aivyos_core.server_entry）
// - Week 3+：经 Named Pipe/TCP 将 bridge 调用转发给 Python 核心（§12.1 IPC）
// - Phase 3：托盘 8 状态机、全局热键、自动更新（§12/§13/§15）

use serde_json::{json, Value};

/// 桥接命令：前端 invoke("bridge", {method, params}) → Python 核心
/// Week 1 为占位实现，返回明确的"未接通"错误。
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
        .invoke_handler(tauri::generate_handler![bridge, ping])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
