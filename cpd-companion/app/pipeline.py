"""Meeting-recording pipeline (M7).

audio upload -> whisper job (transcript, drained by scripts/drain_whisper.py on
the host GPU) -> claude job (de-identified minutes + reflection draft, drained
by the nightly Claude Code run) -> draft activity + evidence, awaiting sign-off.
"""

import json
import re

from . import config, db, growth, medicolegal, news, pdp, reviews


def create_meeting(
    *,
    audio_filename: str,
    audio_bytes: bytes,
    meeting_type: str,
    date: str,
    participants: str,
    duration_minutes: int,
    notes: str,
) -> int:
    """Store the recording and queue the transcription job. Returns the job id."""
    config.ensure_dirs()
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", audio_filename) or "recording"
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (kind, engine, payload, prompt, created_at) VALUES"
            " ('transcribe_meeting', 'whisper', '', '', ?)",
            (db.now_iso(),),
        )
        job_id = cur.lastrowid
        audio_path = config.AUDIO_DIR / f"{job_id}_{safe_name}"
        audio_path.write_bytes(audio_bytes)
        payload = {
            "audio_file": audio_path.name,
            "meeting_type": meeting_type,
            "date": date,
            "participants": participants,
            "duration_minutes": duration_minutes,
            "notes": notes,
        }
        conn.execute("UPDATE jobs SET payload = ? WHERE id = ?", (json.dumps(payload), job_id))
    return job_id


def _summary_prompt(meta: dict) -> str:
    label = config.MEETING_TYPES.get(meta["meeting_type"], config.MEETING_TYPES["other"])["label"]
    return (
        f"You are preparing RACP CPD evidence from a transcript of a real meeting: "
        f"{label} on {meta['date']} with {meta['participants'] or 'colleagues'}.\n"
        "From the transcript in this job's payload, produce a JSON result with keys:\n"
        "  title: short title for the CPD entry\n"
        "  summary_md: structured minutes in markdown (attendees by role only, topics, key\n"
        "    clinical points, decisions/actions, learning outcomes)\n"
        "  reflection: 2-4 sentence first-person reflection draft\n"
        "STRICT RULES: de-identify completely — replace any patient name or identifying detail\n"
        "with [patient]; keep clinician names only if they are meeting participants. Summarise\n"
        "only what is actually in the transcript; never invent content, attendees, or outcomes."
    )


def handle_job_result(job_id: int, result: dict) -> dict:
    """Apply a posted job result; returns a description of what happened."""
    with db.tx() as conn:
        # Serialise with concurrent posts/failures so a job can only ever be
        # completed once (the drain script is sequential, but nothing forces
        # callers to be).
        conn.execute("BEGIN IMMEDIATE")
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            return {"error": "job not found"}
        if job["status"] != "pending":
            return {"error": f"job already {job['status']}"}
        meta = json.loads(job["payload"] or "{}")

        if job["kind"] == "transcribe_meeting":
            transcript = str(result.get("transcript", "")).strip()
            if not transcript:
                return {"error": "result must include a non-empty 'transcript'"}
            transcript_path = config.TRANSCRIPT_DIR / f"meeting_{job_id}.txt"
            transcript_path.write_text(transcript, encoding="utf-8")
            meta["transcript_file"] = transcript_path.name
            next_payload = dict(meta, transcript=transcript)
            cur = conn.execute(
                "INSERT INTO jobs (kind, engine, payload, prompt, created_at) VALUES"
                " ('meeting_summary', 'claude', ?, ?, ?)",
                (json.dumps(next_payload), _summary_prompt(meta), db.now_iso()),
            )
            follow_up = cur.lastrowid
            conn.execute(
                "UPDATE jobs SET status = 'done', result = ?, payload = ?, completed_at = ? WHERE id = ?",
                (json.dumps({"transcript_file": transcript_path.name}), json.dumps(meta),
                 db.now_iso(), job_id),
            )
            return {"job": job_id, "status": "done", "summary_job_id": follow_up}

        if job["kind"] == "meeting_summary":
            title = str(result.get("title", "")).strip()
            summary_md = str(result.get("summary_md", "")).strip()
            reflection = str(result.get("reflection", "")).strip()
            if not title or not summary_md:
                return {"error": "result must include 'title' and 'summary_md'"}
            mapping = config.MEETING_TYPES.get(meta.get("meeting_type"), config.MEETING_TYPES["other"])
            doc_path = config.EVIDENCE_DIR / f"meeting_{job_id}_minutes.md"
            doc_bytes = (
                f"# {title}\n\nDate: {meta.get('date')}\nParticipants: {meta.get('participants')}\n"
                f"Duration: {meta.get('duration_minutes')} minutes\n\n{summary_md}\n"
            ).encode("utf-8")
            doc_path.write_bytes(doc_bytes)
            now = db.now_iso()
            cur = conn.execute(
                "INSERT INTO activities (date, category, activity_type, title, description,"
                " reflection, minutes, source_module, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'meetings', 'draft', ?)",
                (
                    meta.get("date", db.today_iso()),
                    mapping["category"],
                    mapping["activity_type"],
                    title,
                    summary_md,
                    reflection,
                    int(meta.get("duration_minutes", 0)),
                    now,
                ),
            )
            activity_id = cur.lastrowid
            import hashlib

            evidence_rows = [(activity_id, "generated_doc", str(doc_path),
                              hashlib.sha256(doc_bytes).hexdigest(), now)]
            if meta.get("transcript_file"):
                transcript_sha = (
                    hashlib.sha256(str(meta.get("transcript", "")).encode()).hexdigest()
                    if meta.get("transcript") else None)
                evidence_rows.append(
                    (activity_id, "file", str(config.TRANSCRIPT_DIR / meta["transcript_file"]),
                     transcript_sha, now)
                )
            conn.executemany(
                "INSERT INTO evidence (activity_id, kind, path_or_url, sha256, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                evidence_rows,
            )
            # Scrub the transcript out of the completed job's payload; it lives
            # in TRANSCRIPT_DIR, not the jobs table.
            scrubbed = {k: v for k, v in meta.items() if k != "transcript"}
            conn.execute(
                "UPDATE jobs SET status = 'done', result = ?, payload = ?, completed_at = ?"
                " WHERE id = ?",
                (json.dumps({"activity_id": activity_id}), json.dumps(scrubbed), now, job_id),
            )
            return {"job": job_id, "status": "done", "draft_activity_id": activity_id}

        if job["kind"] == "digest":
            return news.apply_digest_result(conn, job, result)

        if job["kind"] == "medicolegal_audit":
            return medicolegal.apply_audit_result(conn, job, result)

        if job["kind"] == "report_extract":
            return medicolegal.apply_extract_result(conn, job, result)

        if job["kind"] == "review_themes":
            return reviews.apply_themes_result(conn, job, result)

        if job["kind"] == "pdp_draft":
            return pdp.apply_draft_result(conn, job, result)

        if job["kind"] == "info_sheet":
            return growth.apply_info_sheet_result(conn, job, result)

        if job["kind"] == "opportunity_scan":
            return growth.apply_opportunity_result(conn, job, result)

        if job["kind"] == "referrer_newsletter":
            return growth.apply_newsletter_result(conn, job, result)

        # Unknown kinds: store the result verbatim so future modules can define their own.
        conn.execute(
            "UPDATE jobs SET status = 'done', result = ?, completed_at = ? WHERE id = ?",
            (json.dumps(result), db.now_iso(), job_id),
        )
        return {"job": job_id, "status": "done"}


# Job kinds whose payloads carry bulky/sensitive text (report contents,
# transcripts): scrub them down to reference keys on any terminal status so
# the jobs table (and its nightly backups) never mirrors the source material.
_SENSITIVE_PAYLOAD_KINDS = ("report_extract", "meeting_summary", "transcribe_meeting")
_REFERENCE_KEYS = ("report_id", "audit_id", "cycle_id", "output_id", "year",
                   "item_ids", "meeting_type", "date", "audio_file",
                   "transcript_file", "duration_minutes")


def handle_job_failure(job_id: int, error: str) -> dict:
    """Mark a job failed and unwind module state so the work can be retried.

    Without this, a runner POSTing /fail (as claude-runner.md instructs) would
    permanently wedge the module that queued the job: reports stuck 'queued',
    info-sheet outputs stuck 'idea'. Audits and review cycles recover through
    their own requeue paths (ensure_monthly_audit / maybe_open_cycle)."""
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            return {"error": "job not found"}
        if job["status"] != "pending":
            return {"error": f"job already {job['status']}"}
        payload = json.loads(job["payload"] or "{}")
        stored_payload = job["payload"]
        if job["kind"] in _SENSITIVE_PAYLOAD_KINDS:
            stored_payload = json.dumps(
                {k: payload[k] for k in _REFERENCE_KEYS if k in payload})
        conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, payload = ?, completed_at = ?"
            " WHERE id = ?",
            (error[:2000], stored_payload, db.now_iso(), job_id),
        )
        if job["kind"] == "report_extract" and payload.get("report_id"):
            conn.execute(
                "UPDATE reports SET extract_status = 'pending'"
                " WHERE id = ? AND extract_status = 'queued'",
                (payload["report_id"],),
            )
        if job["kind"] == "info_sheet" and payload.get("output_id"):
            conn.execute(
                "UPDATE practice_outputs SET status = 'dismissed', notes = ?,"
                " updated_at = ? WHERE id = ? AND status = 'idea'",
                (f"drafting job failed: {error[:200]}", db.now_iso(),
                 payload["output_id"]),
            )
    return {"job": job_id, "status": "failed"}


def meeting_queue_overview() -> list[dict]:
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE kind IN ('transcribe_meeting', 'meeting_summary')"
            " ORDER BY id DESC LIMIT 30"
        ).fetchall()
    out = []
    for r in rows:
        meta = json.loads(r["payload"] or "{}")
        meta.pop("transcript", None)
        out.append({
            "id": r["id"], "kind": r["kind"], "engine": r["engine"], "status": r["status"],
            "created_at": r["created_at"], "meta": meta,
        })
    return out
