"""M2 reviews tests: polling/ingest dedupe, review cycles, themes job,
improvement backlog, and Cat 2 sign-off."""

import json
from pathlib import Path

from tests.test_app import KEY, client, login  # noqa: F401 - reuse env setup + fixture
from app import config, db, reviews


def test_inbox_ingest_and_dedupe(client):
    config.ensure_dirs()
    export = [
        {"author": "A Patient", "rating": 5, "text": "Wonderful, thorough neurologist.",
         "date": "2026-07-01"},
        {"author": "B Patient", "rating": 3,
         "text": "Great doctor but the phone line is impossible to get through.",
         "date": "2026-07-15"},
        {"author": "", "rating": None, "text": "", "date": ""},  # empty -> skipped
    ]
    (config.REVIEWS_INBOX / "export.json").write_text(json.dumps(export))
    (config.REVIEWS_INBOX / "broken.json").write_text("{not json")

    assert reviews.ingest_inbox() == 2
    assert reviews.ingest_inbox() == 0  # hash dedupe on re-scan

    out = reviews.poll_reviews()  # no Places key configured -> inbox only
    assert out["places"] == "not configured"
    assert "inbox only" in db.get_setting("reviews_last_status")


def test_places_poll(client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_PLACES_API_KEY", "k")
    monkeypatch.setattr(config, "GOOGLE_PLACE_ID", "p")
    monkeypatch.setattr(reviews, "_fetch_place_reviews", lambda: [
        {"author": "C Patient", "rating": 5, "text": "Explained everything clearly.",
         "date": "2026-08-01"},
        {"author": "A Patient", "rating": 5, "text": "Wonderful, thorough neurologist.",
         "date": "2026-07-01"},  # duplicate of the inbox one
    ])
    out = reviews.poll_reviews()
    assert out["places_new"] == 1
    assert db.get_setting("reviews_last_status").startswith("ok:")

    def boom():
        raise RuntimeError("quota exceeded")
    monkeypatch.setattr(reviews, "_fetch_place_reviews", boom)
    out = reviews.poll_reviews()
    assert "error" in out
    assert db.get_setting("reviews_last_status").startswith("error: quota")


def test_cycle_flow_and_backlog(client):
    login(client)
    out = reviews.maybe_open_cycle(force=True)
    assert out["status"] == "opened"
    cycle_id = out["cycle_id"]
    assert out["review_count"] == 3

    # a second open while one is in progress is refused
    assert reviews.maybe_open_cycle(force=True)["status"] == "cycle_in_progress"

    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    job = next(j for j in jobs if j["kind"] == "review_themes")
    assert len(job["payload"]["reviews"]) == 3
    assert "never invent" in job["prompt"]

    r = client.post(f"/api/jobs/{job['id']}/result", headers=KEY, json={
        "themes_md": "## Praise\n- thoroughness\n## Complaints\n- phone access",
        "actions": ["Add a call-back option to the phone system", "  ", 42],
    })
    assert r.status_code == 200
    assert r.json()["improvement_actions"] == 2  # blank dropped, 42 coerced to str

    with db.tx() as conn:
        cycle = conn.execute("SELECT * FROM review_cycles WHERE id = ?", (cycle_id,)).fetchone()
        backlog = conn.execute(
            "SELECT * FROM practice_outputs WHERE kind = 'improvement_action'"
            " AND source_id = ?", (cycle_id,)).fetchall()
    assert cycle["status"] == "review"
    assert "phone access" in cycle["themes_draft"]
    assert any("call-back" in b["title"] for b in backlog)

    # reviews page shows the cycle and backlog
    page = client.get("/reviews").text
    assert "phone access" in page and "call-back" in page

    # close a backlog item, then sign off
    action_id = backlog[0]["id"]
    r = client.post(f"/outputs/{action_id}/status", data={"status": "done"},
                    follow_redirects=False)
    assert r.status_code == 303

    r = client.post(f"/reviews/{cycle_id}/signoff", data={
        "final_text": "## Themes\nPhone access needs work.",
        "reflection": "We added a call-back option.",
        "minutes": "30",
    }, follow_redirects=False)
    assert r.status_code == 303

    with db.tx() as conn:
        cycle = conn.execute("SELECT * FROM review_cycles WHERE id = ?", (cycle_id,)).fetchone()
        activity = conn.execute("SELECT * FROM activities WHERE id = ?",
                                (cycle["activity_id"],)).fetchone()
        evidence = conn.execute("SELECT * FROM evidence WHERE activity_id = ?",
                                (activity["id"],)).fetchall()
    assert cycle["status"] == "signed_off"
    assert activity["category"] == 2
    assert activity["activity_type"] == "patient_feedback"
    assert activity["status"] == "confirmed" and activity["minutes"] == 30
    doc = Path(evidence[0]["path_or_url"]).read_text()
    assert "Phone access needs work" in doc
    assert "call-back" in doc.lower()  # completed actions listed in the evidence

    # signed-off cycle cannot be signed off again
    assert reviews.sign_off_cycle(cycle_id, "again", "", 5) is None


def test_cycle_cadence(client):
    # last cycle just signed off -> a scheduled (non-forced) open is not due yet
    out = reviews.maybe_open_cycle()
    assert out["status"] in ("not_due", "no_new_reviews")


def test_stale_themes_after_signoff(client, monkeypatch):
    # new review, new cycle, sign off before the draft arrives, then post it
    with db.tx() as conn:
        reviews._store_reviews(conn, [
            {"author": "D", "rating": 4, "text": "Efficient visit.", "date": "2026-08-10"}])
    out = reviews.maybe_open_cycle(force=True)
    cycle_id = out["cycle_id"]
    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    job = next(j for j in jobs if j["kind"] == "review_themes"
               and j["payload"]["cycle_id"] == cycle_id)
    assert reviews.sign_off_cycle(cycle_id, "manual themes", "", 10) is not None
    r = client.post(f"/api/jobs/{job['id']}/result", headers=KEY,
                    json={"themes_md": "late draft", "actions": []})
    assert r.status_code == 200 and r.json().get("skipped")
    with db.tx() as conn:
        cycle = conn.execute("SELECT * FROM review_cycles WHERE id = ?", (cycle_id,)).fetchone()
    assert cycle["final_text"] == "manual themes"
