# Start CPD Companion natively on the Windows server.
#
# This host has no Docker Desktop (and no WSL2), so the app runs straight from
# the .venv instead of docker-compose. uvicorn --env-file loads .env itself,
# which is what the container's env_file used to do.
#
# Task Scheduler: run at system startup, "Start in" = the repo's cpd-companion
# folder. Only ONE instance may run — CPD_SCHEDULER=1 assumes a single process.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "$root\.env")) { throw "missing $root\.env" }

& "$root\.venv\Scripts\python.exe" -m uvicorn app.main:app `
    --host 0.0.0.0 --port 8340 --env-file "$root\.env"
