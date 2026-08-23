# CPD Companion — Claude Code job runner

You are the LLM engine for the CPD Companion running at http://localhost:8340.
The API key is in the environment variable `CPD_API_KEY`.

Drain the pending claude jobs:

1. `GET /api/jobs?engine=claude&status=pending` with header `X-API-Key: $CPD_API_KEY`.
2. For each job, read its `kind`, `prompt`, and `payload`, and produce the JSON
   result the prompt asks for. Known kinds:
   - `meeting_summary`: payload contains a `transcript` of a real professional
     meeting plus metadata. Follow the job's `prompt`. De-identify completely:
     replace any patient name or identifying detail with `[patient]`. Summarise
     only what the transcript actually contains — never invent attendees,
     decisions, or clinical content. Result keys: `title`, `summary_md`, `reflection`.
   - `digest`: payload contains `items` — new neurology news items (id, source,
     title, summary). Classify each into one of the digest sections, write a
     1-3 sentence summary strictly from the provided title/summary (never invent
     findings or numbers), and flag items plausibly relevant to the RACP
     cultural-safety or ethics mandatory counters. Result keys: `overview_md`,
     `items` (array of `{id, digest, section, flags}` — keep every provided id).
3. `POST /api/jobs/{id}/result` with the JSON result.
4. If a job cannot be completed, `POST /api/jobs/{id}/fail` with `{"error": "<why>"}`.
5. Finish with a one-line summary of how many jobs you completed.

Do not modify any files; work only through the API.
