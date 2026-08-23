# CPD Companion — monthly email harvest (Claude Code + Gmail connector)

Run this as a monthly Claude Code session (interactive or scheduled) with the
Gmail connector available. The CPD Companion runs at http://localhost:8340 and
the API key is in the environment variable `CPD_API_KEY`.

## The job

Search the last month of Gmail (or a wider range for a back-fill) for evidence
of CPD-claimable events, and post **draft** activities to the CPD Companion.
Look for:

- meeting/webinar invites you accepted and attendance confirmations
  (grand rounds, journal clubs, ANZAN/RACP events, M&M meetings)
- conference or course registration receipts
- CPD certificates and certificates of attendance
- speaker/teaching invitations you accepted

## Posting

For each event found, `POST /api/activities` with header
`X-API-Key: $CPD_API_KEY` and JSON:

```json
{
  "date": "<event date, YYYY-MM-DD>",
  "category": 1,
  "activity_type": "meeting",
  "title": "<event name>",
  "description": "<what it was; who organised it; source email subject + date>",
  "minutes": <duration from the invite; if unknown, use 60 and say so in the description>,
  "source_module": "email_harvest",
  "external_ref": "gmail-<message-id>"
}
```

Rules:

- `external_ref` = `gmail-<message-id>` **always** — the server deduplicates on
  it, so re-running the harvest is safe. A 409 response means it is already
  logged; that is success, move on.
- Category guide: attendance at educational meetings/webinars/conferences → 1;
  presenting with feedback received, or peer-review exchanges → 2;
  audit-related meetings → 3. When unsure, use 1 — the category can be fixed at
  sign-off.
- Minutes must come from the invite/agenda; never estimate generously. If the
  duration is unknown, use 60 and flag it in the description for correction at
  sign-off.
- Teaching/committee work and journal-club presentations count too; note the
  role in the description.
- Do NOT post anything that is not evidenced by an actual email. Never invent
  events. Skip declined invites and promotional emails for events not attended.
- These land as **drafts** — the doctor confirms (and can fix minutes/category)
  in the dashboard Inbox. The API cannot self-certify hours by design.

Finish with a short table of what was posted (date, title, minutes) and how
many 409 duplicates were skipped, and remind the user to forward any
certificates to the evidence vault (attach via the activity's edit page).
