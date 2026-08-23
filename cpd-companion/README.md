# CPD Companion

Self-hosted tracker for RACP MyCPD requirements. See [../docs/cme-tracker/SPEC.md](../docs/cme-tracker/SPEC.md) for the full specification and the research reports behind it.

**Phase 1 (this code):** FastAPI + SQLite app with dashboard (progress bars, activity log, draft inbox), the Claude Code session-logging endpoint with weekly rollup into draft Category 1 activities, MyCPD CSV export, and nightly backups.

## Run it (Windows server, Docker Desktop)

```powershell
cd cpd-companion
copy .env.example .env
# edit .env: set CPD_API_KEY, CPD_DASHBOARD_PASSWORD, CPD_SECRET_KEY
docker compose up -d --build
```

Dashboard: http://localhost:8340 (or http://<server-ip>:8340 from other LAN devices).
Data (SQLite db, evidence, nightly backups) lives in `cpd-companion/data/` on the host — include it in your normal backup routine.

Without Docker: `pip install -r requirements.txt`, set the same env vars plus `CPD_DATA_DIR=C:\cpd-data`, then `uvicorn app.main:app --host 0.0.0.0 --port 8340`.

## Logging research/development time from Claude Code

Add this to the `CLAUDE.md` of each medical dev project (or your global `~/.claude/CLAUDE.md`):

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
| `GET/POST /api/activities`, `PATCH/DELETE /api/activities/{id}` | Activity CRUD (used by later modules and the email-harvest runner) |
| `GET /api/progress?year=2026` | Category totals vs RACP minimums |
| `GET /health` | Liveness check (no auth) |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
