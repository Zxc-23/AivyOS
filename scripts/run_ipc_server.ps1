# 启动 IPC 服务（供 Tauri 壳层 / 外部客户端调用）
# 用法：powershell -File scripts\run_ipc_server.ps1 [-Mode auto|local|cloud|mock]
param([string]$Mode = "auto")
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if ($Mode -ne "auto") { $env:AIVYOS_LLM_MODE = $Mode }
    python -m aivyos_core.server_entry
} finally {
    Pop-Location
}
