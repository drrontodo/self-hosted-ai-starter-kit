"""Phase 6 tests: audit-bundle export and cookie hardening."""

import io
import zipfile

from tests.test_app import KEY, client, login  # noqa: F401 - reuse env setup + fixture
from app import config, db

YEAR = 2031  # isolated from years other tests populate


def test_audit_bundle_zip(client):
    login(client)
    r = client.post("/log/add", data={
        "date": f"{YEAR}-03-01", "category": "3", "activity_type": "audit",
        "title": "=EMG audit", "minutes": "90",
        "description": "Turnaround audit", "reflection": "Improved",
    }, follow_redirects=False)
    assert r.status_code == 303
    with db.tx() as conn:
        aid = conn.execute("SELECT id FROM activities WHERE title = '=EMG audit'"
                           ).fetchone()["id"]
    r = client.post(f"/activity/{aid}/evidence",
                    files={"upload": ("audit-doc.md", b"# audit evidence", "text/markdown")},
                    follow_redirects=False)
    assert r.status_code == 303

    # a second confirmed entry whose evidence file has vanished from disk
    client.post("/log/add", data={
        "date": f"{YEAR}-04-01", "category": "1", "activity_type": "reading",
        "title": "Journal reading", "minutes": "30", "description": "", "reflection": "",
    }, follow_redirects=False)
    with db.tx() as conn:
        aid2 = conn.execute("SELECT id FROM activities WHERE title = 'Journal reading'"
                            ).fetchone()["id"]
        conn.execute(
            "INSERT INTO evidence (activity_id, kind, path_or_url, created_at)"
            " VALUES (?, 'file', ?, ?)",
            (aid2, str(config.EVIDENCE_DIR / "vanished.pdf"), db.now_iso()))

    r = client.get(f"/export/audit-bundle/{YEAR}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert f"register-{YEAR}.csv" in names
    assert f"register-{YEAR}.md" in names
    assert any(n.startswith(f"evidence/activity-{aid}/") and n.endswith("audit-doc.md")
               for n in names)

    csv_text = zf.read(f"register-{YEAR}.csv").decode()
    assert "'=EMG audit" in csv_text  # formula escaping preserved in the bundle
    md_text = zf.read(f"register-{YEAR}.md").decode()
    assert "=EMG audit" in md_text and "Journal reading" in md_text
    assert "MISSING FILE" in md_text and "vanished.pdf" in md_text
    assert "Cat 3: 1.5 h" in md_text

    # other years' entries stay out of the bundle
    assert "ANZAN webinar" not in md_text


def test_secure_cookie_flag(client, monkeypatch):
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    r = client.post("/login", data={"password": "test-pass"}, follow_redirects=False)
    assert r.status_code == 303
    assert "secure" in r.headers["set-cookie"].lower()
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    r = client.post("/login", data={"password": "test-pass"}, follow_redirects=False)
    assert "secure" not in r.headers["set-cookie"].lower()
