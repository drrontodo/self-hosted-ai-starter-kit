# CPD Companion — handover for the next session

Read this, then [SPEC.md](SPEC.md) (full design + rationale), then [`cpd-companion/README.md`](../../cpd-companion/README.md). The research behind the spec is in [research/](research/).

## State as of 2026-08-23 (second session)

**All build-plan phases (1–6), M7, and M5b are built, tested (60 pytest tests), live-smoke-tested, and adversarially reviewed.** The app is feature-complete against SPEC.md:

- **Core (Phase 1):** FastAPI + SQLite in `cpd-companion/` — auth, activities register with draft→confirmed sign-off, dashboard (progress vs RACP minimums, mandatory-items widget, audit-readiness score), log/inbox/edit screens, MyCPD CSV export, nightly backups, generic jobs queue (`claude`/`whisper` engines).
- **M1 sessions** → weekly draft Cat 1 rollups. **M7 meetings** → whisper transcript → de-identified minutes → draft + evidence.
- **M3 news digest (Phase 2):** `feeds` table seeded from the research shortlist (TGA, 6 PubMed E-utilities queries, journal eTOCs — unverified URLs carry a status note; fix via `scripts/probe_sources.py` from the home network). Daily polling, PBS schedule monthly diff + Stroke Foundation living-guidelines diff (both snapshot-then-diff; first run is baseline only), nightly `digest` claude job (sections + cultural-safety/ethics flags), digest page with visibility-aware reading timer, weekly reading rollup → draft Cat 1 + reading-log evidence, per-item growth buttons.
- **M5 medicolegal audit (Phase 3):** watched `data/inbox/medicolegal`, hash detection, local docx/pdf/txt extraction, objective metrics vs configurable checklist (default NSW UCPR Sch 7; `medicolegal_checklist` setting), monthly `medicolegal_audit` claude job **from anonymised metrics only** (no filenames/text in payloads), sign-off with page timer → confirmed Cat 3 + de-identified evidence, month-on-month trend table. Signed-off audits are immune to late job results.
- **M5b response library:** `report_extract` claude job per report (pre-scrubbed text; absolute de-identification + generic Q&A templates per condition/topic in the doctor's own wording), curation page (approve/edit/reject = human de-id check), full-text search, md/JSON export for the medicolegal app, `backfill/` subfolder for old reports (excluded from monthly audits), weekly batches (`report_extract_batch` setting, default 5), curation sessions loggable as confirmed Cat 2.
- **M2 reviews (Phase 4):** daily Places poll (needs `GOOGLE_PLACES_API_KEY` + `EAST_NEURO_PLACE_ID` in `.env`; JSON exports in `data/inbox/reviews` work without), quarterly cycles (`review_cycle_months` setting), `review_themes` job, improvement backlog (practice_outputs), sign-off → confirmed Cat 2 + feedback-summary evidence listing completed actions.
- **M6 (Phase 4):** PDP builder page (`pdp_draft` claude pre-draft; completion → evidence + confirmed Cat 2 + mandatory tick), email-harvest standing prompt (`scripts/email-harvest.md`, external_ref dedupe), evidence upload/download on the activity edit page.
- **§5 growth loop (Phase 5):** `info_sheet` job (runner uses the **east-neuro-patient-page skill**), quarterly `opportunity_scan` + `referrer_newsletter` (newsletter consumes flags), weekly refresh flagging of published outputs, Outputs page.
- **Phase 6:** per-year audit-bundle zip (`/export/audit-bundle/{year}` — register CSV + markdown + all evidence; missing files flagged), `CPD_COOKIE_SECURE` flag, Tailscale notes in the README.

## Hard conventions — do not break

1. **API callers can only create drafts.** Confirmation happens exclusively through the logged-in dashboard; minutes come from measured/user-entered time, never LLM-estimated; LLM jobs never invent content (see the STRICT RULES blocks in every prompt and `scripts/claude-runner.md`). LLM job results can never touch signed-off/completed records — every `apply_*_result` checks and skips.
2. All DB access via `db.tx()`; schema changes go into `db.SCHEMA` as idempotent `CREATE ... IF NOT EXISTS` (no migration tool; the deployed DB is still treated as disposable — if that changes, add a migration path before touching table shapes).
3. All LLM work via the jobs queue (drained by `scripts/drain_claude.ps1` + `scripts/claude-runner.md` on the user's Claude Max subscription) — **no Anthropic API calls, no API keys**. Every new job kind gets: a queue function, an `apply_*` handler dispatched from `pipeline.handle_job_result()`, a STRICT RULES prompt, and a section in `claude-runner.md`.
4. `pytest` in `cpd-companion/` must pass; add tests for each new module (env vars set before importing the app — see `tests/test_app.py`).
5. Every module that creates activities attaches evidence (files in `EVIDENCE_DIR` + `evidence` rows); the audit-readiness score depends on it.
6. Commit and push to the branch you are on (`git branch --show-current`); run an adversarial code-review subagent over your changes against SPEC.md before finishing, and fix what it finds.

## Deployment notes / first-run checklist

1. `.env`: set the core secrets, plus (optional) `CPD_NCBI_API_KEY`, `GOOGLE_PLACES_API_KEY` + `EAST_NEURO_PLACE_ID`, `CPD_PBS_SUBSCRIPTION_KEY` if the PBS API needs one from your network.
2. Run `python scripts/probe_sources.py` from the deployment network; fix any feed URLs marked unverified on the Feeds page (delete + re-add).
3. Schedule on the host (Task Scheduler): nightly `drain_whisper.py` then `drain_claude.ps1`; monthly email-harvest session per `scripts/email-harvest.md`.
4. Smoke-test the PBS "run now" button (Feeds page) — the v3 API shape was written defensively (`CPD_PBS_API_BASE`) because it could not be reached from the build network.
5. Drop a few old reports into `data/inbox/medicolegal/backfill` and mine a batch from the Library page to calibrate extraction quality before trusting the weekly cadence.

## Remaining ideas (nothing blocking)

- Requirements lock file (optional hardening).
- M4 voice-note quick-add; MSF survey generator (SPEC §1 playbook items not yet needed).
- If the deployed DB stops being disposable: introduce a migration tool before the next schema change.
- Tailscale HTTPS (`tailscale serve`) + `CPD_COOKIE_SECURE=1` once phone access is wanted.
