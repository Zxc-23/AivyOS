// AivyOS 壳层 Rust 侧（Tauri 2.0）— 对齐 §12-15 桌面端设计
//
// 已接入：全局热键（§12.3）、原生通知（§12.6）、开机自启（§12.5）、自动更新（§13）、
//         系统托盘 8 状态机（§12.2/§15，tray.rs：图标切换/左键双击/右键菜单/拖拽文件）
// 桥接：bridge 命令 → TCP 回环（127.0.0.1:31701）→ Python 核心（§16.2 JSON-RPC + 长度前缀帧）
//
// 架构（actor 模式）：
//   ┌─────────────────┐  mpsc   ┌───────────────────────────┐  TCP  ┌──────────────┐
//   │ bridge command  │ ──────▶ │ BridgeTask (tokio task)   │ ─────▶│ Python IPC   │
//   │ (sync -> block) │◀─────── │ 读帧/写帧/分发响应       │◀────── │ server_entry │
//   └─────────────────┘ oneshot └───────────────────────────┘       └──────────────┘

mod tray;

use std::path::PathBuf;
use std::sync::Arc;

use serde_json::{json, Value};
use tauri::Emitter;
use tauri::Manager;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::sync::{mpsc, oneshot, Mutex as AsyncMutex};

/// IPC 地址（与 aivyos_core.ipc.server 默认一致：文档 §16.2）
const IPC_HOST: &str = "127.0.0.1";
const IPC_PORT: u16 = 31701;
/// 帧最大长度（协议约束：16MB，aivyos_core.ipc.protocol MAX_FRAME=16*1024*1024）
const MAX_FRAME: usize = 16 * 1024 * 1024;
/// 等待 Python 核心 TCP 就绪的总超时（秒）
const CORE_BOOT_TIMEOUT_SECS: u64 = 30;
/// 单个 IPC 调用超时（秒）—— 避免前端挂死
const IPC_CALL_TIMEOUT_SECS: u64 = 120;
/// 长任务 IPC 调用超时（秒）：workbench.* 双模型 CLI 串行可能跑 10 分钟以上
const IPC_LONG_CALL_TIMEOUT_SECS: u64 = 900;

/// 按 method 前缀选择超时：workbench 双模型任务走长超时，其余默认
fn ipc_timeout_secs(method: &str) -> u64 {
    if method.starts_with("workbench.") {
        IPC_LONG_CALL_TIMEOUT_SECS
    } else {
        IPC_CALL_TIMEOUT_SECS
    }
}

/// BridgeTask 接收的请求：(id, json_rpc_body_bytes, 响应一次性 sender)
type ReqEnvelope = (u64, Vec<u8>, oneshot::Sender<Result<Value, String>>);

// ---------- Python 路径发现 ----------

/// 发现 python 可执行路径：项目虚拟环境 → which python/python3 → Windows 常见位置
fn find_python() -> Result<PathBuf, String> {
    let cwd = std::env::current_dir().ok();
    // 1) 项目虚拟环境（aivyos/ 目录下的 .venv\Scripts\python.exe）
    if let Some(cwd) = cwd.as_ref() {
        // Tauri 的 cwd 通常为 shell/ 或 shell/src-tauri
        let roots = [
            cwd.clone(),
            cwd.parent().map(|p| p.to_path_buf()).unwrap_or_default(),
            cwd.parent()
                .and_then(|p| p.parent())
                .map(|p| p.to_path_buf())
                .unwrap_or_default(),
        ];
        for r in roots {
            for rel in [".venv\\Scripts\\python.exe", "venv\\Scripts\\python.exe"] {
                let c = r.join(rel);
                if c.exists() {
                    return Ok(c);
                }
            }
        }
    }
    // 2) PATH（过滤掉 WindowsApps 重定向器）
    for name in &["python", "python3"] {
        if let Ok(p) = which::which(name) {
            // 跳过 Microsoft Store 重定向器，它不转发环境变量
            if !p.to_string_lossy().contains("WindowsApps") {
                return Ok(p);
            }
        }
    }
    // 3) Windows 常见安装位置（含 Python 3.14）
    let home = std::env::var("USERPROFILE")
        .unwrap_or_else(|_| "C:\\Users\\25155".into());
    for p in [
        // Python 3.14 自定义安装路径
        format!("{home}\\AppData\\Local\\Python\\bin\\python.exe"),
        format!("{home}\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe"),
        // TRAE 自带 Python
        format!("{home}\\AppData\\Roaming\\TRAE SOLO CN\\ModularData\\ai-agent\\vm\\tools\\python\\python.exe"),
        format!("{home}\\AppData\\Roaming\\TRAE SOLO CN\\ModularData\\ai-agent\\vm\\tools\\bin\\python.exe"),
        // 标准安装路径
        format!("{home}\\AppData\\Local\\Programs\\Python\\Python314\\python.exe"),
        format!("{home}\\AppData\\Local\\Programs\\Python\\Python313\\python.exe"),
        format!("{home}\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"),
        format!("{home}\\AppData\\Local\\Programs\\Python\\Python311\\python.exe"),
        format!("{home}\\AppData\\Local\\Programs\\Python\\Python310\\python.exe"),
        "C:\\Python314\\python.exe".into(),
        "C:\\Python313\\python.exe".into(),
        "C:\\Python312\\python.exe".into(),
        "C:\\Python311\\python.exe".into(),
        "C:\\Python310\\python.exe".into(),
    ] {
        let pb = PathBuf::from(&p);
        if pb.exists() {
            return Ok(pb);
        }
    }
    Err("未找到 Python 可执行文件，请确保 python 在 PATH 或使用项目虚拟环境 (.venv)".into())
}

// ---------- 帧编解码（aivyos_core.ipc.protocol 对齐：大端 4 字节长度前缀 + UTF-8 JSON）----------

/// 编码一个 JSON 对象为长度前缀帧
fn encode_frame(obj: &Value) -> Result<Vec<u8>, String> {
    let data = serde_json::to_vec(obj).map_err(|e| e.to_string())?;
    if data.len() > MAX_FRAME {
        return Err(format!("帧过大 ({} bytes > 16MB)", data.len()));
    }
    let len = (data.len() as u32).to_be_bytes();
    let mut out = Vec::with_capacity(4 + data.len());
    out.extend_from_slice(&len);
    out.extend_from_slice(&data);
    Ok(out)
}

/// 从 reader 精确读一帧（先 4 字节大端长度，再读 payload，最后 serde_json 反序列化）
async fn read_frame(reader: &mut (impl AsyncReadExt + Unpin)) -> Result<Value, String> {
    let mut hdr = [0u8; 4];
    reader
        .read_exact(&mut hdr)
        .await
        .map_err(|e| format!("读帧头失败: {e}"))?;
    let n = u32::from_be_bytes(hdr) as usize;
    if n > MAX_FRAME {
        return Err(format!("帧长度越界: {n} > {MAX_FRAME}"));
    }
    let mut buf = vec![0u8; n];
    reader
        .read_exact(&mut buf)
        .await
        .map_err(|e| format!("读帧体失败: {e}"))?;
    serde_json::from_slice(&buf).map_err(|e| format!("解析 JSON 失败: {e}"))
}

// ---------- BridgeTask actor：独占 TCP 读写，select! 同时处理请求收发 ----------

async fn bridge_task_actor(
    stream: TcpStream,
    mut rx: mpsc::Receiver<ReqEnvelope>,
    app: tauri::AppHandle,
) {
    let (mut reader, mut writer) = stream.into_split();
    let mut pending: std::collections::HashMap<u64, oneshot::Sender<Result<Value, String>>> =
        std::collections::HashMap::new();

    loop {
        tokio::select! {
            // 入队新请求：写帧 + 注册 pending
            Some((id, bytes, reply)) = rx.recv() => {
                pending.insert(id, reply);
                if let Err(e) = writer.write_all(&bytes).await {
                    eprintln!("[AivyOS] 写 IPC 帧失败(id={id}): {e}");
                    if let Some(s) = pending.remove(&id) {
                        let _ = s.send(Err(format!("写 TCP 失败: {e}")));
                    }
                    break;
                }
                if let Err(e) = writer.flush().await {
                    eprintln!("[AivyOS] TCP flush 失败(id={id}): {e}");
                    if let Some(s) = pending.remove(&id) {
                        let _ = s.send(Err(format!("TCP flush 失败: {e}")));
                    }
                    break;
                }
            }
            // 持续读响应帧：找到对应 id 回复
            result = read_frame(&mut reader) => {
                match result {
                    Ok(frame) => {
                        let Some(id_val) = frame.get("id") else {
                            // Notification 帧（服务端主动推送）— 转为 Tauri 事件
                            let method = frame.get("method").and_then(|m| m.as_str()).unwrap_or("unknown");
                            let params = frame.get("params").cloned().unwrap_or(Value::Null);
                            let event_name = format!("ipc:{}", method);
                            if let Err(e) = app.emit::<Value>(&event_name, params.clone()) {
                                eprintln!("[AivyOS] 发射事件失败({event_name}): {e}");
                            } else {
                                println!("[AivyOS] 📡 收到推送事件: {event_name}");
                            }
                            continue;
                        };
                        let id: u64 = match id_val {
                            Value::Number(n) => n.as_u64().unwrap_or(0),
                            _ => 0,
                        };
                        if let Some(sender) = pending.remove(&id) {
                            let resp: Result<Value, String> = if let Some(err) = frame.get("error") {
                                let msg = err.get("message").and_then(|m| m.as_str()).unwrap_or("unknown");
                                Err(msg.to_string())
                            } else {
                                Ok(frame.get("result").cloned().unwrap_or(Value::Null))
                            };
                            let _ = sender.send(resp);
                        }
                    }
                    Err(e) => {
                        eprintln!("[AivyOS] 读 IPC 帧失败: {e}");
                        for (_, s) in pending.drain() {
                            let _ = s.send(Err(format!("Python 核心断开: {e}")));
                        }
                        break;
                    }
                }
            }
            else => break,
        }
    }

    // actor 退出：pending 全部报错
    for (_, s) in pending.drain() {
        let _ = s.send(Err("Python 核心连接已断开".into()));
    }
    eprintln!("[AivyOS] IPC bridge actor 已退出");
}

// ---------- CoreHandle：全局共享状态（被 tauri::State 管理）----------

struct CoreHandleInner {
    /// actor 的发送端：setup 后 install 填 Some
    tx: AsyncMutex<Option<mpsc::Sender<ReqEnvelope>>>,
    /// id 自增（atomic，无锁）
    next_id: std::sync::atomic::AtomicU64,
    /// 是否就绪（setup 完成后置 true）
    ready: std::sync::atomic::AtomicBool,
    /// 保存 Python 子进程句柄，应用退出时自动 drop + kill
    _child: AsyncMutex<Option<std::process::Child>>,
}

#[derive(Clone)]
struct CoreHandle(Arc<CoreHandleInner>);

impl CoreHandle {
    fn new() -> Self {
        Self(Arc::new(CoreHandleInner {
            tx: AsyncMutex::const_new(None),
            next_id: std::sync::atomic::AtomicU64::new(1),
            ready: std::sync::atomic::AtomicBool::new(false),
            _child: AsyncMutex::const_new(None),
        }))
    }

    /// 安装 actor 发送端 + 保存子进程句柄
    async fn install(&self, tx: mpsc::Sender<ReqEnvelope>, child: Option<std::process::Child>) {
        *self.0.tx.lock().await = Some(tx);
        *self.0._child.lock().await = child;
        self.0
            .ready
            .store(true, std::sync::atomic::Ordering::SeqCst);
    }

    /// 发送一个 JSON-RPC 请求并等待响应（async command 使用，不阻塞主线程）
    async fn call(&self, method: &str, params: Value) -> Result<Value, String> {
        if !self.0.ready.load(std::sync::atomic::Ordering::SeqCst) {
            return Err(
                "Python 核心尚未就绪（稍后再试；或手动在 f:\\AivyOS\\aivyos 下执行 `python -m aivyos_core.server_entry --mode auto`）"
                    .into(),
            );
        }
        let id = self
            .0
            .next_id
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let body = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });
        let frame_bytes = encode_frame(&body)?;

        let inner = Arc::clone(&self.0);
        let method_owned = method.to_string();
        let tx_guard = inner.tx.lock().await;
        let Some(tx) = tx_guard.as_ref() else {
            return Err("Python 核心尚未就绪：actor tx 为空".into());
        };
        let (resp_tx, resp_rx) = oneshot::channel::<Result<Value, String>>();
        tx.send((id, frame_bytes, resp_tx))
            .await
            .map_err(|_| "Python 核心 IPC actor 已退出")?;
        drop(tx_guard);

        match tokio::time::timeout(
            std::time::Duration::from_secs(ipc_timeout_secs(method)),
            resp_rx,
        )
        .await
        {
            Ok(Ok(res)) => res,
            Ok(Err(_)) => Err(format!(
                "IPC(id={id}, method={method_owned}) 响应通道被关闭"
            )),
            Err(_) => Err(format!(
                "IPC(id={id}, method={method_owned}) 超时（> {}s）",
                ipc_timeout_secs(method)
            )),
        }
    }
}

// ---------- Tauri command 实现 ----------

/// 桥接命令：前端 invoke("bridge", {method, params}) → JSON-RPC over TCP → Python 核心
/// async command：在 tokio runtime 执行，不阻塞主线程（避免 voice.turn 等长调用卡 UI）
#[tauri::command]
async fn bridge(
    method: String,
    params: Value,
    state: tauri::State<'_, CoreHandle>,
) -> Result<Value, String> {
    state.call(&method, params).await
}

#[tauri::command]
fn ping() -> Value {
    json!({ "pong": true, "shell": "aivyos-shell" })
}

/// 热重启 Python 核心：优雅关闭（core.shutdown）→ 超时强杀 → 重新拉起并重连。
/// 更新安装后应用新版本用；UI 进程不退出，实现"热更新生效"。
#[tauri::command]
async fn restart_core(
    app: tauri::AppHandle,
    state: tauri::State<'_, CoreHandle>,
) -> Result<Value, String> {
    // 外部核心（非本应用 spawn，如手动启动的服务）无法由我们重启
    let owns_child = state.0._child.lock().await.is_some();
    if !owns_child {
        return Err("当前 Python 核心由外部进程提供（非本应用拉起），请手动重启该进程".into());
    }

    // 优雅关闭：核心响应后 0.3s 自行退出（见 server_entry core.shutdown）；失败则走下方强杀
    let _ = tokio::time::timeout(
        std::time::Duration::from_secs(3),
        state.call("core.shutdown", json!({})),
    )
    .await;

    // 标记未就绪，restart 期间拒绝新调用
    state.0.ready.store(false, std::sync::atomic::Ordering::SeqCst);

    // 等端口释放（最多 5s）
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    loop {
        let probe = tokio::time::timeout(
            std::time::Duration::from_millis(300),
            TcpStream::connect((IPC_HOST, IPC_PORT)),
        )
        .await;
        if !matches!(probe, Ok(Ok(_))) {
            break; // 连不上 = 核心已退出
        }
        if std::time::Instant::now() > deadline {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    }

    // 子进程仍在（优雅关闭失败）则强杀
    {
        let mut guard = state.0._child.lock().await;
        if let Some(mut c) = guard.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }

    // 重新拉起 + 重连（boot_core 内含最多 30s 端口等待）
    boot_core(state.inner().clone(), app).await;

    if state.0.ready.load(std::sync::atomic::Ordering::SeqCst) {
        Ok(json!({ "ok": true }))
    } else {
        Err("核心重启后未能就绪，请查看终端日志".into())
    }
}

// ---------- 核心进程拉起 + 桥接 actor 初始化 ----------

/// 找 Python → （端口未占用时）spawn 核心 → 轮询端口就绪 → 安装 actor。
/// 初次启动与热重启（restart_core）共用。
async fn boot_core(handle: CoreHandle, app_handle: tauri::AppHandle) {
    // 找 python
    let python = match find_python() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("[AivyOS] 找 Python 失败: {e}");
            eprintln!("[AivyOS] 提示：请在 f:\\AivyOS\\aivyos 目录执行 `python -m aivyos_core.server_entry --mode auto`");
            return;
        }
    };
    println!("[AivyOS] Python: {}", python.display());

    // 探测端口是否已监听
    let port_alive = tokio::time::timeout(
        std::time::Duration::from_millis(500),
        TcpStream::connect((IPC_HOST, IPC_PORT)),
    )
    .await;

    let child: Option<std::process::Child> =
        if matches!(port_alive, Ok(Ok(_))) {
            println!("[AivyOS] 端口 {}:{} 已在监听，复用现有进程", IPC_HOST, IPC_PORT);
            None
        } else {
            // 向上查找包含 aivyos_core/ 的目录作为 Python 根路径
            // cargo run 时 cwd 为 shell/src-tauri，需往上 2 层到达 aivyos/
            let cwd = std::env::current_dir().unwrap_or_default();
            let mut aivyos_root = cwd.clone();
            for _ in 0..5 {
                if aivyos_root.join("aivyos_core").is_dir() {
                    break;
                }
                if !aivyos_root.pop() {
                    break;
                }
            }

            // 设置 PYTHONPATH 环境变量，确保 Python 能找到 aivyos_core 模块
            let pythonpath = std::env::var("PYTHONPATH")
                .unwrap_or_default();
            let mut new_pythonpath = aivyos_root.to_string_lossy().to_string();
            if !pythonpath.is_empty() {
                new_pythonpath.push(';');
                new_pythonpath.push_str(&pythonpath);
            }
            println!("[AivyOS] PYTHONPATH = {}", new_pythonpath);
            println!("[AivyOS] cwd = {}", aivyos_root.display());

            match std::process::Command::new(&python)
                .args(["-m", "aivyos_core.server_entry", "--mode", "auto"])
                .current_dir(&aivyos_root)
                .env("PYTHONPATH", &new_pythonpath)
                .stdout(std::process::Stdio::inherit())
                .stderr(std::process::Stdio::inherit())
                .spawn()
            {
                Ok(c) => {
                    println!("[AivyOS] Python 核心 PID={}，等待端口就绪…", c.id());
                    Some(c)
                }
                Err(e) => {
                    eprintln!("[AivyOS] spawn Python 核心失败: {e}");
                    return;
                }
            }
        };

    // 轮询端口（最多 30s）
    let deadline = std::time::Instant::now()
        + std::time::Duration::from_secs(CORE_BOOT_TIMEOUT_SECS);
    let stream = loop {
        if std::time::Instant::now() > deadline {
            eprintln!(
                "[AivyOS] 等待 IPC 端口超时: {}:{}（请检查 Python 核心是否正常启动）",
                IPC_HOST, IPC_PORT
            );
            return;
        }
        match tokio::time::timeout(
            std::time::Duration::from_secs(1),
            TcpStream::connect((IPC_HOST, IPC_PORT)),
        )
        .await
        {
            Ok(Ok(s)) => break s,
            _ => tokio::time::sleep(std::time::Duration::from_millis(300)).await,
        }
    };

    // 启动 actor：创建 (tx, rx)，把 tx 放进 CoreHandle
    let (tx, rx) = mpsc::channel::<ReqEnvelope>(128);
    handle.install(tx, child).await;
    println!(
        "[AivyOS] ✅ 桥接就绪（tcp {}:{}），前端输入框可立即使用",
        IPC_HOST, IPC_PORT
    );

    let bridge_app_handle = app_handle.clone();
    tauri::async_runtime::handle().spawn(async move {
        bridge_task_actor(stream, rx, bridge_app_handle).await;
    });
}

// ---------- 主入口 ----------

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[allow(unused_mut)]
    let mut builder = tauri::Builder::default()
        // §12.5 开机自启
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        // §12.6 原生通知
        .plugin(tauri_plugin_notification::init())
        // §12.3 全局热键（Alt+Space 等由前端注册）
        .plugin(tauri_plugin_global_shortcut::Builder::new().build());

    // §13 自动更新（仅生产环境启用；dev 环境端点不存在会导致崩溃）
    #[cfg(not(debug_assertions))]
    {
        builder = builder.plugin(tauri_plugin_updater::Builder::new().build());
    }

    builder
        .setup(|app| {
            let rt = tauri::async_runtime::handle();
            let handle = CoreHandle::new();
            tray::setup_tray(app)?;
            app.manage(handle.clone());
            let app_handle = app.handle().clone();

            // 后台启动 Python 核心 & bridge actor（不阻塞 setup）
            rt.spawn(async move {
                boot_core(handle, app_handle).await;
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![bridge, ping, restart_core, tray::set_tray_state])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
