# CPD Companion — handover for the next session

Read this, then [SPEC.md](SPEC.md) (full design + rationale), then [`cpd-companion/README.md`](../../cpd-companion/README.md). The research behind the spec is in [research/](research/).

## State as of 2026-08-23

**Built, tested (22 pytest tests), live-smoke-tested, and adversarially reviewed** (all high/medium findings fixed):

- FastAPI + SQLite app in `cpd-companion/` — auth (API key for `/api`, bcrypt-or-plaintext cookie login with throttling for the dashboard), activities register with draft→confirmed sign-off, dashboard (progress bars vs RACP minimums, mandatory-items widget with PDP/Annual-Conversation toggles, audit-readiness score, year navigation), activity log + editing, draft inbox with stale-write protection, MyCPD CSV export (formula-injection-escaped).
- **M1 sessions module**: `POST /api/sessions` + weekly rollup into draft Cat 1 activities, grouped per (project, calendar year, ISO week), timezone-correct, race-safe (`BEGIN IMMEDIATE`).
- **M7 meetings module**: audio upload → `whisper` job (host drain script `scripts/drain_whisper.py` uses faster-whisper) → `claude` job (drain via `scripts/drain_claude.ps1` + `scripts/claude-runner.md`) → de-identified minutes + draft activity + evidence files.
- Generic **jobs queue** (`jobs` table, `engine` = `claude`|`whisper`; `GET /api/jobs`, `POST /api/jobs/{id}/result|fail`) — **this is the substrate for every remaining LLM feature**: add a new `kind`, enqueue with a self-contained `prompt` + `payload`, teach `pipeline.handle_job_result()` what to do with the result, and document the kind in `scripts/claude-runner.md`.
- Nightly backup job, scheduler singleton lock, Docker deployment (named volume for the DB, bind mounts for evidence/audio/backups), `scripts/probe_sources.py` to verify feeds from the user's network.

## Hard conventions — do not break

1. **API callers can only create drafts.** Confirmation (an entry counting toward CPD totals) happens exclusively through the logged-in dashboard. This is the integrity model: automated clients must never self-certify hours. Same spirit everywhere: minutes come from measured/user-entered time, never LLM-estimated; LLM jobs must never invent content (see the de-identification and no-invention rules in `claude-runner.md`).
2. All DB access via `db.tx()`; schema changes go into `db.SCHEMA` as idempotent `CREATE ... IF NOT EXISTS` (there is no migration tool; the only deployed DB so far is disposable, so plain schema edits are still OK — say so in the commit if you rely on that).
3. All LLM work via the jobs queue (the user's Claude Max subscription drains it) — **no Anthropic API calls, no API keys**.
4. `pytest` in `cpd-companion/` must pass; add tests for each new module (see `tests/` for the pattern — env vars are set before importing the app).
5. Evidence artefacts are files in `EVIDENCE_DIR` + `evidence` rows; every module that creates activities should attach evidence (the audit-readiness score depends on it).
6. Commit and push to the branch you are on (`git branch --show-current`); run an adversarial code-review subagent over your changes against SPEC.md before finishing, and fix what it finds.

## Remaining work, in order

### Phase 2 — News digest & reading log (SPEC §3 M3)
- Feed poller (APScheduler + `feedparser`) over the shortlist in `research/news-sources.md` §4; feeds configurable in a `feeds` table/settings page. Store in `news_items` (dedupe on link/guid).
- PubMed via E-utilities (esearch reldate=7 + efetch abstracts) for the six subspecialty queries; PBS Schedule API monthly diff; Stroke Foundation updates-page scrape — see research doc for URLs/limits.
- Nightly `digest` claude job: cluster + summarise new items into sections; flag cultural-safety/ethics-relevant items.
- Digest dashboard page with a visibility-aware reading timer; mark-read stamps `read_seconds`; weekly rollup into a draft Cat 1 reading activity + generated reading-log PDF/markdown as evidence.
- Per-item action buttons (wire the buttons now, implement handlers in Phase 5): *Draft patient info sheet*, *Flag as opportunity*, *Add to referrer newsletter*.

### Phase 3 — Medicolegal audit (SPEC §3 M5)
- Watched folder `inbox/medicolegal` (add bind mount), hash-based new-file detection, docx/pdf text extraction, objective metrics in code (dates, turnaround, section presence per configurable checklist — default NSW UCPR Sch 7 expert-report elements).
- Monthly `medicolegal_audit` claude job drafting the audit vs checklist; sign-off screen; de-identified audit doc as Cat 3 evidence. Month-on-month trend table.

### Phase 4 — Reviews, email harvest, PDP builder (SPEC §3 M2, M6)
- Google Places daily poll (key + place ID in `.env`; `scripts/probe_sources.py` already tests the call) with `review_hash` dedupe; quarterly review-cycle screen; `review_themes` claude job; Cat 2 entry + feedback-summary evidence + **practice improvement backlog** (tracked actions).
- Email harvest: a standing prompt file (like `claude-runner.md`) for a monthly Claude Code session with the Gmail connector: find meeting invites/certificates/registrations, POST draft activities with `external_ref` (dedupe is already enforced server-side).
- PDP builder per SPEC §3 M6: guided RACP-template form, claude pre-draft from goals + register, evidence doc, ticks the mandatory tracker.
- Evidence upload UI on the activity edit page (files → `EVIDENCE_DIR`, sha256, evidence row) — small but currently missing.

### Phase 5 — Practice growth loop (SPEC §5)
- `practice_outputs` table + pipeline. `info_sheet` claude job: instruct the runner to use the **`east-neuro-patient-page` skill** (available in the user's Claude Code environment) so drafts match the East Neurology house style; store draft HTML in `practice_outputs`, review/download from the dashboard.
- Quarterly `opportunity_scan` claude job over the quarter's news + PBS diffs → service-opportunity briefs (the "business improvement LLM call"). Quarterly `referrer_newsletter` job from flagged items.
- Published-output refresh flagging (new digest items matching sources of published outputs).

### Phase 6 — Hardening & audit bundle
- Audit-bundle zip export per CPD year (register + all evidence). Tailscale setup notes. `Secure` cookie flag once HTTPS exists. Optional: lock file for requirements.

## Copy-paste prompt for the fresh session

See the conversation summary, or use:

> Read docs/cme-tracker/HANDOVER.md and follow it: continue building the CPD Companion from Phase 2 onward, keeping the hard conventions, adding tests, running an adversarial review before finishing, and committing/pushing as you go.
