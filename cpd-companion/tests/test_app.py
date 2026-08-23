import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="cpd-test-")
os.environ.update({
    "CPD_DATA_DIR": _tmp,
    "CPD_API_KEY": "test-key",
    "CPD_DASHBOARD_PASSWORD": "test-pass",
    "CPD_SECRET_KEY": "test-secret",
    "CPD_SCHEDULER": "0",
})

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.main import app

KEY = {"X-API-Key": "test-key"}


@pytest.fixture()
def client():
    auth._failures.clear()
    with TestClient(app) as c:
        yield c


def login(c):
    r = c.post("/login", data={"password": "test-pass"}, follow_redirects=False)
    assert r.status_code == 303


def confirm_via_dashboard(c, activity_id, minutes, reflection=""):
    r = c.post(f"/inbox/{activity_id}/confirm", data={"minutes": minutes, "reflection": reflection},
               follow_redirects=False)
    assert r.status_code == 303
    return r


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_openapi_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_dashboard_requires_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_wrong_password_and_throttle(client):
    for _ in range(auth.FAILURE_LIMIT):
        assert client.post("/login", data={"password": "nope"}).status_code == 401
    assert client.post("/login", data={"password": "nope"}).status_code == 429
    auth._failures.clear()


def test_non_ascii_password_is_401_not_500(client):
    assert client.post("/login", data={"password": "pässwörd"}).status_code == 401


def test_api_requires_key(client):
    assert client.get("/api/activities").status_code in (401, 403, 422)
    assert client.get("/api/activities", headers={"X-API-Key": "wrong"}).status_code == 401


def test_session_rollup_confirm_flow(client):
    for minutes, summary in [(40, "Researched CGRP antagonists"), (25, "Built triage tool")]:
        r = client.post("/api/sessions", headers=KEY, json={
            "project": "headache-tool",
            "active_minutes": minutes,
            "topics": ["migraine", "CGRP"],
            "summary": summary,
        })
        assert r.status_code == 201

    r = client.post("/api/rollup", headers=KEY)
    ids = r.json()["created_draft_activity_ids"]
    assert len(ids) == 1

    drafts = client.get("/api/activities", headers=KEY, params={"status": "draft"}).json()
    draft = next(a for a in drafts if a["id"] == ids[0])
    assert draft["minutes"] == 65
    assert draft["category"] == 1

    year = draft["date"][:4]
    prog = client.get("/api/progress", headers=KEY, params={"year": year}).json()
    assert prog["cat1_min"] == 0  # drafts don't count

    login(client)
    confirm_via_dashboard(client, ids[0], 60, "Useful")
    prog = client.get("/api/progress", headers=KEY, params={"year": year}).json()
    assert prog["cat1_min"] == 60

    assert client.post("/api/rollup", headers=KEY).json()["created_draft_activity_ids"] == []


def test_rollup_respects_year_boundary(client):
    for started in ["2025-12-30T10:00:00+11:00", "2026-01-02T10:00:00+11:00"]:
        client.post("/api/sessions", headers=KEY, json={
            "project": "yearend", "active_minutes": 30, "started_at": started,
            "summary": "boundary work",
        })
    ids = client.post("/api/rollup", headers=KEY).json()["created_draft_activity_ids"]
    assert len(ids) == 2
    drafts = client.get("/api/activities", headers=KEY, params={"status": "draft"}).json()
    dates = sorted(a["date"] for a in drafts if a["id"] in ids)
    assert dates == ["2025-12-30", "2026-01-02"]


def test_rollup_converts_utc_to_local_date(client):
    # 14:00 UTC on 31 Dec = 01:00 on 1 Jan in Sydney
    client.post("/api/sessions", headers=KEY, json={
        "project": "utcproj", "active_minutes": 15,
        "started_at": "2025-12-31T14:00:00Z", "summary": "late night reading",
    })
    ids = client.post("/api/rollup", headers=KEY).json()["created_draft_activity_ids"]
    drafts = client.get("/api/activities", headers=KEY, params={"status": "draft"}).json()
    draft = next(a for a in drafts if a["id"] in ids)
    assert draft["date"] == "2026-01-01"


def test_api_cannot_confirm(client):
    r = client.post("/api/activities", headers=KEY, json={
        "date": "2026-03-05", "category": 3, "activity_type": "audit",
        "title": "Medicolegal report audit — Feb 2026", "minutes": 90,
    })
    assert r.status_code == 201
    aid = r.json()["id"]
    assert r.json()["status"] == "draft"

    # confirming over the API is rejected
    assert client.patch(f"/api/activities/{aid}", headers=KEY,
                        json={"status": "confirmed"}).status_code == 422

    login(client)
    confirm_via_dashboard(client, aid, 90)
    prog = client.get("/api/progress", headers=KEY, params={"year": 2026}).json()
    assert prog["cat3_min"] >= 90


def test_csv_export_and_formula_escaping(client):
    login(client)
    r = client.post("/log/add", data={
        "date": "2026-03-06", "category": "1", "activity_type": "reading",
        "title": "=HYPERLINK(\"http://evil\")", "minutes": "10",
        "description": "", "reflection": "",
    }, follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/export/mycpd.csv", params={"year": 2026})
    assert r.status_code == 200
    assert "'=HYPERLINK" in r.text  # formula neutralised
    assert "\n2026-03-06,1," in r.text


def test_invalid_dates_rejected(client):
    r = client.post("/api/activities", headers=KEY, json={
        "date": "2026-13-99", "category": 1, "activity_type": "reading",
        "title": "bad date", "minutes": 10,
    })
    assert r.status_code == 422
    login(client)
    r = client.post("/log/add", data={
        "date": "banana", "category": "1", "activity_type": "reading",
        "title": "x", "minutes": "10", "description": "", "reflection": "",
    }, follow_redirects=False)
    assert r.status_code == 422


def test_out_of_range_forms_are_422_not_500(client):
    login(client)
    for bad in [{"category": "9"}, {"minutes": "-5"}, {"minutes": "999999"}]:
        data = {"date": "2026-05-05", "category": "1", "activity_type": "reading",
                "title": "x", "minutes": "10", "description": "", "reflection": ""}
        data.update(bad)
        assert client.post("/log/add", data=data, follow_redirects=False).status_code == 422


def test_stale_confirm_redirects_with_notice(client):
    r = client.post("/api/activities", headers=KEY, json={
        "date": "2026-06-01", "category": 2, "activity_type": "peer_discussion",
        "title": "stale test", "minutes": 15,
    })
    aid = r.json()["id"]
    login(client)
    r = client.post(f"/inbox/{aid}/discard", follow_redirects=False)
    assert r.headers["location"] == "/inbox"
    r = client.post(f"/inbox/{aid}/confirm", data={"minutes": 15, "reflection": ""},
                    follow_redirects=False)
    assert r.headers["location"] == f"/inbox?stale={aid}"
    # the entry stayed discarded
    rows = client.get("/api/activities", headers=KEY).json()
    assert not any(a["id"] == aid for a in rows)  # discarded entries are hidden


def test_external_ref_dedupe(client):
    body = {"date": "2026-07-01", "category": 1, "activity_type": "meeting",
            "title": "ANZAN webinar", "minutes": 60, "external_ref": "gmail-msg-123"}
    assert client.post("/api/activities", headers=KEY, json=body).status_code == 201
    assert client.post("/api/activities", headers=KEY, json=body).status_code == 409


def test_activity_patch_and_soft_delete(client):
    r = client.post("/api/activities", headers=KEY, json={
        "date": "2026-04-01", "category": 2, "activity_type": "peer_discussion",
        "title": "Case discussion", "minutes": 20,
    })
    aid = r.json()["id"]
    r = client.patch(f"/api/activities/{aid}", headers=KEY, json={"minutes": 30})
    assert r.status_code == 200
    assert client.patch(f"/api/activities/{aid}", headers=KEY,
                        json={"activity_type": "not_a_type"}).status_code == 422
    r = client.delete(f"/api/activities/{aid}", headers=KEY)
    assert r.json()["discarded"] is True
    assert client.delete("/api/activities/999999", headers=KEY).status_code == 404


def test_invalid_activity_type_rejected(client):
    r = client.post("/api/activities", headers=KEY, json={
        "date": "2026-04-01", "category": 1, "activity_type": "not_a_type",
        "title": "x", "minutes": 10,
    })
    assert r.status_code == 422


def test_cross_origin_post_rejected(client):
    login(client)
    r = client.post("/log/add", data={
        "date": "2026-05-05", "category": "1", "activity_type": "reading",
        "title": "csrf", "minutes": "10", "description": "", "reflection": "",
    }, headers={"Origin": "http://evil.example"}, follow_redirects=False)
    assert r.status_code == 403


def test_mandatory_toggle_and_home(client):
    login(client)
    r = client.post("/mandatory/pdp/toggle", data={"year": "2026"}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/", params={"year": 2026}).text
    assert "Professional Development Plan" in page
    assert "✅ done" in page


def test_backup(client):
    from app import scheduler
    path = scheduler.backup()
    assert os.path.exists(path)
