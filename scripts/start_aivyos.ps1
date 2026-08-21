# ============================================================
# AivyOS one-click launcher
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\start_aivyos.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start_aivyos.ps1 -Web
#   powershell -ExecutionPolicy Bypass -File scripts\start_aivyos.ps1 -Build
#   powershell -ExecutionPolicy Bypass -File scripts\start_aivyos.ps1 -Rebuild
#   powershell -ExecutionPolicy Bypass -File scripts\start_aivyos.ps1 -Mode mock
# ============================================================
param(
    [switch]$Web,
    [switch]$Build,
    [switch]$Rebuild,
    [string]$Mode = "auto"
)

$ErrorActionPreference = "Stop"

# ---- process cleanup registry (terminal close / script exit) ----
# PIDs spawned by this script (python core, vite, desktop app).
# Stored in $global so the PowerShell.Exiting action (separate runspace) can read them.
$global:AivyCleanupPids = @()

function Add-AivyPid([int]$PidToTrack) {
    if ($PidToTrack -gt 0 -and $global:AivyCleanupPids -notcontains $PidToTrack) {
        $global:AivyCleanupPids += $PidToTrack
    }
}

function Stop-AivyCleanup {
    # 1) kill processes this script spawned
    foreach ($p in $global:AivyCleanupPids) {
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
    # 2) kill all desktop app instances
    Get-Process -Name "aivyos-shell" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    # 3) kill core listening on 31701 (spawned by Tauri as its child)
    try {
        Get-NetTCPConnection -LocalPort 31701 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch { }
    Start-Sleep -Milliseconds 500
}

# Register exit hook: fires when the terminal window is closed or the script ends.
# Action runs in its own runspace, so it reads $global:AivyCleanupPids.
Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    foreach ($p in $global:AivyCleanupPids) {
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
    Get-Process -Name "aivyos-shell" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    try {
        Get-NetTCPConnection -LocalPort 31701 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch { }
} | Out-Null

# ---- auto-locate repo root (works from any cwd) ----
# 1) explicit override via -Root param
# 2) fall back to script parent, then walk up until aivyos_core found
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = $null
if (Test-Path (Join-Path $scriptDir "aivyos_core")) {
    $root = $scriptDir
} else {
    $cur = $scriptDir
    while ($cur) {
        if (Test-Path (Join-Path $cur "aivyos_core")) { $root = $cur; break }
        $parent = Split-Path -Parent $cur
        if ($parent -eq $cur) { break }
        $cur = $parent
    }
}
if (-not $root) {
    Write-Host "[x] Cannot locate aivyos repo root (aivyos_core not found above script)." -ForegroundColor Red
    exit 1
}
$root = (Resolve-Path $root).Path

Push-Location $root
try {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "   AivyOS Launcher" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  Root: $root"
    Write-Host "  LLM mode: $Mode"
    if ($Build) { Write-Host "  Action: BUILD release desktop app" -ForegroundColor Magenta }
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
            $coreProc = Start-Process -FilePath "python" -ArgumentList "-m", "aivyos_core.server_entry", "--mode", $Mode -WorkingDirectory $root -WindowStyle Minimized -PassThru
            Add-AivyPid $coreProc.Id
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
        Add-AivyPid $vite.Id
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
    $debugExe = Join-Path $root "shell\src-tauri\target\debug\aivyos-shell.exe"
    $releaseExe = Join-Path $root "shell\src-tauri\target\release\aivyos-shell.exe"

    # frontend deps check (shared by build paths)
    function Ensure-NpmDeps {
        if (-not (Test-Path (Join-Path $root "shell\node_modules"))) {
            Write-Host "  [i] Installing frontend deps..." -ForegroundColor DarkYellow
            Push-Location (Join-Path $root "shell")
            npm.cmd install 2>$null
            Pop-Location
        }
    }

    # ---------- -Build: compile release desktop app ----------
    if ($Build) {
        Write-Host "[2/4] Building RELEASE desktop app (tauri build)..." -ForegroundColor Magenta
        Write-Host "  [i] This compiles Rust + bundles frontend, may take several minutes." -ForegroundColor DarkYellow

        # Stop running AivyOS instances first (Windows locks the exe, build cannot overwrite)
        $running = Get-Process -Name "aivyos-shell" -ErrorAction SilentlyContinue
        if ($running) {
            Write-Host "  [i] Stopping $($running.Count) running AivyOS instance(s) to unlock the exe..." -ForegroundColor DarkYellow
            $running | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            $still = Get-Process -Name "aivyos-shell" -ErrorAction SilentlyContinue
            if ($still) {
                Write-Host "  [x] Could not stop $($still.Count) AivyOS instance(s) (access denied)." -ForegroundColor Red
                Write-Host "      Please close the AivyOS window (or taskkill /IM aivyos-shell.exe /F) and rerun." -ForegroundColor Red
                exit 1
            }
            Write-Host "  [ok] Stopped. Building..." -ForegroundColor Green
        }

        # Rust toolchain check
        $cargo = Get-Command cargo -ErrorAction SilentlyContinue
        if (-not $cargo) {
            Write-Host "  [x] cargo not found. Install Rust: https://rustup.rs" -ForegroundColor Red
            exit 1
        }
        Write-Host "  [ok] cargo: $($cargo.Source)" -ForegroundColor Green

        Ensure-NpmDeps

        if ($Mode -ne "auto") { $env:AIVYOS_LLM_MODE = $Mode }
        Push-Location (Join-Path $root "shell")
        Write-Host "  Running: npm run tauri build (debug profile is skipped, release only)" -ForegroundColor DarkYellow
        npm.cmd run tauri build
        $buildExit = $LASTEXITCODE
        Pop-Location
        if ($buildExit -ne 0) {
            Write-Host "  [x] Release build failed (exit $buildExit)." -ForegroundColor Red
            exit 1
        }
        if (-not (Test-Path $releaseExe)) {
            Write-Host "  [x] Build finished but $releaseExe not found." -ForegroundColor Red
            exit 1
        }
        Write-Host "  [ok] Release build done: $releaseExe" -ForegroundColor Green
        $exe = $releaseExe
    } else {
        # ---- existing exe selection (no build) ----
        $exe = $null
        if (Test-Path $releaseExe) {
            $exe = $releaseExe
        } elseif (Test-Path $debugExe) {
            $exe = $debugExe
        }
    }

    if ($exe) {
        # ---- Launch built desktop shell ----
        if ($exe -eq $debugExe -and -not $Build) {
            # debug build loads frontend via devUrl (127.0.0.1:1420), Vite required
            Write-Host "[2/4] Debug build detected - needs Vite dev server for frontend." -ForegroundColor Yellow
            Ensure-NpmDeps
            $viteAlive = $false
            try {
                $viteAlive = Test-NetConnection -ComputerName 127.0.0.1 -Port 1420 -WarningAction SilentlyContinue -InformationLevel Quiet
            } catch { }
            if (-not $viteAlive) {
                Write-Host "  [i] Starting Vite dev server (127.0.0.1:1420)..." -ForegroundColor DarkYellow
                $vite = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory (Join-Path $root "shell") -PassThru -WindowStyle Minimized
                Start-Sleep -Seconds 6
                Write-Host "  [ok] Vite started." -ForegroundColor Green
            } else {
                Write-Host "  [ok] Vite already running." -ForegroundColor Green
            }
        } elseif ($exe -eq $releaseExe -and $Rebuild) {
            # release exe requested frontend rebuild (re-embed dist requires re-build; just note)
            Write-Host "[2/4] Release exe embeds dist; use -Build to recompile with latest frontend." -ForegroundColor DarkYellow
        }

        Write-Host "[3/4] Launching desktop app: $(Split-Path -Leaf $exe)..." -ForegroundColor Yellow
        if ($Mode -ne "auto") { $env:AIVYOS_LLM_MODE = $Mode }
        Write-Host "[4/4] Done! AivyOS starting (core auto-spawned)." -ForegroundColor Green
        Write-Host ""
        Write-Host "  Note: first launch takes a few seconds for core warm-up." -ForegroundColor DarkGray
        Write-Host "  Closing this terminal will stop AivyOS (app + core)." -ForegroundColor DarkGray
        $appProc = Start-Process -FilePath $exe -PassThru
        Add-AivyPid $appProc.Id
        try { Wait-Process -Id $appProc.Id -ErrorAction SilentlyContinue } catch { }
        Write-Host ""
        Write-Host "  [i] AivyOS window closed. Cleaning up processes..." -ForegroundColor DarkYellow
        Stop-AivyCleanup
        Write-Host "  [ok] Cleaned up. Goodbye!" -ForegroundColor Green
        exit 0
    } else {
        # ---- Dev mode (tauri dev, needs Rust toolchain) ----
        Write-Host "[2/4] No built app found, using dev mode (npm run tauri dev)..." -ForegroundColor Yellow
        Write-Host "  [i] First run compiles the Rust shell, may take minutes." -ForegroundColor DarkYellow
        Ensure-NpmDeps
        if ($Mode -ne "auto") { $env:AIVYOS_LLM_MODE = $Mode }
        Push-Location (Join-Path $root "shell")
        npm.cmd run tauri dev
        Pop-Location
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
    # Normal-exit cleanup (the PowerShell.Exiting event handles terminal-close)
    if ($global:AivyCleanupPids.Count -gt 0) {
        Stop-AivyCleanup
    }
}
