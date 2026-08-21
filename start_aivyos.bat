@echo off
REM ============================================================
REM  AivyOS one-click launcher (double-click to run)
REM  Desktop mode: launches Tauri app (auto-spawns Python core)
REM  For browser mode: uncomment the -Web line below
REM  For release build: uncomment the -Build line below (needs Rust)
REM ============================================================
cd /d "%~dp0.."

if not exist "aivyos_core" (
    if exist "%~dp0aivyos_core" cd /d "%~dp0"
)

echo.
echo ============================================
echo    AivyOS Launcher
echo ============================================

REM --- Desktop mode (default) ---
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_aivyos.ps1"

REM --- Browser mode: comment the line above, uncomment below ---
REM powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_aivyos.ps1" -Web

REM --- Release build then launch: comment the first line, uncomment below ---
REM powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_aivyos.ps1" -Build

echo.
pause
