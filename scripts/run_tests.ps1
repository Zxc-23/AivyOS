# AivyOS 开发辅助脚本
# 用法：powershell -File scripts\run_tests.ps1
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "`n[OK] 全部测试通过" -ForegroundColor Green
} finally {
    Pop-Location
}
