# Next-session prompt — CPD Companion server deployment

> Written 2026-08-25 by the cloud build session. Paste this whole file into a
> fresh Claude Code session running **locally on the Windows server** (with
> access to `C:\Users\drron\AI-Projects`). First action after cloning: save a
> copy of this prompt to
> `C:\Users\drron\AI-Projects\next session prompts\CPD program\2026-08-25-server-deployment.md`
> so the usual ritual folder is current.

## Exact current state

- Repo: `drrontodo/self-hosted-ai-starter-kit`, branch
  **`claude/cpd-companion-phase-2-2hklwj`** (NOT merged to main), head
  `0d1b876` ("fix: harden drain_whisper.py — device/compute flags, per-job
  error handling").
- **The build is code-complete.** All SPEC phases (1–6), M7 meetings, and the
  M5b medicolegal response library are implemented; **66 pytest tests, all
  green**; two adversarial review passes (41 confirmed findings) fixed.
- Nothing is deployed. The app has never run on the server from this branch.
  The whisper drain pipeline was verified end-to-end in the cloud with a stub
  model; **real GPU inference is unverified** (HuggingFace was blocked there).
- The user's job in this session: **paste their keys into `.env` when asked —
  everything else is yours.**

## Immediate next steps, in order

1. **Clone** the branch to the local folder (the folder may not exist yet):
   ```powershell
   cd "C:\Users\drron\AI-Projects"
   git clone --branch claude/cpd-companion-phase-2-2hklwj https://github.com/drrontodo/self-hosted-ai-starter-kit.git "CPD program"
   cd "C:\Users\drron\AI-Projects\CPD program\cpd-companion"
   ```
   If the folder already exists with content, fetch/checkout the branch
   instead of cloning over it. Then save this prompt per the note above.
2. **Env file:** `copy .env.example .env`. Generate `CPD_API_KEY` and
   `CPD_SECRET_KEY` yourself (`python -c "import secrets; print(secrets.token_hex(32))"`),
   then STOP and ask the user to add: dashboard password (offer to bcrypt-hash
   it for `CPD_DASHBOARD_PASSWORD_HASH`), `GOOGLE_PLACES_API_KEY`,
   `EAST_NEURO_PLACE_ID`, optionally `CPD_NCBI_API_KEY` /
   `CPD_PBS_SUBSCRIPTION_KEY`. Blank optional keys are fine — features degrade
   gracefully.
3. **Bring the app up:** `docker compose up -d --build`; verify
   `http://localhost:8340/health` and log in to the dashboard. If a stale
   `cpd_data` volume exists from any pre-branch experiment, delete it first —
   the schema changed across this branch and there is deliberately no
   migration tool (DB is documented as disposable until first real data).
4. **Host-side whisper:** `pip install faster-whisper` (plus
   `nvidia-cublas-cu12 nvidia-cudnn-cu12` if CUDA init fails). Verify
   `WhisperModel('large-v3', device='cuda', compute_type='float16')` loads on
   the RTX 5090. Then a REAL end-to-end test: synthesize a short spoken WAV
   with Windows TTS (`System.Speech.Synthesis.SpeechSynthesizer` in
   PowerShell), upload it on `/meetings`, run
   `python scripts\drain_whisper.py --base-url http://localhost:8340 --data-dir .\data`,
   and confirm the transcript reaches the claude job queue
   (`GET /api/jobs?engine=claude` with the API key).
5. **Claude drain:** verify `scripts\drain_claude.ps1` runs with the local
   `claude` CLI (Max subscription) and drains the meeting-summary job from
   step 4; the draft should land in the dashboard Inbox with evidence.
6. **Feeds:** run `python scripts\probe_sources.py`; fix the feeds seeded
   from unverified URLs (marked in `last_status` on the Feeds page —
   Neurology eTOC, JAMA Online First, Lancet Neurology, Medscape which is
   seeded disabled). You can log into the dashboard programmatically with the
   `.env` password to delete/re-add feeds. Press "Poll all feeds now" and the
   PBS + Stroke "run now" buttons; first PBS/Stroke run is baseline-only.
7. **Task Scheduler:** create nightly entries — `drain_whisper.py` then
   `drain_claude.ps1` (whisper first), with `CPD_API_KEY` in the task
   environment. Add a monthly reminder task (or note for the user) to run the
   email-harvest session per `scripts\email-harvest.md`.
8. **M1 adoption:** add the CPD session-logging snippet from
   `cpd-companion/README.md` to the server's global `~/.claude/CLAUDE.md` so
   dev sessions start reporting research time.
9. **Backfill trial:** have the user drop 3–5 old medicolegal reports into
   `data\inbox\medicolegal\backfill`, press "Scan inbox now" (Audits page)
   and "Mine next batch now" (Library page), drain claude, and curate the
   first extracted snippets together to calibrate quality before trusting the
   weekly cadence.
10. **Smoke every page** (Home, Digest, Inbox, Log, Meetings, Audits,
    Library, Reviews, Outputs, PDP, Feeds, CSV + audit-bundle exports) and
    fix anything the real Windows/Docker environment surfaces. Commit fixes
    to this branch and push.

## Long-term roadmap

- Merge `claude/cpd-companion-phase-2-2hklwj` to `main` via PR once the
  server deployment is validated end-to-end.
- Tailscale on server + phone for remote access; `tailscale serve` for HTTPS
  and then `CPD_COOKIE_SECURE=1`.
- Monthly email-harvest routine (Claude Code + Gmail connector,
  `scripts/email-harvest.md`) — first run should back-fill the whole CPD year.
- Requirements lock file (pip freeze) once the deployment is stable.
- Introduce a migration tool (e.g. tiny hand-rolled `PRAGMA user_version`
  steps) BEFORE the next schema change — after real data exists the
  disposable-DB assumption in HANDOVER.md convention 2 no longer holds.
- M4 voice-note quick-add for peer discussions; MSF survey generator
  (SPEC §1 playbook items, deliberately deferred).
- Mini clinical-audit templates (EVOLVE top-5, EMG turnaround, epilepsy
  driving-advice documentation) as one-click Cat 3 starters.
- Response library growth: export automation into the medicolegal reporting
  program's intranet once the JSON export shape has settled.

## Key file paths

- Spec: `docs/cme-tracker/SPEC.md` (M5b = response library section)
- Conventions + state: `docs/cme-tracker/HANDOVER.md` (hard conventions are
  binding; read before changing anything)
- This prompt: `docs/cme-tracker/NEXT-SESSION-PROMPT.md`
- Session handoffs: `docs/cme-tracker/handoff/`
- App: `cpd-companion/` (README has run/API docs; `CLAUDE.md` has the lean
  status + guardrails)
- Runner contracts: `cpd-companion/scripts/claude-runner.md` (all 8 job
  kinds), `email-harvest.md`, `drain_whisper.py`, `drain_claude.ps1`,
  `probe_sources.py`

## Gotchas + tuned values

- **Hard conventions** (HANDOVER.md): API creates drafts only; minutes are
  measured/user-entered, never LLM-estimated; all LLM work via the jobs queue
  (no Anthropic API keys); every activity-creating module attaches evidence;
  `pytest` (66 tests, run from `cpd-companion/`) must stay green.
- Failed claude/whisper jobs are recoverable by design: report_extract resets
  to pending, info_sheet dismisses its output (re-click retries), review
  cycles and audits self-requeue, meeting jobs retry from surviving files
  (cap: 2 retries). Don't "fix" a failure by hand-editing the DB.
- Settings (DB `settings` table, not env): `report_extract_batch` (default
  5/week), `review_cycle_months` (3), `pbs_atc_prefixes`
  (N02C,N03,N04,N07,L04), `stroke_updates_url`, `medicolegal_checklist`
  (JSON override of the NSW UCPR Sch 7 default).
- Reading timer caps at 7200 s/item; digest job batches 60 items; PBS/Stroke
  first run is baseline-only; backfill reports never enter monthly audits.
- Port 8340; DB on the `cpd_data` named volume; evidence/audio/transcripts/
  inbox/outputs/backups bind-mounted under `cpd-companion\data\`.
- `drain_whisper.py` defaults to `--device cuda --compute-type float16`; use
  `--device cpu --compute-type int8` only as fallback.
- The repo root is the old n8n starter kit — ignore it; everything lives in
  `cpd-companion/` and `docs/cme-tracker/`.
