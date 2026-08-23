"""M5b response library tests: backfill separation, pre-scrub, extraction
batching, curation, search, export, and the Cat 2 curation log."""

import json
from pathlib import Path

from tests.test_app import KEY, client, login  # noqa: F401 - reuse env setup + fixture
from app import config, db, medicolegal

BACKFILL_TEXT = """Expert report.
RE: Smith v Acme Pty Ltd
Date of birth: 12/03/1971
Claim number: XY-4451-B
Qualifications: consultant neurologist.
Question 1: Is the diagnosis of mild traumatic brain injury correct?
Answer: In my opinion the diagnosis is correct because the acute features
(brief loss of consciousness, post-traumatic amnesia of less than 24 hours)
satisfy the accepted criteria.
Opinion: prognosis for recovery within 12 months is good.
Dated 5/5/2024.
"""


def _drop_backfill(name: str, text: str) -> Path:
    config.ensure_dirs()
    path = config.MEDICOLEGAL_BACKFILL / name
    path.write_text(text)
    return path


def test_backfill_scanned_but_excluded_from_audit(client):
    _drop_backfill("old-2024-report.txt", BACKFILL_TEXT)
    new = medicolegal.scan_inbox()
    assert len(new) == 1
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM reports WHERE filename = 'old-2024-report.txt'"
                           ).fetchone()
    assert row["backfill"] == 1
    assert row["extract_status"] == "pending"
    # excluded from the monthly audit for its detected month
    period = row["detected_at"][:7]
    out = medicolegal.ensure_monthly_audit(period)
    if out["status"] not in ("no_reports", "signed_off"):
        with db.tx() as conn:
            attached = conn.execute("SELECT audit_id FROM reports WHERE id = ?",
                                    (row["id"],)).fetchone()["audit_id"]
        assert attached is None


def test_extraction_queue_prescrub_and_batching(client):
    login(client)
    # make the batch deterministic regardless of reports other test modules left
    with db.tx() as conn:
        conn.execute(
            "UPDATE reports SET extract_status = 'done' WHERE extract_status = 'pending'"
            " AND filename != 'old-2024-report.txt'")
    _drop_backfill("old-2024-second.txt",
                   BACKFILL_TEXT.replace("mild traumatic", "moderate traumatic"))
    medicolegal.scan_inbox()
    with db.tx() as conn:
        first_id = conn.execute(
            "SELECT id FROM reports WHERE filename = 'old-2024-report.txt'"
        ).fetchone()["id"]
        second_id = conn.execute(
            "SELECT id FROM reports WHERE filename = 'old-2024-second.txt'"
        ).fetchone()["id"]

    db.set_setting("report_extract_batch", "1")
    out = medicolegal.queue_extractions()
    assert out["queued"] == [first_id]  # batch of one, oldest first
    assert out["remaining"] == 1        # the second report stays pending
    with db.tx() as conn:
        assert conn.execute("SELECT extract_status FROM reports WHERE id = ?",
                            (second_id,)).fetchone()["extract_status"] == "pending"
        # keep the second out of later tests
        conn.execute("UPDATE reports SET extract_status = 'skipped' WHERE id = ?",
                     (second_id,))

    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    extract_jobs = [j for j in jobs if j["kind"] == "report_extract"]
    job = next(j for j in extract_jobs if j["payload"]["report_id"] == first_id)
    text = job["payload"]["text"]
    # code-level pre-scrub caught the obvious identifiers
    assert "Smith v Acme" not in text
    assert "12/03/1971" not in text
    assert "XY-4451-B" not in text
    assert "mild traumatic brain injury" in text  # clinical content intact
    assert "de-identify" in job["prompt"].lower() or "De-identify" in job["prompt"]
    assert "placeholders" in job["prompt"]

    report_id = job["payload"]["report_id"]
    with db.tx() as conn:
        assert conn.execute("SELECT extract_status FROM reports WHERE id = ?",
                            (report_id,)).fetchone()["extract_status"] == "queued"

    r = client.post(f"/api/jobs/{job['id']}/result", headers=KEY, json={
        "snippets": [
            {"condition": "mild traumatic brain injury", "topic": "diagnosis",
             "question": "Is the diagnosis of mTBI correct?",
             "answer": "In my opinion the diagnosis is correct where the acute"
                       " features ([loss of consciousness duration], post-traumatic"
                       " amnesia of [duration]) satisfy the accepted criteria."},
            {"condition": "", "topic": "", "question": "", "answer": "dropped"},
        ],
    })
    assert r.status_code == 200
    assert r.json()["snippets_created"] == 1
    with db.tx() as conn:
        assert conn.execute("SELECT extract_status FROM reports WHERE id = ?",
                            (report_id,)).fetchone()["extract_status"] == "done"
        drafts = conn.execute("SELECT * FROM response_snippets WHERE status = 'draft'"
                              " AND source_report_id = ?", (report_id,)).fetchall()
        done_job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    assert len(drafts) == 1
    # the report text is scrubbed from the completed job's payload
    assert "mild traumatic brain injury" not in (done_job["payload"] or "")
    assert json.loads(done_job["payload"])["report_id"] == report_id


def test_curation_search_export_and_cpd(client):
    login(client)
    with db.tx() as conn:
        draft = conn.execute("SELECT * FROM response_snippets WHERE status = 'draft'"
                             " ORDER BY id LIMIT 1").fetchone()
    assert draft is not None

    # library page shows the draft
    page = client.get("/library").text
    assert "Drafts to curate" in page and "mTBI" in page

    # approve with an edit
    r = client.post(f"/library/{draft['id']}/review", data={
        "action": "approved",
        "condition": "Mild traumatic brain injury",
        "topic": "diagnosis",
        "question": draft["question"],
        "answer": draft["answer"] + " [edited]",
    }, follow_redirects=False)
    assert r.status_code == 303
    # a reviewed snippet cannot be re-reviewed
    assert medicolegal.review_snippet(draft["id"], "rejected") is False

    # search finds it; unrelated query doesn't
    assert len(medicolegal.search_snippets("traumatic")) == 1
    assert medicolegal.search_snippets("zebra syndrome") == []
    page = client.get("/library", params={"q": "amnesia"}).text
    assert "[edited]" in page

    # exports contain only approved snippets
    md = client.get("/library/export.md").text
    assert "Mild traumatic brain injury" in md and "[edited]" in md
    data = client.get("/library/export.json").json()
    assert len(data) == 1 and data[0]["topic"] == "diagnosis"

    # log the curation session -> confirmed Cat 2 with evidence
    r = client.post("/library/log-session", data={"minutes": "20"}, follow_redirects=False)
    assert r.status_code == 303
    with db.tx() as conn:
        activity = conn.execute(
            "SELECT * FROM activities WHERE source_module = 'library'"
            " ORDER BY id DESC LIMIT 1").fetchone()
        evidence = conn.execute("SELECT * FROM evidence WHERE activity_id = ?",
                                (activity["id"],)).fetchall()
    assert activity["category"] == 2 and activity["activity_type"] == "self_review"
    assert activity["status"] == "confirmed" and activity["minutes"] == 20
    doc = Path(evidence[0]["path_or_url"]).read_text()
    assert "[edited]" in doc and "approved: 1" in doc

    # nothing new reviewed since -> no second activity
    assert medicolegal.log_curation_session(10) is None


def test_missing_or_mismatched_file_marked_skipped(client):
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO reports (filename, sha256, detected_at) VALUES"
            " ('gone.docx', 'deadbeef' || RANDOM(), ?)", (db.now_iso(),))
        # same name as a real backfill file, but wrong content hash — must be
        # skipped, never mined from the other file's text
        conn.execute(
            "INSERT INTO reports (filename, sha256, detected_at) VALUES"
            " ('old-2024-report.txt', ?, ?)", ("0" * 64, db.now_iso()))
    out = medicolegal.queue_extractions(limit=10)
    with db.tx() as conn:
        gone = conn.execute("SELECT * FROM reports WHERE filename = 'gone.docx'").fetchone()
        mismatch = conn.execute("SELECT * FROM reports WHERE sha256 = ?",
                                ("0" * 64,)).fetchone()
    assert gone["extract_status"] == "skipped" and gone["id"] in out["skipped"]
    assert mismatch["extract_status"] == "skipped" and mismatch["id"] in out["skipped"]
