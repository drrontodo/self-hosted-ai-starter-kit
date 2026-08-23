# CPD Companion

Self-hosted tracker for RACP MyCPD requirements. See [../docs/cme-tracker/SPEC.md](../docs/cme-tracker/SPEC.md) for the full specification and the research reports behind it.

**Built so far (Phases 1 + M7):** FastAPI + SQLite app with dashboard (progress bars, mandatory-items checklist, audit-readiness score, activity log, draft inbox), the Claude Code session-logging endpoint with weekly rollup into draft Category 1 activities, the meeting-recording pipeline (upload → local faster-whisper transcription → de-identified minutes via Claude Code → draft entry with evidence), MyCPD CSV export, and nightly backups.

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
