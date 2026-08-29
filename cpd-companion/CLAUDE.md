# CPD Companion — project notes for Claude sessions

**Status (2026-08-29): DEPLOYED and in use on the Windows server.** Branch
`claude/cpd-companion-phase-2-2hklwj`, head `890b353`, **72 pytest tests
green**. All SPEC phases 1–6 + M7 + M5b; adversarially reviewed twice.

Runs **natively, not under Docker** — this host has no Docker Desktop and no
WSL2. **Read `../docs/cme-tracker/DEPLOYMENT.md`** for venvs, launcher,
scheduled tasks, and the Norton-TLS / CUDA-DLL gotchas. Session history is in
`../docs/cme-tracker/handoff/`.

**Next:** wire in the PubMed LLM analyser (port 5090) so case-research time
becomes draft Cat 1 via `POST /api/sessions`; fix the `rollup.py` evidence gap
alongside it; validate `appointment_date` against real reports; backfill trial;
merge to main. Full prompt:
`C:\Users\drron\AI-Projects\next session prompts\CPD program\2026-08-29-pubmed-integration-and-first-real-data.md`

## Guardrails — binding, do not break

Full list in `../docs/cme-tracker/HANDOVER.md`. In brief:

1. API callers create **drafts only**; confirmation is dashboard-only.
   Minutes are measured (timers) or user-entered — never LLM-estimated.
   LLM jobs never invent content and never touch signed-off records.
2. All DB access via `db.tx()`; schema = idempotent `CREATE IF NOT EXISTS` in
   `db.SCHEMA`. **The deployed DB is no longer disposable** (real data since
   2026-08-26). New *columns* go in `db._ADDED_COLUMNS` (applied idempotently
   at startup); renames, type changes or new constraints need a real migration
   path built first.
3. All LLM work via the `jobs` queue drained by `scripts/drain_claude.ps1`
   per `scripts/claude-runner.md` — **no Anthropic API calls or keys**.
   New job kind = queue fn + `apply_*` handler in `pipeline.handle_job_result`
   + STRICT-RULES prompt + `claude-runner.md` section (+ failure unwind in
   `pipeline.handle_job_failure` if it holds module state).
4. Every module creating activities attaches evidence
   (`db.add_generated_evidence` — files are sha256-stamped).
   **Known violation: `rollup.py` attaches none — fix it.**
5. `python -m pytest` from this directory must stay green (shared-DB test
   suite; files must pass in any order).
6. Serialise check-then-act writes with `BEGIN IMMEDIATE` (see rollup.py);
   medicolegal report text may enter job payloads only pre-scrubbed
   (`_prescrub`) and is purged from payloads on job completion/failure.

## Operational facts

- **Start/restart: double-click `start.bat`.** Frees port 8340 (only if this
  app holds it — refuses and names anything else), starts minimised, waits for
  `/health`. Port 8340, single process only (`CPD_SCHEDULER=1` assumes it).
  Also auto-starts at logon via the `CPD Companion - app` task.
- The app reads **`cpd-companion\.env`**. The repo-root `.env` belongs to the
  old n8n starter kit, is not read, and is untracked.
- DB at `data\cpd.db`; evidence/audio/transcripts/inbox/outputs/backups/logs
  under `data\`.
- **Norton 360 intercepts TLS.** `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` point at
  `C:\Users\drron\.certs\ca-bundle-norton.pem`; without it every outbound
  HTTPS call fails. `pip` needs `PIP_CERT` set to the same file.
- **Whisper must run via `scripts\drain-whisper.ps1`** — it puts the CUDA DLLs
  on PATH, or CTranslate2 dies at the first encode. cuda/float16 defaults
  (`--device cpu --compute-type int8` fallback).
- `claude -p` exits 0 even when unauthenticated; `drain_claude.ps1` detects
  that and exits 1. Silent no-op drains = sign in with `claude` interactively.
- Turnaround = **appointment → completed report** (`_APPOINTMENT_CONTEXT`,
  anchored patterns only; absent ⇒ `NULL`, never inferred).
- Tuned settings (DB `settings` table): `report_extract_batch`=5,
  `review_cycle_months`=3, `pbs_atc_prefixes` = `N02C,N03,N04,N07A,N07X,
  L04AE,L04AG,L04AJ,L04AL,L04AK02,L04AA40,L04AC19,L03AB07,L03AB08,L03AB13,
  L03AX13,M03,N06D` (tuned 2026-08-26: 1507→551 items, non-neurology 70%→5%).
  Reading timer caps 7200 s/item; digest 60 items/run; meeting-job retries
  cap at 2; PBS/Stroke first run is baseline-only.
- PBS v3 needs the public subscription key (in `.env`), reports
  `total_records` not `total_pages`, rate-limits hard, full fetch ~6 min.
- Backfill reports (`data/inbox/medicolegal/backfill`) feed the response
  library but are excluded from monthly audits.
