# Nightly drain: whisper first (transcripts queue the claude jobs), then claude.
# One task rather than two staggered ones, so the ordering cannot drift.
#
# Register once (see docs/cme-tracker/DEPLOYMENT.md); logs to data/logs.
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("drain-" + (Get-Date -Format "yyyy-MM-dd") + ".log")

function Write-Log($msg) { "$(Get-Date -Format 'HH:mm:ss')  $msg" | Tee-Object -FilePath $log -Append }

Write-Log "=== nightly drain start ==="

try {
    Write-Log "-- whisper --"
    & "$PSScriptRoot\drain-whisper.ps1" 2>&1 | Tee-Object -FilePath $log -Append
    Write-Log "whisper exit=$LASTEXITCODE"
} catch {
    Write-Log "whisper ERROR: $_"
}

try {
    Write-Log "-- claude --"
    & "$PSScriptRoot\drain_claude.ps1" 2>&1 | Tee-Object -FilePath $log -Append
    Write-Log "claude exit=$LASTEXITCODE"
} catch {
    Write-Log "claude ERROR: $_"
}

Write-Log "=== nightly drain done ==="

# Keep a fortnight of drain logs.
Get-ChildItem $logDir -Filter "drain-*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 14 |
    Remove-Item -Force -ErrorAction SilentlyContinue
