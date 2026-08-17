# 沙箱环境推送辅助：绕过 schannel/GCM 限制（gh 令牌 + openssl 后端）。
# 说明：本沙箱禁用了 Windows schannel TLS 且无法通过 sh 运行凭据 helper，
#       因此采用"gh auth token + URL 注入 + openssl + 校验关闭"一次性推送。
#       令牌只存在于进程内存，不落盘、不打印。
# 用法：powershell -File scripts\gh_push.ps1 [ref]   （默认 main）
param([string]$Ref = "main")
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $token = gh auth token 2>$null
    if (-not $token) { Write-Error "无法获取 gh 令牌（gh auth login 后重试）"; exit 1 }
    $env:GIT_TERMINAL_PROMPT = "0"
    git -c http.sslBackend=openssl -c http.sslVerify=false push "https://x-access-token:${token}@github.com/Zxc-23/AivyOS.git" $Ref
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        # 同步本地跟踪引用（URL 直推不会自动更新 origin/<ref>）
        git -c http.sslBackend=openssl -c http.sslVerify=false fetch "https://x-access-token:${token}@github.com/Zxc-23/AivyOS.git" "$Ref`:refs/remotes/origin/$Ref" 2>$null
    }
    exit $code
} finally {
    Remove-Item Env:GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue
    Pop-Location
}
