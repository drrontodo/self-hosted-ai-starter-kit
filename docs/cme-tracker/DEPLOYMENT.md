# CPD Companion — server deployment (Windows, native)

Deployed 2026-08-25 on the Windows 11 server at
`C:\Users\drron\AI-Projects\CPD program`, branch
`claude/cpd-companion-phase-2-2hklwj`.

This supersedes the "Run it (Windows server, Docker Desktop)" section of
`cpd-companion/README.md` **on this host**. The compose file still works
anywhere Docker exists; it just is not how this machine runs the app.

## Why native rather than Docker

The server has **no Docker Desktop and no WSL2**. Installing them needs
administrator rights and a reboot, which is the user's call, not an agent's.
The app is plain FastAPI + SQLite with pure-Python dependencies, so it runs
directly from a virtualenv with no behavioural difference. The full 66-test
suite passes natively on Python 3.11.

Consequences of the switch, all handled:

| Docker assumption | Native equivalent |
|---|---|
| DB on the `cpd_data` named volume (for WAL locking on Docker Desktop) | DB at `cpd-companion\data\cpd.db` — plain NTFS, no WAL locking issue |
| `env_file: .env` | `uvicorn --env-file .env` (uvicorn loads it via python-dotenv) |
| `CPD_DATA_DIR=/data` + bind mounts | `CPD_DATA_DIR=…\cpd-companion\data`; every subfolder already lived there |
| `docker compose up -d` | `scripts\start-cpd.ps1`, run at logon by Task Scheduler |

## Layout

- App venv: `cpd-companion\.venv` (Python 3.11.9) — FastAPI, uvicorn, etc.
- Whisper venv: `cpd-companion\.venv-whisper` — faster-whisper 1.2.1,
  ctranslate2 4.8.1, plus the `nvidia-cublas-cu12` / `nvidia-cudnn-cu12`
  wheels. Kept separate so ~3 GB of CUDA libraries cannot disturb the app's
  dependency set.
- Data root: `cpd-companion\data\` (db, evidence, audio, transcripts, inbox,
  outputs, backups, logs).
- Both venvs are gitignored.

## Environment-specific gotchas

### 1. Norton 360 intercepts TLS — this breaks outbound HTTPS

Norton re-signs every TLS connection with its own root CA
(`C:\ProgramData\Norton\Antivirus\wscert.pem`). Anything that trusts only
`certifi` — which is httpx's default, and therefore every feed poll, PubMed
query, PBS call and Google Places call — fails with
`CERTIFICATE_VERIFY_FAILED`. pip fails the same way.

Fixed with a combined bundle (certifi + the Norton root):

    C:\Users\drron\.certs\ca-bundle-norton.pem

`.env` sets `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to it. For pip, pass
`--cert` or set `PIP_CERT` to the same path.

**Rebuild the bundle whenever certifi is upgraded in the app venv**, or newly
added root CAs will be missing:

```powershell
$certifi = & ".\.venv\Scripts\python.exe" -c "import certifi;print(certifi.where())"
Get-Content $certifi -Raw | Set-Content C:\Users\drron\.certs\ca-bundle-norton.pem -NoNewline -Encoding ascii
Add-Content C:\Users\drron\.certs\ca-bundle-norton.pem "`n" -NoNewline -Encoding ascii
Get-Content C:\ProgramData\Norton\Antivirus\wscert.pem -Raw | Add-Content C:\Users\drron\.certs\ca-bundle-norton.pem -NoNewline -Encoding ascii
```

If Norton is ever removed, the bundle still works — it is a superset of certifi.

### 2. faster-whisper needs the CUDA DLLs on PATH

`WhisperModel(...)` *loads* fine without them, then dies at the first encode
with `Library cublas64_12.dll is not found or cannot be loaded`. The DLLs ship
inside the nvidia wheels but Windows will not find them unless
`…\.venv-whisper\Lib\site-packages\nvidia\{cublas,cudnn,cuda_nvrtc}\bin` is on
PATH. `scripts\drain-whisper.ps1` does this; call the drain through that
wrapper, never `python scripts\drain_whisper.py` directly.

Verified on the RTX 5090 (driver 595.95): `large-v3`, `cuda`, `float16`, model
load 4.2 s, transcription ~3.4× realtime, transcript accurate.

### 3. PBS Data API v3

- It needs a subscription key. The public one published in the PBS docs
  (`2384af7c667342ceb5a736fe29f1dc6b`) works and is in `.env`. Without it the
  API returns 401.
- Rate limiting is aggressive — `_pbs_get()` retries 429s with backoff.
- A full fetch takes ~5–6 minutes. It runs monthly, so that is fine.

## Scheduled tasks

| Task | Trigger | Runs |
|---|---|---|
| `CPD Companion - app` | At logon | `scripts\start-cpd.ps1` (uvicorn, port 8340, restarts up to 3×) |
| `CPD Companion - nightly drain` | Daily 02:30 | `scripts\drain-nightly.ps1` → whisper drain, then claude drain |

Drain logs: `cpd-companion\data\logs\drain-YYYY-MM-DD.log` (14 kept).

The monthly email-harvest session (`scripts\email-harvest.md`) is still a
manual Claude Code run — it needs the Gmail connector and an interactive
session, so it is deliberately not scheduled.

## Known issue — medicolegal instruction-date parsing

`medicolegal.compute_metrics()` finds the instruction date by scanning a
120-character window after any `_INSTRUCTION_CONTEXT` match and then taking
`min()` of the dates found. A bare prose mention — "the assumed facts are those
set out in **the letter of instruction**. The history was of a collision on
5 January 2025…" — therefore captures the *accident* date, and `min()` prefers
it over the genuine instruction date.

Observed on a synthetic report: instruction date parsed as 2025-01-05 (the
accident) rather than 2026-02-02 (the actual letter), which pushed the
turnaround past the 400-day sanity cap so `turnaround_days` silently became
`NULL`. A near-miss is worse — it would produce a plausible but wrong
turnaround feeding the monthly Cat 3 audit.

Suggested fix (not applied — it changes audit metric semantics, and the right
answer depends on how real reports are actually worded): prefer dates from an
explicit anchored pattern such as `letter of instruction dated X` /
`Date of letter of instruction: X`, and only fall back to the loose proximity
window when no anchored match exists. Tighten the window and drop `min()` in
favour of the first anchored hit.

## Restarting the app

Restarts are the user's to perform. To restart: end the running
`python.exe`/uvicorn process for this app, then run the `CPD Companion - app`
task (or `scripts\start-cpd.ps1`). Only ever run **one** instance —
`CPD_SCHEDULER=1` assumes a single process.
