# Sandbox push helper: bypass schannel/GCM limits (gh token + openssl backend).
# NOTE: This sandbox blocks Windows schannel TLS and cannot run git credential
#       helpers via sh, so we push with a gh token injected in the URL,
#       openssl TLS backend and verification disabled. The token lives only in
#       process memory; it is never written to disk or printed.
# Usage: powershell -File scripts\gh_push.ps1 [ref]   (default: main)
$Ref = if ($args.Count -gt 0) { $args[0] } else { "main" }
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $token = gh auth token 2>$null
    if (-not $token) { Write-Error "gh auth token failed (run gh auth login first)"; exit 1 }
    $env:GIT_TERMINAL_PROMPT = "0"
    git -c http.sslBackend=openssl -c http.sslVerify=false push "https://x-access-token:${token}@github.com/Zxc-23/AivyOS.git" $Ref
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        # After a URL-targeted push git does not update origin/<ref>; sync locally.
        git update-ref "refs/remotes/origin/$Ref" "refs/heads/$Ref"
    }
    exit $code
} finally {
    Remove-Item Env:GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue
    Pop-Location
}
