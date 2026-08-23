"""§5 practice growth loop tests: info sheets, opportunity scan, referrer
newsletter, and refresh flagging."""

import json
from pathlib import Path

from tests.test_app import KEY, client, login  # noqa: F401 - reuse env setup + fixture
from app import db, growth


def _add_item(guid: str, title: str, *, summary="", digest=None, section="General",
              opportunity=0, newsletter=0) -> int:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO news_items (source, guid, link, title, summary, fetched_at,"
            " section, llm_digest, flagged_opportunity, flagged_newsletter)"
            " VALUES ('Test source', ?, 'https://example.com/x', ?, ?, ?, ?, ?, ?, ?)",
            (guid, title, summary, db.now_iso(), section, digest, opportunity, newsletter),
        )
        return conn.execute("SELECT id FROM news_items WHERE guid = ?", (guid,)
                            ).fetchone()["id"]


def test_info_sheet_job_flow(client):
    login(client)
    item_id = _add_item("g-info-1", "Erenumab now PBS-listed for chronic migraine",
                        summary="CGRP monoclonal antibody listed for chronic migraine.")

    r = client.post(f"/digest/{item_id}/action/info_sheet", follow_redirects=False)
    assert r.status_code == 303
    # idempotent: second click adds nothing
    client.post(f"/digest/{item_id}/action/info_sheet", follow_redirects=False)

    with db.tx() as conn:
        outputs = conn.execute(
            "SELECT * FROM practice_outputs WHERE kind = 'info_sheet' AND source_id = ?",
            (item_id,)).fetchall()
    assert len(outputs) == 1 and outputs[0]["status"] == "idea"
    output_id = outputs[0]["id"]

    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    sheet_jobs = [j for j in jobs if j["kind"] == "info_sheet"
                  and j["payload"].get("output_id") == output_id]
    assert len(sheet_jobs) == 1
    job = sheet_jobs[0]
    assert "east-neuro-patient-page" in job["prompt"]
    assert "[review]" in job["prompt"]
    assert job["payload"]["item"]["title"].startswith("Erenumab")

    r = client.post(f"/api/jobs/{job['id']}/result", headers=KEY, json={
        "title": "Erenumab (Aimovig) for chronic migraine",
        "target_site": "sydneyheadachecentre.com.au",
        "html": "<h1>Erenumab</h1><p>Now on the PBS.</p>",
    })
    assert r.status_code == 200

    with db.tx() as conn:
        output = conn.execute("SELECT * FROM practice_outputs WHERE id = ?",
                              (output_id,)).fetchone()
    assert output["status"] == "draft"
    assert output["target_site"] == "sydneyheadachecentre.com.au"
    assert "<h1>Erenumab</h1>" in Path(output["path"]).read_text()

    # draft is downloadable and shows on the outputs page
    r = client.get(f"/outputs/{output_id}/download")
    assert r.status_code == 200 and b"Erenumab" in r.content
    page = client.get("/outputs").text
    assert "Erenumab (Aimovig)" in page

    # publish, then a late duplicate job result cannot regress it
    client.post(f"/outputs/{output_id}/status", data={"status": "published"},
                follow_redirects=False)
    dup = growth.request_info_sheet(item_id)
    assert dup == output_id  # published output still blocks duplicates
    with db.tx() as conn:
        n_jobs = conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE kind = 'info_sheet'"
                              ).fetchone()["n"]
    assert n_jobs == 1


def test_opportunity_scan_flow(client):
    login(client)
    _add_item("g-opp-1", "New PBS listing for ocrelizumab", section="Drugs & regulatory AU")
    _add_item("g-opp-2", "Tilt-table testing validated for POTS diagnosis",
              opportunity=1)

    job_id = growth.quarterly_opportunity_scan()
    assert job_id is not None
    assert growth.quarterly_opportunity_scan() is None  # one pending at a time

    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    job = next(j for j in jobs if j["id"] == job_id)
    payload_items = job["payload"]["items"]
    assert any(i["flagged_by_doctor"] for i in payload_items)
    assert "go/no-go" in job["prompt"]

    r = client.post(f"/api/jobs/{job_id}/result", headers=KEY, json={
        "briefs": [
            {"title": "Expand POTS testing capacity",
             "brief_md": "## The development\nTilt-table validation...",
             "target_site": "potstestingsydney.com.au"},
            {"title": "", "brief_md": "no title, dropped"},
            {"title": "Bad site", "brief_md": "content", "target_site": "evil.example"},
        ],
    })
    assert r.status_code == 200
    created = r.json()["created_outputs"]
    assert len(created) == 2  # empty-title brief dropped

    with db.tx() as conn:
        briefs = conn.execute(
            "SELECT * FROM practice_outputs WHERE kind = 'opportunity_brief' ORDER BY id"
        ).fetchall()
    assert briefs[0]["status"] == "draft"
    assert briefs[0]["target_site"] == "potstestingsydney.com.au"
    assert briefs[1]["target_site"] == ""  # unknown site rejected
    assert "Tilt-table validation" in Path(briefs[0]["path"]).read_text()


def test_newsletter_consumes_flags(client):
    login(client)
    a = _add_item("g-nl-1", "Lecanemab AU approval", newsletter=1,
                  digest="TGA approved lecanemab with MRI monitoring requirements.")
    b = _add_item("g-nl-2", "New epilepsy driving guidance", newsletter=1)

    job_id = growth.quarterly_referrer_newsletter()
    assert job_id is not None
    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    job = next(j for j in jobs if j["id"] == job_id)
    assert set(job["payload"]["item_ids"]) == {a, b}

    r = client.post(f"/api/jobs/{job_id}/result", headers=KEY,
                    json={"newsletter_md": "# What's new in neurology\n- lecanemab..."})
    assert r.status_code == 200
    output_id = r.json()["output_id"]

    with db.tx() as conn:
        output = conn.execute("SELECT * FROM practice_outputs WHERE id = ?",
                              (output_id,)).fetchone()
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM news_items WHERE flagged_newsletter = 1"
        ).fetchone()["n"]
    assert output["kind"] == "newsletter" and output["status"] == "draft"
    assert "lecanemab" in Path(output["path"]).read_text()
    assert remaining == 0  # flags consumed

    # nothing flagged -> no new job
    assert growth.quarterly_referrer_newsletter() is None


def test_refresh_flagging(client):
    login(client)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO practice_outputs (kind, title, status, created_at)"
            " VALUES ('info_sheet', 'Erenumab migraine prevention explained',"
            " 'published', ?)", (db.now_iso(),))
        output_id = conn.execute("SELECT MAX(id) AS m FROM practice_outputs"
                                 ).fetchone()["m"]
    _add_item("g-refresh-1",
              "Updated guidance on erenumab migraine prevention dosing")

    flagged = growth.flag_refreshes()
    assert output_id in flagged
    with db.tx() as conn:
        output = conn.execute("SELECT * FROM practice_outputs WHERE id = ?",
                              (output_id,)).fetchone()
    assert output["needs_refresh"] == 1
    assert "refresh suggested" in output["notes"]

    # already-flagged outputs are not re-flagged
    assert growth.flag_refreshes() == []

    # outputs page surfaces it; clearing works
    page = client.get("/outputs").text
    assert "refresh?" in page
    r = client.post(f"/outputs/{output_id}/refresh-clear", follow_redirects=False)
    assert r.status_code == 303
    with db.tx() as conn:
        assert conn.execute("SELECT needs_refresh FROM practice_outputs WHERE id = ?",
                            (output_id,)).fetchone()["needs_refresh"] == 0
