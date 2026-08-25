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
$output = claude -p $prompt --allowedTools "Bash(curl:*)" 2>&1 | Out-String
$claudeExit = $LASTEXITCODE
Write-Output $output

# `claude -p` exits 0 even when it never ran — an expired OAuth session prints
# "Failed to authenticate" and returns success, which would let a scheduled
# drain report green every night while draining nothing. Fail loudly instead.
$authFailure = $output -match 'Failed to authenticate|OAuth session expired|Invalid API key|Please run /login'
if ($claudeExit -ne 0 -or $authFailure) {
    if ($authFailure) {
        Write-Error "claude CLI is not authenticated — run 'claude' interactively and sign in, then re-run this drain. Jobs remain pending."
    } else {
        Write-Error "claude CLI exited $claudeExit; jobs remain pending."
    }
    exit 1
}
exit 0
