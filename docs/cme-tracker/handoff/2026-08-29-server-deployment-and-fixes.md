# Handoff — 2026-08-25/29: server deployment, feed + PBS fixes, turnaround semantics

Branch `claude/cpd-companion-phase-2-2hklwj`, head `890b353`. 72 tests green.
The app is deployed and running on the Windows server.

## What this session did

Took the code-complete branch from "never run on the server" to deployed,
smoke-tested and in daily use.

### Deployment (native, not Docker)

The server has **no Docker Desktop and no WSL2**, and installing them needs
admin plus a reboot — the user's call. The app is plain FastAPI + SQLite with
pure-Python dependencies, so it runs from a venv instead. Full detail in
[DEPLOYMENT.md](../DEPLOYMENT.md). Two venvs (`.venv`, `.venv-whisper`), data
at `cpd-companion\data\`, two scheduled tasks, `start.bat` as the front door.

### Environment problems found and solved

- **Norton 360 intercepts TLS** with its own root CA. certifi alone rejects
  every outbound HTTPS call, so pip, feed polling, PubMed, PBS and Places all
  failed. Fixed with a combined certifi+Norton bundle wired into `.env`.
- **faster-whisper on the RTX 5090**: model loads without the CUDA DLLs, then
  dies at the first encode. `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` plus
  their `bin` dirs on PATH, done by `scripts\drain-whisper.ps1`. Verified with
  real TTS-synthesised audio: accurate transcript, ~3.4x realtime.
- **`Start-Process` leaks the launcher's stdout handle** to the server, hanging
  any caller that reads it. `start-cpd.ps1 -Detach` goes through `cmd start`.

### Real bugs fixed

1. **PBS monthly diff tracked zero items, permanently.** `/items` carries no
   ATC field at all, so the ATC prefix filter matched nothing. ATC now joins
   from `/item-atc-relationships` (highest `atc_priority_pct` wins).
2. **PBS paging stopped after page 1.** It paged on `_meta.total_pages`, which
   v3 never sends; the default-to-current-page fallback guaranteed an immediate
   break. Now pages on `total_records`, retries 429s, and accumulates brands
   per code so row ordering never reads as a change.
3. **`drain_claude.ps1` reported success when unauthenticated.** `claude -p`
   prints "Failed to authenticate" and still exits 0 — the nightly task would
   have looked green while draining nothing every night. Now exits 1.
4. **Four feeds were wrong.** JAMA Neurology `onlineFirst_16.xml` 404s (real id
   is `site_16/onlineFirst_72.xml`); Medscape legacy id 2698 serves **Urology**
   headlines (neurology is 2684); Lancet `laneur_online.xml` carries ~2 entries
   vs 21 on the issue TOC feed; the AAN eTOC URL was fine and its "unverified"
   note was cleared. All 14 feeds now poll green.
5. **Reading timer stopped when you opened the article.** The tick loop skipped
   while `document.hidden`, but "Open source" opens a new tab — so reading the
   actual article banked only the seconds before the click. Now one item (the
   last whose source was opened) keeps counting while hidden, capped at 30
   minutes per hidden stretch and reset on return. Script moved to
   `app/static/digest-timer.js` and verified in a real browser.
6. **Turnaround measured the wrong thing.** Was instruction-date -> report, and
   the instruction date came from a loose 120-char window after *any* mention
   of "the letter of instruction" reduced with `min()` — so prose like "the
   facts set out in the letter of instruction. The history was of a collision
   on 5 January 2025" captured the accident date and silently nulled the
   metric. Per Ron: turnaround is now **appointment -> completed report**, with
   anchored appointment patterns only and no inference when absent.

### Configuration tuned

`pbs_atc_prefixes` narrowed from `N02C,N03,N04,N07,L04`. The post-2023 WHO ATC
split the old flat `L04AA` into mechanism subgroups, so MS/neuromuscular agents
can be kept while the TNF/interleukin/JAK/mTOR/calcineurin blocks are dropped:
**1507 tracked items -> 551, non-neurology ~70% -> ~5%**. The old default also
missed the injectable MS DMTs entirely (interferon beta and glatiramer are
`L03A` immunostimulants, not immunosuppressants) and botulinum toxin
(`M03AX01`); `N06D` was added so an anti-amyloid PBS listing is caught
automatically. Researched by subagent, independently re-verified against the
raw API before applying.

### Schema

The deployed DB now holds real data, so the disposable-DB assumption is dead.
`db._ADDED_COLUMNS` + `_apply_added_columns()` apply new **columns**
idempotently at startup — that is how `reports.appointment_date` reached the
live DB with 316 news items intact. Renames, type changes and new constraints
still need a real migration path built first.

### Security

The repo-root `.env` (old n8n starter kit, not read by this app) was **tracked
by git**, and API keys had been pasted into it by mistake. Nothing was
committed. Keys moved to `cpd-companion\.env` under the names the app actually
reads (`PubMedAPIKey` would never have been picked up — config reads
`CPD_NCBI_API_KEY`), root file restored, untracked and gitignored.
`scripts\set_dashboard_password.py` was added so the password is never typed
into the wrong file again.

## Open items

The next-session prompt is
`C:\Users\drron\AI-Projects\next session prompts\CPD program\2026-08-29-pubmed-integration-and-first-real-data.md`.

Headlines:

1. **Wire in the PubMed LLM analyser** (port 5090) so case-research time
   becomes draft Cat 1 via the existing `POST /api/sessions` -> weekly rollup
   path. Key stays server-side; measure, never estimate.
2. **`rollup.py` is the only activity-creating module that attaches no
   evidence** — verified: six modules insert into `activities`,
   `medicolegal.py`/`news.py`/`pdp.py`/`pipeline.py`/`reviews.py` all attach
   evidence, `rollup.py` does not. Breaks hard convention 5, drags the
   audit-readiness score, and is exactly the path PubMed time will use. Fix
   alongside item 1.
3. **`appointment_date` is unvalidated against real report wording** — the
   regex was only ever tested on synthetic documents.
4. Backfill trial, then merge to main.

## Blockers / notes

- jCodemunch indexing: see the ritual note in the commit; if the repo is not
  under `trusted_folders`, add it and re-run `index_folder`.
- The digest classifies 60 items per run by design, so the ~316-item backlog
  clears over several nights.
