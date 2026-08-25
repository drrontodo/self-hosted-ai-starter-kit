# Nightly wrapper around drain_whisper.py for Task Scheduler.
#
# Two things the bare script cannot do for itself on this host:
#   1. faster-whisper's CUDA backend needs the DLLs shipped by the
#      nvidia-cublas-cu12 / nvidia-cudnn-cu12 wheels on PATH, or CTranslate2
#      fails at the first encode with "Library cublas64_12.dll is not found".
#   2. CPD_API_KEY has to come from .env rather than being pasted in here, so
#      this file stays committable.
#
# Run this BEFORE drain_claude.ps1 — meeting transcripts queue the claude jobs.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$nv = "$root\.venv-whisper\Lib\site-packages\nvidia"
$env:PATH = "$nv\cublas\bin;$nv\cudnn\bin;$nv\cuda_nvrtc\bin;$env:PATH"

foreach ($line in Get-Content "$root\.env") {
    if ($line -match '^\s*CPD_API_KEY\s*=\s*(\S.*?)\s*$') { $env:CPD_API_KEY = $Matches[1] }
}
if (-not $env:CPD_API_KEY) { throw "CPD_API_KEY not found in $root\.env" }

& "$root\.venv-whisper\Scripts\python.exe" "$root\scripts\drain_whisper.py" `
    --base-url http://localhost:8340 --data-dir "$root\data" @args
exit $LASTEXITCODE
