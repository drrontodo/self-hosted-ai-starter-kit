"""M6 PDP builder + evidence upload/download tests."""

from pathlib import Path

from tests.test_app import KEY, client, login  # noqa: F401 - reuse env setup + fixture
from app import config, db, pdp

YEAR = 2027  # keep clear of years other tests assert progress on


def test_pdp_form_draft_and_complete(client):
    login(client)
    page = client.get("/pdp", params={"year": YEAR}).text
    assert "Development goals" in page

    r = client.post(f"/pdp/{YEAR}/save", data={
        "goals": "Improve headache service\nPublish autonomic testing audit",
        "planned_cat1": "Weekly digest reading",
        "planned_cat2": "Quarterly feedback cycles",
        "planned_cat3": "Monthly medicolegal audit",
        "timeframes": "Ongoing through the year",
        "success_measures": "50h logged; audits signed off",
        "queue_draft": "1",
    }, follow_redirects=False)
    assert r.status_code == 303

    row = pdp.get_or_create(YEAR)
    assert row["status"] == "drafting"
    assert "headache service" in row["goals"]

    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    job = next(j for j in jobs if j["kind"] == "pdp_draft")
    assert job["payload"]["year"] == YEAR
    assert job["payload"]["stated"]["goals"].startswith("Improve headache")
    assert "progress_this_year" in job["payload"]
    assert "never invent" in job["prompt"]

    # only one pending pdp_draft at a time
    assert pdp.queue_draft(YEAR) is None

    r = client.post(f"/api/jobs/{job['id']}/result", headers=KEY,
                    json={"pdp_md": "## Goals\n1. Headache service\n2. Autonomic audit"})
    assert r.status_code == 200
    row = pdp.get_or_create(YEAR)
    assert row["status"] == "editing"
    assert "Autonomic audit" in row["draft_md"]

    r = client.post(f"/pdp/{YEAR}/complete", data={
        "final_md": "## Goals (final)\n1. Headache service", "minutes": "40",
    }, follow_redirects=False)
    assert r.status_code == 303

    row = pdp.get_or_create(YEAR)
    assert row["status"] == "completed"
    with db.tx() as conn:
        activity = conn.execute("SELECT * FROM activities WHERE id = ?",
                                (row["activity_id"],)).fetchone()
        evidence = conn.execute("SELECT * FROM evidence WHERE activity_id = ?",
                                (activity["id"],)).fetchall()
    assert activity["category"] == 2 and activity["activity_type"] == "pdp"
    assert activity["status"] == "confirmed" and activity["minutes"] == 40
    assert "Headache service" in Path(evidence[0]["path_or_url"]).read_text()
    assert db.get_setting(f"pdp_done_{YEAR}") == "1"  # mandatory tracker ticked

    # completed PDPs are frozen
    assert pdp.complete(YEAR, "again", 5) is None
    assert pdp.queue_draft(YEAR) is None
    pdp.save_form(YEAR, {"goals": "overwrite"})
    assert pdp.get_or_create(YEAR)["goals"] != "overwrite"


def test_stale_pdp_draft_after_completion(client):
    year = YEAR + 1
    login(client)
    pdp.get_or_create(year)
    pdp.save_form(year, {"goals": "g"})
    job_id = pdp.queue_draft(year)
    assert job_id is not None
    assert pdp.complete(year, "done early", 10) is not None
    r = client.post(f"/api/jobs/{job_id}/result", headers=KEY, json={"pdp_md": "late"})
    assert r.status_code == 200 and r.json().get("skipped")
    assert pdp.get_or_create(year)["draft_md"] == "done early"


def test_evidence_upload_and_download(client):
    login(client)
    r = client.post("/api/activities", headers=KEY, json={
        "date": "2026-05-20", "category": 1, "activity_type": "meeting",
        "title": "ANZAN webinar with certificate", "minutes": 60,
    })
    aid = r.json()["id"]

    r = client.post(f"/activity/{aid}/evidence",
                    files={"upload": ("certificate.pdf", b"%PDF-1.4 fake", "application/pdf")},
                    follow_redirects=False)
    assert r.status_code == 303
    # same name twice -> second file gets a distinct name
    r = client.post(f"/activity/{aid}/evidence",
                    files={"upload": ("certificate.pdf", b"%PDF-1.4 other", "application/pdf")},
                    follow_redirects=False)
    assert r.status_code == 303

    with db.tx() as conn:
        rows = conn.execute("SELECT * FROM evidence WHERE activity_id = ? ORDER BY id",
                            (aid,)).fetchall()
    assert len(rows) == 2
    assert rows[0]["sha256"] and rows[0]["kind"] == "file"
    assert rows[0]["path_or_url"] != rows[1]["path_or_url"]

    r = client.get(f"/evidence/{rows[0]['id']}")
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 fake"

    # the edit page lists the evidence
    page = client.get(f"/activity/{aid}").text
    assert "certificate.pdf" in page

    # missing evidence id -> redirect, not a traceback
    assert client.get("/evidence/999999", follow_redirects=False).status_code == 303


def test_evidence_download_refuses_paths_outside_data_dir(client):
    login(client)
    r = client.post("/api/activities", headers=KEY, json={
        "date": "2026-05-21", "category": 1, "activity_type": "meeting",
        "title": "path traversal test", "minutes": 10,
    })
    aid = r.json()["id"]
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO evidence (activity_id, kind, path_or_url, created_at)"
            " VALUES (?, 'file', '/etc/passwd', ?)", (aid, db.now_iso()))
        eid = conn.execute("SELECT id FROM evidence WHERE activity_id = ?"
                           " ORDER BY id DESC", (aid,)).fetchone()["id"]
    r = client.get(f"/evidence/{eid}")
    assert r.status_code == 404
