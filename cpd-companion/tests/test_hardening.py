"""Regression tests for the adversarial-review fixes: failed-job recovery,
flag propagation, evidence hashing, and harvest evidence references."""

from tests.test_app import KEY, client, login  # noqa: F401 - reuse env setup + fixture
from app import config, db, growth, medicolegal, news, reviews


def _claude_jobs(client, kind):
    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    return [j for j in jobs if j["kind"] == kind]


def test_failed_medicolegal_audit_job_is_requeued(client):
    login(client)
    config.ensure_dirs()
    (config.MEDICOLEGAL_INBOX / "hardening-report.txt").write_text(
        "Opinion: fine. Qualifications listed. Reasons for my opinion follow.")
    ids = medicolegal.scan_inbox()
    assert len(ids) == 1
    with db.tx() as conn:
        conn.execute("UPDATE reports SET detected_at = '2025-06-15T10:00:00+10:00'"
                     " WHERE id = ?", (ids[0],))

    out = medicolegal.ensure_monthly_audit("2025-06")
    assert out["status"] == "drafting"
    audit_id = out["audit_id"]
    job = _claude_jobs(client, "medicolegal_audit")[-1]
    r = client.post(f"/api/jobs/{job['id']}/fail", headers=KEY,
                    json={"error": "runner crashed"})
    assert r.status_code == 200

    # the audit is 'drafting' with no live job -> re-running queues a fresh one
    out2 = medicolegal.ensure_monthly_audit("2025-06")
    assert out2["status"] == "drafting" and out2["audit_id"] == audit_id
    pending = _claude_jobs(client, "medicolegal_audit")
    assert len(pending) == 1 and pending[0]["id"] != job["id"]

    r = client.post(f"/api/jobs/{pending[0]['id']}/result", headers=KEY,
                    json={"audit_md": "recovered draft"})
    assert r.status_code == 200
    with db.tx() as conn:
        audit = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
        # keep this report out of the later library-extraction tests
        conn.execute("UPDATE reports SET extract_status = 'skipped' WHERE id = ?",
                     (ids[0],))
    assert audit["status"] == "review" and audit["draft_text"] == "recovered draft"


def test_failed_review_themes_job_is_requeued(client):
    login(client)
    with db.tx() as conn:
        reviews._store_reviews(conn, [
            {"author": "H", "rating": 4, "text": "Prompt and thorough.",
             "date": "2026-08-01"}])
    out = reviews.maybe_open_cycle(force=True)
    assert out["status"] == "opened"
    cycle_id = out["cycle_id"]
    job = _claude_jobs(client, "review_themes")[-1]
    client.post(f"/api/jobs/{job['id']}/fail", headers=KEY, json={"error": "boom"})

    # the scheduler's next (non-forced) run re-queues instead of wedging
    out2 = reviews.maybe_open_cycle()
    assert out2 == {"status": "requeued", "cycle_id": cycle_id}
    fresh = _claude_jobs(client, "review_themes")
    assert len(fresh) == 1 and fresh[0]["payload"]["cycle_id"] == cycle_id
    assert len(fresh[0]["payload"]["reviews"]) == 1

    r = client.post(f"/api/jobs/{fresh[0]['id']}/result", headers=KEY,
                    json={"themes_md": "recovered themes", "actions": []})
    assert r.status_code == 200
    # the drafting state also renders a manual sign-off path now
    assert reviews.sign_off_cycle(cycle_id, "recovered themes", "", 10) is not None


def test_failed_report_extract_resets_report(client):
    login(client)
    config.ensure_dirs()
    (config.MEDICOLEGAL_INBOX / "hardening-extract.txt").write_text(
        "Question: prognosis? Answer: good. Opinion follows.")
    ids = medicolegal.scan_inbox()
    out = medicolegal.queue_extractions(limit=50)
    assert ids[0] in out["queued"]
    job = next(j for j in _claude_jobs(client, "report_extract")
               if j["payload"].get("report_id") == ids[0])
    client.post(f"/api/jobs/{job['id']}/fail", headers=KEY, json={"error": "no dice"})
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (ids[0],)).fetchone()
        failed = conn.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    assert row["extract_status"] == "pending"  # eligible for the next batch
    assert "Answer: good" not in (failed["payload"] or "")  # text scrubbed on failure
    # clean up this test's own artefacts so later scan/audit tests are unaffected
    with db.tx() as conn:
        conn.execute("DELETE FROM reports WHERE id = ?", (ids[0],))
    (config.MEDICOLEGAL_INBOX / "hardening-extract.txt").unlink()


def test_failed_info_sheet_dismisses_output_and_allows_retry(client):
    login(client)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO news_items (source, guid, link, title, summary, fetched_at)"
            " VALUES ('T', 'g-hard-info', '', 'Hardening info item', '', ?)",
            (db.now_iso(),))
        item_id = conn.execute("SELECT id FROM news_items WHERE guid = 'g-hard-info'"
                               ).fetchone()["id"]
    first = growth.request_info_sheet(item_id)
    job = next(j for j in _claude_jobs(client, "info_sheet")
               if j["payload"].get("output_id") == first)
    client.post(f"/api/jobs/{job['id']}/fail", headers=KEY, json={"error": "skill missing"})
    with db.tx() as conn:
        output = conn.execute("SELECT * FROM practice_outputs WHERE id = ?",
                              (first,)).fetchone()
    assert output["status"] == "dismissed"
    assert "drafting job failed" in output["notes"]

    retry = growth.request_info_sheet(item_id)
    assert retry is not None and retry != first
    retry_jobs = [j for j in _claude_jobs(client, "info_sheet")
                  if j["payload"].get("output_id") == retry]
    assert len(retry_jobs) == 1


def test_digest_flags_flow_into_reading_draft_tags_and_home_suggestions(client):
    login(client)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO news_items (source, guid, link, title, summary, fetched_at,"
            " llm_digest, digest_flags) VALUES ('T', 'g-hard-flag', '',"
            " 'Consent in acute stroke thrombolysis', '', ?, 'Ethics piece.', 'ethics')",
            (db.now_iso(),))
        item_id = conn.execute("SELECT id FROM news_items WHERE guid = 'g-hard-flag'"
                               ).fetchone()["id"]
    # home page suggests the flagged item while the ethics counter is behind
    page = client.get("/").text
    assert "Consent in acute stroke thrombolysis" in page

    assert news.mark_read(item_id, 300)
    created = news.rollup_reading()
    assert len(created) == 1
    with db.tx() as conn:
        draft = conn.execute("SELECT * FROM activities WHERE id = ?",
                             (created[0],)).fetchone()
        evidence = conn.execute("SELECT * FROM evidence WHERE activity_id = ?",
                                (created[0],)).fetchone()
    assert "ethics" in draft["tags"]
    assert evidence["sha256"]  # generated evidence is hash-stamped now
    # the inbox shows the inherited tags before confirming
    page = client.get("/inbox").text
    assert "ethics" in page
