# CPD Companion — project notes for Claude sessions

**Status (2026-08-26): DEPLOYED on the Windows server**, branch
`claude/cpd-companion-phase-2-2hklwj`. All SPEC phases 1–6 + M7 + M5b; 69
pytest tests green; adversarially reviewed twice.

Running **natively, not under Docker** — that host has no Docker Desktop and
no WSL2. See `../docs/cme-tracker/DEPLOYMENT.md` for the venvs, launcher,
scheduled tasks, and the Norton-TLS / CUDA-DLL gotchas. Verified on the
server: real RTX 5090 whisper transcription end-to-end, 14/14 feeds polling,
PBS baseline 551 items, all pages + exports.

**Blocked / next:**
1. `claude -p` is **not authenticated** on this host — sign in interactively,
   then run `scripts\drain_claude.ps1`. One `meeting_summary` job is waiting.
2. `.env` still holds a **temporary** dashboard password hash — replace with
   Ron's own, and add `GOOGLE_PLACES_API_KEY` / `EAST_NEURO_PLACE_ID`.
3. Backfill trial not yet run (needs real reports in
   `data\inbox\medicolegal\backfill`).
4. `compute_metrics` instruction-date parsing is unreliable — see the note in
   `../docs/cme-tracker/DEPLOYMENT.md`.
5. Then merge to main.

## Guardrails — binding, do not break

Full list in `../docs/cme-tracker/HANDOVER.md`. In brief:

1. API callers create **drafts only**; confirmation is dashboard-only.
   Minutes are measured (timers) or user-entered — never LLM-estimated.
   LLM jobs never invent content and never touch signed-off records.
2. All DB access via `db.tx()`; schema = idempotent `CREATE IF NOT EXISTS`
   in `db.SCHEMA`; no migration tool yet (add one before the next schema
   change once real data exists).
3. All LLM work via the `jobs` queue drained by `scripts/drain_claude.ps1`
   per `scripts/claude-runner.md` — **no Anthropic API calls or keys**.
   New job kind = queue fn + `apply_*` handler in `pipeline.handle_job_result`
   + STRICT-RULES prompt + `claude-runner.md` section (+ failure unwind in
   `pipeline.handle_job_failure` if it holds module state).
4. Every module creating activities attaches evidence
   (`db.add_generated_evidence` — files are sha256-stamped).
5. `python -m pytest` from this directory must stay green (shared-DB test
   suite; files must pass in any order).
6. Serialise check-then-act writes with `BEGIN IMMEDIATE` (see rollup.py);
   medicolegal report text may enter job payloads only pre-scrubbed
   (`_prescrub`) and is purged from payloads on job completion/failure.

## Operational facts

- Run: `docker compose up -d --build`, port 8340; single process only.
- DB on `cpd_data` volume; evidence/audio/transcripts/inbox/outputs/backups
  bind-mounted under `./data/`.
- Host-side: `pip install faster-whisper`; `drain_whisper.py` defaults
  cuda/float16 (`--device cpu --compute-type int8` fallback).
- Tuned settings (DB `settings` table): `report_extract_batch`=5,
  `review_cycle_months`=3, `pbs_atc_prefixes`=N02C,N03,N04,N07,L04.
  Reading timer caps 7200 s/item; meeting-job retries cap at 2.
- Backfill reports (`data/inbox/medicolegal/backfill`) feed the response
  library but are excluded from monthly audits.
