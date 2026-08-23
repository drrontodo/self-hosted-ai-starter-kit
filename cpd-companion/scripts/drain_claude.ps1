# Drain pending claude jobs via a headless Claude Code run (uses your Max
# subscription, no API key billing). Schedule nightly in Task Scheduler, after
# drain_whisper.py, or run manually. CPD_API_KEY must be set in the environment.
$prompt = Get-Content -Raw "$PSScriptRoot\claude-runner.md"
claude -p $prompt --allowedTools "Bash(curl:*)"
