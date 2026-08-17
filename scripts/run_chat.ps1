# 启动交互式对话（CLI）
# 用法：powershell -File scripts\run_chat.ps1 [-Mode auto|local|cloud|mock]
param([string]$Mode = "auto")
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if ($Mode -ne "auto") { $env:AIVYOS_LLM_MODE = $Mode }
    python -m aivyos_core.cli
} finally {
    Pop-Location
}
