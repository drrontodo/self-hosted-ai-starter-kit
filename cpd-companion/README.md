# CPD Companion

Self-hosted tracker for RACP MyCPD requirements. See [../docs/cme-tracker/SPEC.md](../docs/cme-tracker/SPEC.md) for the full specification and the research reports behind it.

**Built so far (Phases 1–4 + M7):** FastAPI + SQLite app with dashboard (progress bars, mandatory-items checklist, audit-readiness score, activity log, draft inbox), the Claude Code session-logging endpoint with weekly rollup into draft Category 1 activities, the meeting-recording pipeline (upload → local faster-whisper transcription → de-identified minutes via Claude Code → draft entry with evidence), the neurology news digest (RSS + PubMed polling, PBS schedule diff, Stroke Foundation guidelines diff, nightly Claude digest job, reading timer + weekly reading rollup with a generated reading-log evidence document), the medicolegal report audit engine (watched inbox folder, local docx/pdf text extraction, objective metrics vs a configurable NSW UCPR Sch 7 checklist, monthly Claude-drafted audit with month-on-month trends, sign-off into a confirmed Cat 3 activity with a de-identified evidence document), the patient-feedback loop (daily Google reviews polling + quarterly themed review cycles with a practice-improvement backlog), the PDP builder, per-activity evidence upload, the monthly email-harvest runner prompt, MyCPD CSV export, and nightly backups.

## Run it (Windows server, Docker Desktop)

```powershell
cd cpd-companion
copy .env.example .env
# edit .env: set CPD_API_KEY, CPD_DASHBOARD_PASSWORD, CPD_SECRET_KEY
docker compose up -d --build
```

Dashboard: http://localhost:8340 (or http://<server-ip>:8340 from other LAN devices).

Storage layout: the SQLite database lives on a Docker named volume (`cpd_data`) — reliable WAL locking on Docker Desktop. Evidence documents, meeting audio, transcripts, and the nightly backup zips are bind-mounted under `cpd-companion/data/` on the host so you (and `drain_whisper.py`) can reach them from Windows; include `data/backups/` in your normal backup routine — each zip contains the full database plus evidence.

Without Docker: `pip install -r requirements.txt`, set the same env vars plus `CPD_DATA_DIR=C:\cpd-data`, then `uvicorn app.main:app --host 0.0.0.0 --port 8340`. Run a **single process** (no `--workers`) — the scheduler and SQLite assume it.

### Meeting recordings (Annual Conversation, peer discussions, M&M)

Upload a recording on the **Meetings** page (with participant consent — required checkbox). Then, on the host:

```powershell
$env:CPD_API_KEY = "<your key>"
python scripts\drain_whisper.py --base-url http://localhost:8340 --data-dir .\data   # GPU transcription
.\scripts\drain_claude.ps1                                                           # de-identified minutes via Claude Code
```

Schedule both in Task Scheduler (whisper first) for hands-off processing. The result lands in the Inbox as a draft with the minutes document and transcript attached as evidence.

### News digest & reading log (M3)

The **Feeds** page manages the polled sources (seeded from the research
shortlist: TGA alerts/news, six PubMed subspecialty queries via E-utilities,
journal eTOCs, NeurologyLive, The Medical Republic). Feeds are polled daily at
05:30; a `digest` claude job is queued at 05:50 and drained by the same nightly
`drain_claude.ps1` run as the meeting jobs. Two monthly API jobs — the PBS
schedule diff (new/changed neurology listings) and the Stroke Foundation
living-guidelines page diff — run on the 1st, with "run now" buttons on the
Feeds page. Journal feed URLs flagged *unverified* in
[the research doc](../docs/cme-tracker/research/news-sources.md) are seeded
with a status note — run `python scripts/probe_sources.py` from the deployment
network and fix any that fail.

The **Digest** page shows unread items grouped by section. Reading time is
measured by a visibility-aware timer (only while an item is open and the tab
visible) and banked when you press *Mark read*; every Monday the read items
roll up into a **draft** Cat 1 reading activity with a generated reading-log
markdown document attached as evidence (diary-style logs are RACP-acceptable
evidence for reading). Each item also carries practice-growth buttons (*Draft
patient info sheet*, *Flag as opportunity*, *Add to referrer newsletter*).

### Medicolegal report audit (M5)

Drop finished reports (docx / pdf / txt) into `data/inbox/medicolegal`. A daily
scan detects new files by content hash and computes objective metrics locally —
word count, report/instruction dates, turnaround, and section presence against
the expert-report checklist (default: NSW UCPR Schedule 7 elements; override
via the `medicolegal_checklist` setting). On the 1st of each month a
`medicolegal_audit` claude job drafts the audit narrative **from the metrics
only** (anonymised R-numbers — no filenames or report text ever enter the job
queue). Review and sign off on the **Audits** page: the sign-off creates a
confirmed Cat 3 activity (minutes timer-tracked while the review page is open)
with the de-identified audit document as evidence, and the month-on-month
table gives the measure → reflect → re-measure cycle Cat 3 requires.

### Patient feedback, PDP, email harvest (M2 + M6)

**Reviews:** set `GOOGLE_PLACES_API_KEY` and `EAST_NEURO_PLACE_ID` in `.env`
for the daily Places poll (the API returns ~5 reviews per call; daily polling
with hash dedupe accumulates them), and/or drop JSON exports
(`[{author, rating, text, date}]`) into `data/inbox/reviews`. A review cycle
opens quarterly (configurable via the `review_cycle_months` setting, or the
"Open a review cycle now" button): a `review_themes` claude job drafts
praise/complaint themes and suggested actions, the actions land in the
practice-improvement backlog on the **Reviews** page, and sign-off creates a
confirmed Cat 2 activity with the feedback summary (including actions
completed since previous cycles) as evidence.

**PDP:** the **PDP** page is a guided RACP-template form; "queue Claude
pre-draft" turns your stated goals + activity register into a `pdp_draft` job.
Completing the plan generates the evidence document, logs a confirmed Cat 2
activity, and ticks the mandatory-items tracker.

**Email harvest:** run a monthly Claude Code session with the Gmail connector
using [scripts/email-harvest.md](scripts/email-harvest.md) — it posts draft
activities with `external_ref` dedupe, so re-runs are safe and nothing counts
until you confirm it in the Inbox.

**Evidence:** any activity's edit page now accepts file uploads (stored
hash-stamped in the evidence vault) and serves existing artefacts back.

## Logging research/development time from Claude Code

Add this to the `CLAUDE.md` of each medical dev project (or your global `~/.claude/CLAUDE.md`). The snippet is bash-style; Claude Code sessions on Windows should translate to their shell (in PowerShell use `$env:CPD_API_KEY` and `curl.exe`, not the `curl` alias):

```markdown
## CPD logging
At the end of each working session that involved medical research, reading, or
development of medical software, report the session to the CPD Companion:

    curl -s -X POST http://<server-ip>:8340/api/sessions \
      -H "X-API-Key: $CPD_API_KEY" -H "Content-Type: application/json" \
      -d '{"project": "<project name>", "active_minutes": <genuine active minutes>,
           "topics": ["<medical topics researched>"],
           "summary": "<one-paragraph account of what was researched/built>"}'

Report only genuine active time spent on medical research and learning; exclude
idle time and non-medical work. If the session had no CPD-relevant content, do
not post a report.
```

Session reports accumulate silently. Every Monday 06:00 they are rolled up into **draft** activities (one per project) which appear in the dashboard **Inbox** for your sign-off — nothing counts toward CPD totals until you confirm it (and you can trim the minutes when confirming).

## API summary

All `/api/*` endpoints require the `X-API-Key` header.

| Endpoint | Purpose |
|---|---|
| `POST /api/sessions` | Log a Claude Code session report |
| `POST /api/rollup` | Trigger the weekly rollup immediately |
| `GET/POST /api/activities`, `PATCH/DELETE /api/activities/{id}` | Activity CRUD. API callers can only create **drafts** and discard — confirming an entry (making it count) is dashboard-only, so automated clients can never self-certify hours. `external_ref` deduplicates re-runs. DELETE is a soft discard. |
| `GET /api/jobs`, `POST /api/jobs/{id}/result`, `POST /api/jobs/{id}/fail` | The LLM/transcription job queue drained by `drain_whisper.py` and `drain_claude.ps1` |
| `GET /api/progress?year=2026` | Category totals vs RACP minimums |
| `GET /health` | Liveness check (no auth) |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
