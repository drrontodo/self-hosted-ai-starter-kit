# Start CPD Companion natively on the Windows server.
#
# This host has no Docker Desktop (and no WSL2), so the app runs straight from
# the .venv instead of docker-compose. uvicorn --env-file loads .env itself,
# which is what the container's env_file used to do.
#
#   .\scripts\start-cpd.ps1            foreground (Task Scheduler uses this)
#   .\scripts\start-cpd.ps1 -Detach    own minimised window; used by start.bat
#
# Either way port 8340 is freed first, so a stale instance can no longer cause
# the "only one usage of each socket address" bind error. Only ONE instance may
# run — CPD_SCHEDULER=1 assumes a single process.
[CmdletBinding()]
param([switch]$Detach)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "$root\.env")) { throw "missing $root\.env" }
$python = "$root\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "missing $python — the virtualenv is gone" }

function Get-Port8340Listener {
    $conns = Get-NetTCPConnection -LocalPort 8340 -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return @() }
    @($conns.OwningProcess | Select-Object -Unique) | ForEach-Object {
        [pscustomobject]@{
            Id          = $_
            CommandLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$_" `
                              -ErrorAction SilentlyContinue).CommandLine
        }
    }
}

# Free the port — but only from THIS app. Blind-killing whatever holds a port
# is how you take down something unrelated that happens to be sitting on it.
foreach ($proc in Get-Port8340Listener) {
    if ($proc.CommandLine -match 'uvicorn' -and $proc.CommandLine -match 'app\.main:app') {
        Write-Host "Stopping previous CPD Companion (PID $($proc.Id))"
        Stop-Process -Id $proc.Id -Force
    } else {
        throw ("Port 8340 is held by PID $($proc.Id), which is NOT the CPD Companion:" +
               "`n  $($proc.CommandLine)`nStop that yourself, then run this again.")
    }
}
for ($i = 0; $i -lt 40 -and (Get-Port8340Listener); $i++) { Start-Sleep -Milliseconds 250 }

if ($Detach) {
    # Launch through cmd's `start` rather than Start-Process: Start-Process
    # leaves the server holding a copy of THIS process's stdout handle, so
    # anything reading our output (a pipeline, a scheduled task, a CI step)
    # blocks until the server itself exits — which is never. `start` detaches
    # cleanly into its own console.
    $cmd = 'start "CPD Companion" /min pwsh -NoProfile -ExecutionPolicy Bypass -File "{0}\start-cpd.ps1"' -f $PSScriptRoot
    & cmd.exe /c $cmd
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $r = Invoke-WebRequest "http://localhost:8340/health" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200) {
                Write-Host ""
                Write-Host "  CPD Companion is running -> http://localhost:8340" -ForegroundColor Green
                Write-Host "  (running in a minimised PowerShell window; close it to stop the app)"
                exit 0
            }
        } catch { }
    }
    throw "No response from /health after 30s — check the minimised PowerShell window for the error."
}

& $python -m uvicorn app.main:app --host 0.0.0.0 --port 8340 --env-file "$root\.env"
