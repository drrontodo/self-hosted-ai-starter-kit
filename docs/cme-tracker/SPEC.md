# RACP CPD Companion — Specification

A self-hosted program that captures the CPD-eligible work Dr. already does (medical software development and research, medicolegal reporting, practice feedback, reading, peer discussion), turns it into properly evidenced RACP MyCPD entries, and shows live progress against the 2026 framework minimums.

**Design principle:** the tracker records *real activity as it happens* and packages it with RACP-acceptable evidence. Every auto-drafted entry requires explicit sign-off before it counts; nothing is invented. This matters because RACP audits 5% of participants annually at random and reports non-compliance to Ahpra, and evidence must "clearly demonstrate the hours claimed."

Companion documents: [research/racp-2026-framework.md](research/racp-2026-framework.md) (framework rules, evidence requirements, sources) and [research/news-sources.md](research/news-sources.md) (verified feed/API inventory).

---

## 1. The target: RACP 2026 requirements at a glance

| Requirement | Minimum | How this program fills it |
|---|---|---|
| Total | 50 h/year | Sum of all modules |
| Cat 1 — Educational Activities | 12.5 h | M1 research/dev time, M3 news & journal reading, harvested meetings/webinars (M6) |
| Cat 2 + Cat 3 combined | 25 h | M2 + M4 (Cat 2) and M5 + audits (Cat 3) |
| Cat 2 — Reviewing Performance | ≥ 5 h | M2 patient-feedback review, M4 peer case discussions, PDP + Annual Conversation tracker |
| Cat 3 — Measuring Outcomes | ≥ 5 h | M5 medicolegal report audit, mini clinical audits |
| Mandatory: PDP + Annual Conversation | annual | Checklist widget with RACP template links + due-date nudges |
| Mandatory: 2 × cultural safety, 2 × ethics activities | annual | Tagged-activity counter; M3 digest flags qualifying content (e.g. cultural-safety webinars, ethics articles) |

Key evidence rule that shapes the whole design: **personal calendar/diary records are only acceptable evidence for journal/reading logs**. Everything else needs artefacts — certificates, organiser emails, minutes, de-identified audit documents, documented case-discussion accounts, feedback summaries. Each module therefore produces a concrete evidence artefact, not just a time entry.

Deadlines the app tracks: CPD year = calendar year; record in MyCPD by 31 March of the following year; audit evidence due 30 June.

### Filling Categories 2 and 3: the playbook

Category 1 fills itself from reading; Cat 2 and Cat 3 need deliberate but cheap structures. Beyond the core modules:

**Category 2 (reviewing performance):**
- **Recorded Annual Conversation** — record the conversation (with your colleague's consent), faster-whisper transcribes it locally, an LLM job drafts the RACP template + reflection from the transcript, you sign off (see M7).
- **Letter peer-review exchange** — swap 5 de-identified letters with a colleague each quarter, structured feedback both ways; each side gets Cat 2 hours and the documented feedback is the evidence. The app schedules it and generates the feedback form.
- **Solicitor/barrister feedback on medicolegal reports** — feedback on your reports is peer review of your work product; log it when it arrives (quick-add), with the correspondence as evidence.
- **Referrer feedback** — GP comments on your letters/management, same pattern.
- **Presenting at journal club / grand rounds** with feedback captured — presenting is Cat 1 teaching, the feedback on your presentation is Cat 2.
- **Multi-source feedback (MSF)** — annual short survey to staff/colleagues; a later phase can generate the survey link and collate results.

**Category 3 (measuring outcomes) — audits that fall out of data the practice already has:**
- **EVOLVE top-5 audit** — prescribing/ordering vs the RACP-endorsed low-value-care list for neurology; the most "RACP-native" audit available.
- **NCS/EMG report turnaround and quality** — digital data already exists.
- **Headache clinic outcomes** — MIDAS/HIT-6 pre/post for CGRP agents/Botox; doubles as payer/marketing evidence that treatment works.
- **MS DMT safety-monitoring compliance** — bloods/JCV/MRI schedules met on time.
- **Epilepsy driving-advice documentation audit** — % of relevant consults with documented advice; classic medicolegal risk reducer.
- **Autonomic testing diagnostic-yield audit** — tilt-table/autonomic outcomes at Autonomics Australia; both CPD and a publishable service differentiator.
- **Practice incident/near-miss log** — quick-add incidents as they happen; the log itself is "incident reporting and monitoring" (a named Cat 3 activity).
- **Practice outcomes/M&M meeting** — see below.

**Hospital Zoom M&M vs running your own:** do both, they're not alternatives. Keep attending the hospital M&M — it's zero setup and already happening; just capture evidence (ask the organiser to email minutes/attendance, or log it with the calendar invite + a 3-line account). *Additionally* run a lightweight **quarterly practice outcomes meeting** (30–45 min, you + a colleague or practice staff): the app generates the agenda automatically from the quarter's incident log, audit metrics and complaint themes, and minutes it via M7 recording→transcription. A solo practice rarely has enough mortality for a true M&M, so frame it as "clinical incidents and outcomes review" — that's squarely Cat 3, fully auto-evidenced, under your control, and it's also just good governance for the practice.

## 2. Architecture

```
Windows server (i9 / RTX 5090 / 64 GB)
│
├─ Docker Desktop
│   └─ cpd-companion container
│       ├─ FastAPI app  (REST API + server-rendered HTML dashboard)
│       ├─ SQLite database  (WAL mode, on a mounted volume)
│       ├─ APScheduler  (in-process job scheduler — no n8n/Postgres needed)
│       └─ /data volume:  cpd.db, evidence/, inbox/medicolegal/, inbox/reviews/
│
├─ Claude Code CLI (host, Max subscription — NOT API calls)
│   └─ Windows Task Scheduler task: claude -p drains the app's LLM job queue
│
└─ (optional, later) Tailscale for phone access
```

Decisions locked in:

- **FastAPI + SQLite.** No Postgres. SQLite in WAL mode is more than sufficient for a single-user tracker; one file to back up. The existing n8n starter-kit stack is *not* required — scheduling is in-process via APScheduler, so the whole thing is one container. (n8n can still be added later for exotic integrations; nothing depends on it.)
- **LLM work runs through Claude Code, not the Anthropic API.** The app never calls an LLM itself. Instead it maintains an **LLM job queue**:
  - `GET /api/llm/jobs?status=pending` — returns pending jobs (news summarisation, review-theme drafting, audit drafting), each with a self-contained prompt and input payload.
  - `POST /api/llm/jobs/{id}/result` — Claude posts the result back.
  - A scheduled Windows task (nightly, or on demand) runs `claude -p "Drain the CPD Companion job queue at http://localhost:8340 using key %CPD_API_KEY%; fetch pending jobs, complete each, post results back."` — headless Claude Code on the Max subscription. A `CLAUDE.md`/skill in a small `cpd-runner/` folder gives it the exact contract.
  - This also degrades gracefully: if the queue isn't drained, the dashboard shows raw items instead of summaries — nothing breaks.
- **Auth:** single static API key (env file) for all write endpoints; session cookie login (single user, bcrypt-hashed password from env) for the dashboard. LAN-only at first.
- **Phone access later:** recommended path is **Tailscale** on the server + phone — dashboard reachable from anywhere with zero public exposure, no reverse-proxy/HTTPS/hardening work, and the login page already exists. (A Caddy + DNS + public HTTPS setup remains possible later; nothing in the design precludes it.)
- **Timezone:** Australia/Sydney everywhere; CPD year boundaries computed in local time.
- **Backups:** nightly APScheduler job copies `cpd.db` + `evidence/` to a dated zip in `/data/backups` (keep 30); this is the audit survival kit.

### Data model (SQLite)

- `activities` — id, date, category (1/2/3), activity_type (reading, research_dev, patient_feedback, peer_discussion, audit, meeting, teaching, other), title, description, reflection, minutes, source_module, status (**draft → confirmed**), tags (cultural_safety, ethics), created_at, confirmed_at
- `evidence` — id, activity_id, kind (file, url, generated_doc, email_ref), path/url, sha256, created_at
- `sessions_log` — raw Claude Code session reports (M1) before they're rolled up into activities
- `reviews` — Google reviews: review_hash (dedupe key), author, rating, text, review_date, first_seen, cycle_id
- `news_items` — source, guid/link (dedupe), title, summary, abstract, published_at, llm_digest, read_at, read_seconds, starred
- `reports` — medicolegal inbox files: filename, sha256, detected_at, parsed metadata, audit_id
- `audits` — id, period, checklist_json, metrics_json, draft_text, final_text, status
- `llm_jobs` — id, kind, payload_json, prompt, status (pending/done/failed), result_json, created_at, completed_at
- `practice_outputs` — id, kind (info_sheet, opportunity_brief, newsletter, improvement_action, template_fix), source refs (news_item/review cycle/audit), target_site, status (idea/draft/published/done/dismissed), path
- `settings`, `mandatory_tracker` (PDP done?, Annual Conversation done?, cultural-safety count, ethics count)

All hours derive from `activities.minutes` on **confirmed** entries only.

## 3. Modules

### M1 — Research & development time logger (Cat 1)

The endpoint your Claude Code sessions write to at the end of a session.

- `POST /api/sessions` with API key. Payload: `{project, started_at, ended_at, active_minutes, topics: [...], summary, artefacts: [...], cpd_relevant: true/false}`.
- Adoption is one line in each dev project's `CLAUDE.md` (or a global `~/.claude/CLAUDE.md` instruction / Stop hook): *"At the end of each working session, POST a session report to the CPD Companion at http://<server>:8340/api/sessions (key in .env) covering what was researched/built, the medical topics involved, and active time."*
- Session reports land as `sessions_log` rows, then a weekly rollup creates **draft** Cat 1 activities grouped by project/topic. You confirm (and can trim minutes) from the dashboard — the sign-off step is what keeps claimed hours honest, since dev-tool time is not an RACP-listed activity and should be claimed as the *learning/research component* of the work (see research doc §2; worth a one-line confirmation email to MyCPD@racp.edu.au).
- Evidence artefact: a generated "research log" PDF per period — date, topic, minutes, one-line takeaway per session — matching the reading-log evidence pattern.

### M2 — East Neurology Google reviews (Cat 2: patient feedback)

- **Daily poll** of the Google Places API (Place Details, simple API key) for the East Neurology listing. The API only returns ~5 reviews per call, but daily polling with `review_hash` dedupe accumulates nearly all of them over time. Any gaps can be topped up by dropping a manual export into `inbox/reviews/` (parsed by the same pipeline).
- Reviews accrue silently. Every **3 months** (configurable to monthly) a review cycle opens: dashboard shows all reviews since the last cycle; an LLM job drafts a themes summary (praise themes, complaint themes, suggested practice actions); you edit, add your reflection and actions taken, and sign off.
- Each cycle also emits a **practice improvement backlog**: concrete action items extracted from complaint/suggestion themes (booking friction, comms, waiting times, report delivery…), tracked to done/dismissed on the dashboard. Closing the loop is a business win *and* strengthens the Cat 2 evidence — "actions taken in response to feedback" is exactly what a practice-review document should show (see §5).
- Output: a **draft Cat 2 activity** (time = actual time you spent in the review screen, tracked automatically while the cycle page is open) + a generated "Patient feedback review — Q3 2026" PDF as evidence (themes, actions, your reflection — RACP's named evidence type for patient feedback).

### M3 — Neurology news digest & reading log (Cat 1)

- Feed poller (APScheduler + `feedparser`/`httpx`) over the shortlist in the research doc: TGA alerts + news, 2–6 PubMed saved-search RSS feeds (stroke, epilepsy, MS, movement disorders, headache, neuropathy — RCT/guideline filtered), Neurology (AAN) eTOC, JAMA Neurology Online First, Lancet Neurology, NeurologyLive, Medscape neurology RSS (headlines only — no login automation; it's ToS-prohibited and brittle. Feed URL to be confirmed from your network; login stays for manual click-through).
- Two API jobs: **PBS Schedule API monthly diff** (new/changed neurology listings — automated "new PBS drugs" section) and **Stroke Foundation living-guidelines page** monthly scrape-and-diff.
- Nightly LLM job: cluster + summarise new items into a digest (sections: Drugs & regulatory AU, Guidelines, Stroke, Epilepsy, MS, Movement disorders, Headache, Neuropathy, General), flagging items that plausibly qualify for the cultural-safety/ethics mandatory counters.
- **Reading time tracking:** the digest page runs a visibility-aware timer (pauses when tab hidden); marking an item read stamps `read_at`/`read_seconds`. A weekly rollup drafts a Cat 1 reading activity with minutes summed from actual reading time.
- Every digest item carries **action buttons** that turn reading into practice output (see §5): *Draft patient info sheet*, *Flag as service opportunity*, *Add to referrer newsletter*. Each button queues an LLM job — reading stops being a cost centre and starts producing website content and business leads.
- Evidence artefact: generated **reading log** (date, source, title, minutes, one-line takeaway) — the one activity where diary-style logs are explicitly acceptable, so this module is fully audit-proof by construction.

### M4 — Peer case discussion log (Cat 2)

- Friction is the enemy: a quick-add form reachable in two taps — date (defaults today), colleague, case theme (no patient identifiers), key learning/outcome, minutes. Optional voice-note field later.
- Each entry generates a "documented account of case discussion" — RACP's explicitly named Cat 2 evidence — and is immediately a confirmed Cat 2 activity (you wrote it yourself; no LLM draft needed).
- MDT/journal-club attendance can be logged here too, with an email/minutes reference attached as evidence.

### M5 — Medicolegal report audit (Cat 3)

- You drop finished reports (docx/pdf) into a watched folder (`/data/inbox/medicolegal`, mapped to a normal Windows folder). A scheduled scan detects new files by hash.
- **Monthly audit job:**
  1. Objective metrics extracted in code: report count, dates, turnaround (where a referral/instruction date is parseable), length, presence of required sections (qualifications, instructions, facts, opinion, declaration — checklist configurable to your jurisdiction's expert-witness code).
  2. LLM job (local Claude Code run — reports never leave the server) audits each report against your checklist and drafts a monthly audit summary: compliance rates, trends vs previous months, improvement suggestions.
  3. You review, edit, sign off → **Cat 3 activity** (time actually spent reviewing, timer-tracked) + a **de-identified** audit document as evidence (patient/party names stripped by the generator; RACP explicitly accepts de-identified audit documents).
- The month-on-month metrics make this a genuine standards-based audit cycle (measure → reflect → re-measure), which is exactly what Cat 3 requires.

### M5b — Medicolegal response library (Q&A extraction)

The same report archive that feeds the audit is also the practice's best knowledge base: over the years the doctor has answered the same solicitor questions (causation, prognosis, work capacity, permanent impairment…) many times, and currently keeps reusable phrasings as hard-coded comments in the medicolegal reporting program's intranet — hard to search, hard to maintain. The library turns that into a first-class asset:

- **Extraction pipeline:** a `report_extract` claude job per report (local runner) takes the report text (code-level pre-redaction of RE: lines, DOBs, claim numbers first), **de-identifies it absolutely**, and distils the Q&A sections and opinion passages into generic template responses — `{condition, topic, question, answer}` — keeping the doctor's own reasoning and turns of phrase but replacing case specifics with placeholders (`[duration]`, `[side]`, `[occupation]`). Only reasoning actually present in the report is extracted; boilerplate is skipped.
- **Curation is mandatory:** extracted snippets land as *drafts* on the Library page. The doctor edits (including a de-identification check — nothing case-specific may survive), approves into the library, or rejects. Nothing enters the library without human sign-off — the same integrity model as activities.
- **Search & reuse:** the Library page is full-text searchable (condition / topic / question / answer) — this replaces "struggling to find that response from two years ago". Approved snippets export as markdown and JSON for import into the medicolegal app / intranet.
- **Gradual backfill:** at 4–6 reports/week the archive is large; old reports dropped into `inbox/medicolegal/backfill` are hash-detected like new ones but **excluded from the monthly audits** (which measure the month's actual output) and mined in small weekly batches (default 5, configurable) so the queue drains steadily without a bulk-processing session.
- **CPD claim:** reviewing one's own written opinions and standardising them is review of one's own work product — Category 2 (reviewing performance). The Library page timer tracks curation time; "log session" creates a confirmed Cat 2 activity whose evidence document lists the (generic, de-identified) snippets reviewed that session.

### M6 — Retrospective harvest & everything else

- **Email harvest (meetings, webinars, conference registrations, CPD certificates):** rather than building Gmail OAuth into the app, this runs as a monthly Claude Code session using the Gmail connector (already linked to your Claude account — it's available in this session). The job: search the last month for meeting invites/attendance confirmations/registration receipts/certificates, and POST draft activities + evidence references to the API. Retrospective back-fill for the year so far works the same way with a wider date range.
- **Mandatory-items widget:** PDP done? Annual Conversation done? (links to the RACP templates, due-date nudges early in the year, upload slot for the completed template = evidence). Counters for cultural-safety and ethics activities with suggestions from the digest when a counter is behind.
- **PDP builder:** a guided form following the RACP PDP template structure (development goals, planned CPD activities per category, timeframes, success measures). A claude job pre-drafts it from your stated goals plus last year's activity register and the current year's gaps; you edit and sign off. Output: completed PDP document as evidence + the mandatory-tracker box ticked + a Cat 2 activity for the time spent. The digest can then flag items matching your PDP goals ("this trial is relevant to goal 2").
- **Other one-click activity templates** (from the framework research): journal club, grand rounds, literature search for a patient, teaching/supervision, referrer feedback received, incident review, mini clinical audit (e.g. EMG turnaround, migraine prophylaxis vs guidelines, EVOLVE recommendations) — each template pre-fills category and the evidence type RACP expects.

### M7 — Voice capture & local transcription (faster-whisper)

- Audio in: upload from the dashboard (phone-friendly), or drop files into `inbox/audio/`. Sources: Annual Conversation recordings, peer case discussions on the go, practice outcomes-meeting recordings, dictated reflections.
- The generic `jobs` queue carries an `engine` field: `claude` jobs are drained by the nightly Claude Code run; `whisper` jobs are drained by a small script on the Windows host that runs the already-installed **faster-whisper** (RTX 5090 makes this near-instant) and posts the transcript back.
- Pipeline: audio → whisper job (transcript) → claude job (structured minutes/reflection/RACP-template draft appropriate to the recording type) → inbox draft → sign-off → activity + evidence document. Audio and transcripts never leave the server.
- Consent note: record conversations only with the other party's knowledge and consent (NSW surveillance-devices law); the upload form carries a consent checkbox as a record.

## 4. Dashboard (HTML, server-rendered + htmx)

- **Home:** progress bars — total/50 h, Cat 1/12.5, Cat 2+3/25 with per-category ≥5 floors; mandatory checklist; "pace" indicator (hours vs day-of-year); pending drafts awaiting sign-off; audit-readiness score (% of confirmed entries with evidence attached).
- **Digest:** the M3 news reader with reading timer.
- **Inbox:** drafts to confirm (sessions rollups, review cycles, audit drafts, email harvest) — confirm/edit/discard.
- **Log:** all activities, filter by category/type/status; add-entry and quick-add forms.
- **Evidence vault:** every artefact, linked to its activity, hash-stamped.
- **Export:**
  - CSV matching MyCPD entry fields (date, category, activity type, hours, description) for fast transcription into MyCPD (no MyCPD API exists — entry remains a short manual step, but reduced to copy-paste).
  - **Audit bundle:** one zip per CPD year — activity register + all evidence artefacts — i.e. the 30-June audit response, pre-built.
- Mobile-first CSS (it's the phone use-case for the digest and quick-add).

## 5. Practice growth loop — turning CPD activity into business output

The same pipelines that earn CPD hours can produce assets for East Neurology (and Autonomics Australia and the other practice sites). A `practice_outputs` table tracks each asset from idea → draft → published, linked back to the triggering news item, review cycle, or audit.

### News → patient info sheets → website content
- Any digest item (new drug, new test, new guideline) has a one-click **"Draft patient info sheet"** action. The queued LLM job runs through the Claude Code runner, which uses the existing **East Neurology patient-page house style** (the `east-neuro-patient-page` skill already defines the design system for eastneurology.com.au, autonomicsaustralia.com.au, potstestingsydney.com.au, burningfeet.com.au, sydneyheadachecentre.com.au, neurologylegal.com.au) to produce a ready-to-review HTML page.
- You review/edit clinically, then publish to the relevant site. Each sheet is fresh, guideline-current SEO content — the sites grow a condition/treatment library as a by-product of your reading.
- CPD angle: developing patient education material is itself claimable educational/teaching activity, and writing the sheet is documented evidence that the reading was applied.

### News → new service lines (the Autonomics Australia pattern)
- A **quarterly opportunity scan**: an LLM job reviews the quarter's accumulated news, PBS diffs and guideline changes and drafts 2–3 one-page "service opportunity briefs" — e.g. a newly PBS-listed CGRP agent → headache clinic capacity/infusion pathway; new autonomic testing evidence → expand Autonomics Australia offerings; a new monitoring requirement for an MS drug → structured monitoring clinic; a new diagnostic antibody panel → add to work-up protocols and referrer education.
- Each brief covers: the clinical development, patient population locally, what the practice would need (equipment, item numbers, referral pathways), competitors in Sydney, and a go/no-go recommendation. Briefs land in the inbox as drafts — most will be discarded, but this is exactly how one article becomes the next Autonomics Australia.
- The **PBS monthly diff is the strongest automatic trigger** here: a new neurology listing is simultaneously CPD reading, a patient info sheet ("now available on the PBS"), and often a service opportunity.

### Reviews → practice improvement backlog
- As per M2: every feedback cycle emits tracked improvement actions. Completed actions feed back into the next cycle's summary ("what we changed"), which is both good Cat 2 evidence and visible service improvement patients notice in later reviews.

### Referrer newsletter (GP marketing that is also teaching)
- Items flagged "referrer-relevant" accumulate into a quarterly **"What's new in neurology" newsletter for referring GPs** — LLM-drafted from already-summarised digest items, your sign-off, sent from the practice. It markets the practice to its actual customer (referrers), positions you as the update source, and plausibly counts as an educational/teaching activity with the newsletter itself as evidence.

### Medicolegal audit → medicolegal business
- M5's metrics double as business KPIs: turnaround time trends (fast, predictable turnaround is the main thing solicitors buy), report-structure consistency, and template weaknesses the audit surfaces → template improvements → fewer requisitions/clarification requests. A "capability statement" stat (median turnaround, reports/year) can be lifted straight from the audit data for neurologylegal.com.au.

### Efficiency flywheel
- Everything drafted once (info sheets, newsletter, briefs) is stored with its source links, so later updates ("this sheet cites the 2026 guideline — a 2027 update just appeared in the digest") can be flagged automatically: the digest matcher checks new items against published `practice_outputs` and queues refresh suggestions.

## 6. Build plan

| Phase | Scope | Outcome |
|---|---|---|
| 1 | FastAPI skeleton, SQLite schema, auth, activities CRUD, dashboard home + log, M1 sessions endpoint + weekly rollup, CSV export | Claude sessions logging real dev/research time; manual entries possible; progress bars live |
| 2 | M3 feeds + digest + reading timer + reading-log evidence; LLM job queue + `cpd-runner` Claude Code contract | Daily digest with counted reading time |
| 3 | M5 medicolegal watcher + metrics + audit drafting + sign-off; M4 quick-add; M7 audio upload + whisper/claude job pipeline | Cat 3 engine running monthly; recordings become minutes |
| 4 | M2 Places API poller + review cycles + improvement backlog; M6 mandatory widget + templates + email-harvest runner prompt | All six modules live |
| 5 | Practice growth loop: info-sheet action, opportunity scan, referrer newsletter, output tracking | Reading produces website content and service briefs |
| 6 | Backups, audit bundle export, Tailscale notes, polish | Audit-proof, phone-accessible |

Deployment: `docker compose up -d` from a new `cpd-companion/` directory in this repo (own compose file — does not require the starter-kit stack), plus a documented Windows Task Scheduler entry for the nightly `claude -p` queue-drain. Config via `.env` (API key, dashboard password, Google Places key, place ID, PubMed/NCBI key, Medscape creds *only* as a convenience login bookmark — never used by automation, folder paths).

## 7. Open questions (non-blocking; defaults will be used unless changed)

1. **Tailscale** acceptable for phone access, or do you want a public HTTPS domain? (Default: Tailscale.)
2. Review cycle **monthly or quarterly**? (Default: quarterly, per your original note — configurable.)
3. Medicolegal audit checklist: default to a generic expert-report checklist (qualifications, instructions, facts/opinion separation, reasoning, declaration, turnaround), or supply your own criteria to encode? Which jurisdiction's expert-witness code should the section checklist follow (NSW UCPR Sch 7 assumed)?
4. Confirm East Neurology **Google Place ID** and whether you can create a Google Cloud API key (2-minute job; needed for M2 daily polling).
5. The PubMed saved-search RSS feeds need to be created once from your browser (Create RSS button) — or the app can use the E-utilities API directly with no setup (default: E-utilities, zero manual steps).
6. Recommend a one-line email to MyCPD@racp.edu.au confirming how they'd like software-development-as-research time categorised (see research doc §2 — it's not an RACP-listed activity; reading/research components are safely Cat 1 regardless).
