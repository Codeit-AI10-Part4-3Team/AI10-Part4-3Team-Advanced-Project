# 개발 환경 점검·복구 진입점 (Windows PowerShell).
# macOS·Linux·WSL·Git Bash 사용자는 scripts/setup-dev.sh 를 쓰세요 — 같은 코어를 호출합니다.
#
# ⚠️ 검사 로직은 여기 두지 마세요. 레지스트리는 scripts/dev_env.py 한 곳에만 있습니다.
#
# 사용: powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1 [--check|--yes|--skip-tests]
#       (실행 정책 때문에 막히면 위처럼 -ExecutionPolicy Bypass 를 붙이세요 → 가이드 #w06)

#Requires -Version 5.1
$ErrorActionPreference = "Stop"

# 콘솔이 cp949면 한글·UTF-8 출력이 깨지므로 UTF-8로 고정한다.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$root = Split-Path -Parent $PSScriptRoot

$py = $null
foreach ($candidate in @("py", "python", "python3")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}

if (-not $py) {
    Write-Host "[E02] Python을 찾을 수 없습니다. 3.12 이상을 설치한 뒤 다시 실행하세요."
    Write-Host "      대처: docs/공통_가이드/환경_세팅_가이드.md#e02"
    exit 2
}

& $py (Join-Path $root "scripts\dev_env.py") @args
exit $LASTEXITCODE
