# ============================================================
# AivyOS one-click launcher
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\start_aivyos.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start_aivyos.ps1 -Web
#   powershell -ExecutionPolicy Bypass -File scripts\start_aivyos.ps1 -Rebuild
#   powershell -ExecutionPolicy Bypass -File scripts\start_aivyos.ps1 -Mode mock
# ============================================================
param(
    [switch]$Web,
    [switch]$Rebuild,
    [string]$Mode = "auto"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "   AivyOS Launcher" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  Root: $root"
    Write-Host "  LLM mode: $Mode"
    Write-Host ""

    # ---------- 1. environment check ----------
    Write-Host "[1/4] Environment check..." -ForegroundColor Yellow

    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Host "  [x] Python not found. Install Python 3.10+ first." -ForegroundColor Red
        exit 1
    }
    Write-Host "  [ok] Python: $($py.Source)" -ForegroundColor Green

    $hasCore = python -c "import aivyos_core; print('yes')" 2>$null
    if ($hasCore -ne "yes") {
        Write-Host "  [x] aivyos_core not found. Run from repo root." -ForegroundColor Red
        exit 1
    }

    # Ollama probe (optional, informational only)
    $ollama = $false
    try {
        $ollama = Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue -InformationLevel Quiet
    } catch {
        $ollama = $false
    }
    if ($ollama) {
        Write-Host "  [ok] Ollama running (127.0.0.1:11434)" -ForegroundColor Green
    } else {
        Write-Host "  [i] Ollama not running - local models unavailable. Cloud/mock modes still work." -ForegroundColor DarkYellow
    }

    # Core port probe (already running?)
    $coreAlive = $false
    try {
        $coreAlive = Test-NetConnection -ComputerName 127.0.0.1 -Port 31701 -WarningAction SilentlyContinue -InformationLevel Quiet
    } catch {
        $coreAlive = $false
    }

    # ---------- 2. mode branch ----------
    if ($Web) {
        # ---- Web mode: Python core + Vite dev server + browser ----
        Write-Host "[2/4] Starting Python core (IPC :31701)..." -ForegroundColor Yellow
        if (-not $coreAlive) {
            if ($Mode -ne "auto") { $env:AIVYOS_LLM_MODE = $Mode }
            Start-Process -FilePath "python" -ArgumentList "-m", "aivyos_core.server_entry", "--mode", $Mode -WorkingDirectory $root -WindowStyle Minimized
            Start-Sleep -Seconds 3
        } else {
            Write-Host "  [ok] Core already running, skip." -ForegroundColor Green
        }

        Write-Host "[3/4] Starting Vite dev server..." -ForegroundColor Yellow
        if (-not (Test-Path "shell\node_modules")) {
            Write-Host "  [i] First run: installing frontend deps..." -ForegroundColor DarkYellow
            Push-Location shell
            npm.cmd install 2>$null
            Pop-Location
        }
        $vite = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory (Join-Path $root "shell") -PassThru -WindowStyle Minimized
        Start-Sleep -Seconds 6

        Write-Host "[4/4] Opening browser..." -ForegroundColor Yellow
        Start-Process "http://127.0.0.1:1420"
        Write-Host ""
        Write-Host "  Web mode ready: http://127.0.0.1:1420" -ForegroundColor Green
        Write-Host "  Closing this window stops nothing; stop Vite and Python manually." -ForegroundColor DarkGray
        Write-Host "  Press Ctrl+C to exit." -ForegroundColor DarkGray
        try { Wait-Process -Id $vite.Id -ErrorAction SilentlyContinue } catch { }
        exit 0
    }

    # ---- Desktop mode (Tauri) ----
    $exe = Join-Path $root "shell\src-tauri\target\debug\aivyos-shell.exe"

    if ($Rebuild -or -not (Test-Path "shell\dist\index.html")) {
        Write-Host "[2/4] Building frontend (npm run build)..." -ForegroundColor Yellow
        if (-not (Test-Path "shell\node_modules")) {
            Write-Host "  [i] First run: installing frontend deps..." -ForegroundColor DarkYellow
            Push-Location shell
            npm.cmd install 2>$null
            Pop-Location
        }
        Push-Location shell
        npm.cmd run build
        $buildExit = $LASTEXITCODE
        Pop-Location
        if ($buildExit -ne 0) {
            Write-Host "  [x] Frontend build failed." -ForegroundColor Red
            exit 1
        }
        Write-Host "  [ok] Frontend build done." -ForegroundColor Green
    } else {
        Write-Host "[2/4] dist exists, skip build." -ForegroundColor Green
    }

    if (Test-Path $exe) {
        # ---- Launch built desktop shell ----
        Write-Host "[3/4] Launching desktop app (aivyos-shell.exe)..." -ForegroundColor Yellow
        if ($Mode -ne "auto") { $env:AIVYOS_LLM_MODE = $Mode }
        Write-Host "[4/4] Done! AivyOS starting (core auto-spawned)." -ForegroundColor Green
        Write-Host ""
        Write-Host "  Note: first launch takes a few seconds for core warm-up." -ForegroundColor DarkGray
        & $exe
        exit $LASTEXITCODE
    } else {
        # ---- Dev mode (tauri dev, needs Rust toolchain) ----
        Write-Host "[3/4] No built app found, using dev mode (npm run tauri dev)..." -ForegroundColor Yellow
        Write-Host "  [i] First run compiles the Rust shell, may take minutes." -ForegroundColor DarkYellow
        if ($Mode -ne "auto") { $env:AIVYOS_LLM_MODE = $Mode }
        Push-Location shell
        npm.cmd run tauri dev
        Pop-Location
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
