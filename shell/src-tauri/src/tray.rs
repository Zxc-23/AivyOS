// AivyOS 系统托盘（§12.2 / AIVY-DDD-004 §3）— 8 状态图标 + 左键/双击 + 右键菜单 + 拖拽文件
//
// 状态机逻辑在 Python 侧（aivyos_core.tray.state_machine），本模块负责：
// - 8 状态图标切换（set_tray_state 命令，前端/Python 桥接调用）
// - 左键单击：窗口可见性切换（300ms 内二次点击判定为双击 → 语音模式）
// - 右键菜单：§3.3 完整菜单（打开主界面/语音/截屏/暂停恢复/记忆/更新/设置/诊断/退出）
// - 拖拽文件：§3.5 路由事件转发前端（analyze-file）
// - 所有用户操作通过 app.emit("tray-event", …) 通知前端

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Instant;

use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, Runtime};

/// 8 状态图标（§3.1，32px，编译期内嵌）
const TRAY_STATES: [&str; 8] = [
    "idle", "listening", "working", "voice", "updating", "booting", "error", "paused",
];

fn state_icon(state: &str) -> tauri::Result<Image<'static>> {
    let bytes: &'static [u8] = match state {
        "idle" => include_bytes!("../icons/tray/idle_32.png"),
        "listening" => include_bytes!("../icons/tray/listening_32.png"),
        "working" => include_bytes!("../icons/tray/working_32.png"),
        "voice" => include_bytes!("../icons/tray/voice_32.png"),
        "updating" => include_bytes!("../icons/tray/updating_32.png"),
        "booting" => include_bytes!("../icons/tray/booting_32.png"),
        "error" => include_bytes!("../icons/tray/error_32.png"),
        "paused" => include_bytes!("../icons/tray/paused_32.png"),
        _ => include_bytes!("../icons/tray/idle_32.png"),
    };
    Image::from_bytes(bytes).map_err(|e| tauri::Error::Io(std::io::Error::other(e)))
}

fn state_tooltip(state: &str) -> String {
    let map: HashMap<&str, &str> = [
        ("idle", "AivyOS — 待命中"),
        ("listening", "AivyOS — 语音监听中"),
        ("working", "AivyOS — 正在执行任务"),
        ("voice", "AivyOS — 语音对话中"),
        ("updating", "AivyOS — 更新中"),
        ("booting", "AivyOS — 启动恢复中"),
        ("error", "AivyOS — 异常，请关注"),
        ("paused", "AivyOS — 监听已暂停"),
    ]
    .iter()
    .copied()
    .collect();
    map.get(state).copied().unwrap_or("AivyOS").to_string()
}

/// 托盘运行时上下文：当前状态 + 左键单击计时（§3.4 双击 300ms 判定）
struct TrayCtx {
    state: String,
    last_click: Option<Instant>,
}

struct TrayState(Mutex<TrayCtx>);

/// 设置托盘状态（图标 + tooltip）。前端/Python 桥接调用（§12.2）。
#[tauri::command]
pub fn set_tray_state(app: AppHandle, state: String) -> Result<(), String> {
    let valid = TRAY_STATES.contains(&state.as_str());
    let state = if valid { state } else { "idle".to_string() };
    let tray = app.tray_by_id("aivyos-tray").ok_or("托盘未创建")?;
    tray.set_icon(Some(state_icon(&state).map_err(|e| e.to_string())?))
        .map_err(|e| e.to_string())?;
    tray.set_tooltip(Some(state_tooltip(&state))).map_err(|e| e.to_string())?;
    if let Some(managed) = app.try_state::<TrayState>() {
        if let Ok(mut g) = managed.0.lock() {
            g.state = state;
        }
    }
    Ok(())
}

/// 构建右键菜单（§3.3）
fn build_menu<R: Runtime>(app: &tauri::App<R>) -> tauri::Result<Menu<R>> {
    let open = MenuItem::with_id(app, "open", "📋 打开主界面 (Alt+Space)", true, None::<&str>)?;
    let voice = MenuItem::with_id(app, "voice", "🎙️ 语音对话 (Alt+V)", true, None::<&str>)?;
    let screenshot = MenuItem::with_id(app, "screenshot", "📸 截屏分析 (Alt+S)", true, None::<&str>)?;
    let pause = MenuItem::with_id(app, "pause", "⏸️ 暂停监听", true, None::<&str>)?;
    let resume = MenuItem::with_id(app, "resume", "▶️ 恢复监听", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "⚙️ 设置", true, None::<&str>)?;
    let diag = MenuItem::with_id(app, "diag", "📊 诊断信息", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "🚪 退出 AivyOS (Alt+Q)", true, None::<&str>)?;

    let memory_sub = Submenu::with_items(
        app,
        "记忆管理",
        true,
        &[
            &MenuItem::with_id(app, "memory-graph", "📊 查看记忆图谱", true, None::<&str>)?,
            &MenuItem::with_id(app, "memory-clear", "🗑️ 清除短期记忆", true, None::<&str>)?,
            &MenuItem::with_id(app, "memory-export", "📥 导出记忆备份", true, None::<&str>)?,
            &MenuItem::with_id(app, "memory-import", "📤 导入记忆备份", true, None::<&str>)?,
        ],
    )?;
    let update_sub = Submenu::with_items(
        app,
        "更新",
        true,
        &[
            &MenuItem::with_id(app, "update-check", "🔍 检查更新", true, None::<&str>)?,
            &MenuItem::with_id(app, "update-history", "📜 查看更新历史", true, None::<&str>)?,
            &MenuItem::with_id(app, "update-rollback", "⏪ 回滚到上一版本", true, None::<&str>)?,
        ],
    )?;

    Menu::with_items(
        app,
        &[
            &open,
            &voice,
            &screenshot,
            &PredefinedMenuItem::separator(app)?,
            &pause,
            &resume,
            &PredefinedMenuItem::separator(app)?,
            &memory_sub,
            &update_sub,
            &PredefinedMenuItem::separator(app)?,
            &settings,
            &diag,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )
}

fn emit(app: &AppHandle, event: &str, payload: serde_json::Value) {
    let _ = app.emit(event, payload);
}

/// 初始化托盘（§12.2 / §3）
pub fn setup_tray(app: &tauri::App) -> tauri::Result<()> {
    app.manage(TrayState(Mutex::new(TrayCtx {
        state: "booting".to_string(),
        last_click: None,
    })));
    let menu = build_menu(app)?;
    let tray = TrayIconBuilder::with_id("aivyos-tray")
        .icon(state_icon("booting")?)
        .tooltip(state_tooltip("booting"))
        .menu(&menu)
        .show_menu_on_left_click(false) // §1.2 左键不弹菜单
        .on_menu_event(|app, event| {
            let id = event.id().as_ref().to_string();
            emit(app, "tray-menu", serde_json::json!({ "id": id }));
            if id == "quit" {
                app.exit(0);
            }
        })
        .on_tray_icon_event(|tray, event| {
            let app = tray.app_handle();
            match event {
                TrayIconEvent::Click { button: MouseButton::Left, button_state, .. } => {
                    if button_state != MouseButtonState::Up {
                        return;
                    }
                    // §3.4 双击判定：300ms 内二次单击 → 语音模式（Windows 另有原生 DoubleClick）
                    let is_double = {
                        let managed = app.state::<TrayState>();
                        let mut g = managed.0.lock().unwrap();
                        let now = Instant::now();
                        let dbl = g
                            .last_click
                            .map(|t| now.duration_since(t).as_millis() < 300)
                            .unwrap_or(false);
                        g.last_click = Some(now);
                        dbl
                    };
                    emit(
                        app,
                        "tray-click",
                        serde_json::json!({ "double": is_double, "state": tray_state_name(app) }),
                    );
                }
                TrayIconEvent::DoubleClick { button: MouseButton::Left, .. } => {
                    // Windows 原生双击 → 语音模式（§3.4）
                    emit(
                        app,
                        "tray-click",
                        serde_json::json!({ "double": true, "state": tray_state_name(app) }),
                    );
                }
                _ => {}
            }
        })
        .build(app)?;
    let _ = tray;
    Ok(())
}

fn tray_state_name(app: &AppHandle) -> String {
    let state = app.try_state::<TrayState>();
    let Some(state) = state else {
        return "idle".to_string();
    };
    match state.inner().0.try_lock() {
        Ok(g) => g.state.clone(),
        Err(_) => "idle".to_string(),
    }
}
