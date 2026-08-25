# Drain pending claude jobs via a headless Claude Code run (uses your Max
# subscription, no API key billing). Schedule nightly in Task Scheduler, after
# drain_whisper.py, or run manually.
#
# CPD_API_KEY is read from .env when it is not already in the environment, so a
# scheduled task needs no secret of its own.
if (-not $env:CPD_API_KEY) {
    $envFile = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*CPD_API_KEY\s*=\s*(\S.*?)\s*$') { $env:CPD_API_KEY = $Matches[1] }
        }
    }
}
if (-not $env:CPD_API_KEY) { throw "CPD_API_KEY is not set and was not found in .env" }

$prompt = Get-Content -Raw "$PSScriptRoot\claude-runner.md"
claude -p $prompt --allowedTools "Bash(curl:*)"
