# Next-session prompt — pointer

The server deployment described in the previous version of this file is
**done**. The app is deployed and running natively on the Windows server
(branch `claude/cpd-companion-phase-2-2hklwj`, head `890b353`, 72 tests green).

The current, authoritative next-session prompt lives in the ritual folder:

    C:\Users\drron\AI-Projects\next session prompts\CPD program\
        2026-08-29-pubmed-integration-and-first-real-data.md

Its headline tasks:

1. **Wire in the PubMed LLM analyser** (`C:\Users\drron\AI-Projects\PubMed LLM
   analyser`, Flask, port 5090) so case-research time becomes a draft Cat 1
   activity via the existing `POST /api/sessions` → weekly rollup path.
2. **Fix the `rollup.py` evidence gap** at the same time — it is the only
   activity-creating module that attaches no evidence, and it is the path
   PubMed research time will flow through.
3. **Validate `appointment_date`** against real medicolegal reports; the regex
   has only ever seen synthetic documents.
4. First real backfill + curation, then merge to main.

Before changing anything, read:

- [`DEPLOYMENT.md`](DEPLOYMENT.md) — how this server actually runs the app,
  and the Norton-TLS / CUDA-DLL / PBS gotchas.
- [`HANDOVER.md`](HANDOVER.md) — the binding conventions.
- [`handoff/2026-08-29-server-deployment-and-fixes.md`](handoff/2026-08-29-server-deployment-and-fixes.md)
  — what the deployment session changed and why.
