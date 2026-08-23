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

from app import db
from app.main import app

KEY = {"X-API-Key": "test-key"}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def login(c):
    r = c.post("/login", data={"password": "test-pass"}, follow_redirects=False)
    assert r.status_code == 303


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_dashboard_requires_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_wrong_password(client):
    r = client.post("/login", data={"password": "nope"})
    assert r.status_code == 401


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
    assert "headache-tool" in draft["title"]

    # drafts don't count toward progress
    year = draft["date"][:4]
    prog = client.get("/api/progress", headers=KEY, params={"year": year}).json()
    assert prog["cat1_min"] == 0

    # confirm via dashboard with trimmed minutes
    login(client)
    r = client.post(f"/inbox/{ids[0]}/confirm", data={"minutes": 60, "reflection": "Useful"},
                    follow_redirects=False)
    assert r.status_code == 303
    prog = client.get("/api/progress", headers=KEY, params={"year": year}).json()
    assert prog["cat1_min"] == 60

    # a second rollup with no new sessions creates nothing
    assert client.post("/api/rollup", headers=KEY).json()["created_draft_activity_ids"] == []


def test_manual_activity_and_csv_export(client):
    r = client.post("/api/activities", headers=KEY, json={
        "date": "2026-03-05",
        "category": 3,
        "activity_type": "audit",
        "title": "Medicolegal report audit — Feb 2026",
        "minutes": 90,
        "status": "confirmed",
        "tags": ["ethics"],
    })
    assert r.status_code == 201

    prog = client.get("/api/progress", headers=KEY, params={"year": 2026}).json()
    assert prog["cat3_min"] >= 90

    login(client)
    r = client.get("/export/mycpd.csv", params={"year": 2026})
    assert r.status_code == 200
    assert "Medicolegal report audit — Feb 2026" in r.text
    assert "1.50" in r.text


def test_activity_patch_and_delete(client):
    r = client.post("/api/activities", headers=KEY, json={
        "date": "2026-04-01", "category": 2, "activity_type": "peer_discussion",
        "title": "Case discussion", "minutes": 20,
    })
    aid = r.json()["id"]
    r = client.patch(f"/api/activities/{aid}", headers=KEY, json={"status": "confirmed", "minutes": 30})
    assert r.status_code == 200
    row = [a for a in client.get("/api/activities", headers=KEY).json() if a["id"] == aid][0]
    assert row["status"] == "confirmed" and row["minutes"] == 30 and row["confirmed_at"]
    assert client.delete(f"/api/activities/{aid}", headers=KEY).json()["deleted"] is True
    assert client.delete(f"/api/activities/{aid}", headers=KEY).status_code == 404


def test_invalid_activity_type_rejected(client):
    r = client.post("/api/activities", headers=KEY, json={
        "date": "2026-04-01", "category": 1, "activity_type": "not_a_type",
        "title": "x", "minutes": 10,
    })
    assert r.status_code == 422


def test_backup(client):
    from app import scheduler
    path = scheduler.backup()
    assert os.path.exists(path)
