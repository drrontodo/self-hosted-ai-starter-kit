"""M5 medicolegal audit tests: inbox scan, local text extraction, objective
metrics, monthly audit job, sign-off, and the de-identification guarantees."""

import io
import json
import os
import zipfile
from pathlib import Path

from tests.test_app import KEY, client, login  # noqa: F401 - reuse env setup + fixture
from app import config, db, medicolegal

REPORT_TEXT = """Expert report prepared for the Supreme Court of NSW.

1. Qualifications: I am a consultant neurologist with 20 years experience.
2. Instructions: I refer to your letter of instruction dated 3 June 2026.
3. Facts and assumptions relied on: the history is set out below.
4. Examination findings and investigations are described in section 5.
5. Opinion: in my opinion the plaintiff sustained a mild traumatic brain injury.
6. Reasons for my opinion: the imaging and examination findings support this.
7. Literature and materials relied on are listed in Appendix A.
I acknowledge the Expert Witness Code of Conduct in Schedule 7 of the UCPR.

Date of report: 24 June 2026
"""

INCOMPLETE_TEXT = """Report regarding the plaintiff.
Opinion: the injury was mild.
Dated 10/06/2026.
"""


def make_docx(text: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.splitlines())
        + "</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org'
                    '/package/2006/content-types"/>')
        zf.writestr("word/document.xml", document)
    return buf.getvalue()


def make_pdf(text: str) -> bytes:
    """Minimal single-page PDF with a correct xref table."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF").encode()
    return bytes(out)


def _drop(name: str, data: bytes) -> Path:
    config.ensure_dirs()
    path = config.MEDICOLEGAL_INBOX / name
    path.write_bytes(data)
    return path


def test_scan_extract_and_metrics(client):
    _drop("smith-v-jones.docx", make_docx(REPORT_TEXT))
    _drop("incomplete-report.txt", INCOMPLETE_TEXT.encode())
    _drop("pdf-report.pdf", make_pdf("Qualifications and opinion, dated this 5/6/2026"))
    _drop("ignore.tmp", b"not a report")

    new = medicolegal.scan_inbox()
    assert len(new) == 3
    assert medicolegal.scan_inbox() == []  # hash dedupe

    with db.tx() as conn:
        full = conn.execute("SELECT * FROM reports WHERE filename = 'smith-v-jones.docx'").fetchone()
        partial = conn.execute("SELECT * FROM reports WHERE filename = 'incomplete-report.txt'").fetchone()
        pdf = conn.execute("SELECT * FROM reports WHERE filename = 'pdf-report.pdf'").fetchone()

    sections = json.loads(full["sections"])
    assert all(sections.values()), sections  # every checklist element present
    assert full["instruction_date"] == "2026-06-03"
    assert full["report_date"] == "2026-06-24"
    assert full["turnaround_days"] == 21
    assert full["word_count"] > 50

    partial_sections = json.loads(partial["sections"])
    assert partial_sections["opinion"] is True
    assert partial_sections["code_acknowledgement"] is False
    assert partial["turnaround_days"] is None

    assert pdf["parse_error"] == ""
    assert json.loads(pdf["sections"])["qualifications"] is True


def test_unreadable_file_records_parse_error(client):
    _drop("corrupt.docx", b"this is not a zip archive")
    new = medicolegal.scan_inbox()
    assert len(new) == 1
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM reports WHERE filename = 'corrupt.docx'").fetchone()
    assert row["parse_error"] != ""
    assert row["word_count"] == 0


def test_monthly_audit_flow_and_deidentification(client):
    login(client)
    period = db.today_iso()[:7]  # the drops above were detected this month

    out = medicolegal.ensure_monthly_audit(period)
    assert out["status"] == "drafting"
    audit_id = out["audit_id"]
    assert out["report_count"] >= 4

    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    job = next(j for j in jobs if j["kind"] == "medicolegal_audit")
    payload = job["payload"]
    # de-identified by construction: anonymised ids only, no filenames, no text
    blob = json.dumps(payload)
    assert "smith-v-jones" not in blob and "plaintiff" not in blob
    assert payload["per_report"][0]["id"] == "R1"
    assert payload["aggregate"]["report_count"] >= 4
    assert "never invent" in job["prompt"]

    # duplicate run with no new reports: no second job
    out2 = medicolegal.ensure_monthly_audit(period)
    assert out2["status"] == "drafting"
    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    assert len([j for j in jobs if j["kind"] == "medicolegal_audit"]) == 1

    r = client.post(f"/api/jobs/{job['id']}/result", headers=KEY,
                    json={"audit_md": "## Compliance\nR2 lacks the code acknowledgement."})
    assert r.status_code == 200
    with db.tx() as conn:
        audit = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
    assert audit["status"] == "review"
    assert "R2 lacks" in audit["draft_text"]

    # audit detail page renders with the draft
    page = client.get(f"/audits/{audit_id}").text
    assert "R2 lacks" in page and "Sign off" in page

    # sign-off -> confirmed Cat 3 activity + de-identified evidence doc
    r = client.post(f"/audits/{audit_id}/signoff",
                    data={"final_text": "## Final audit\nAll good, R2 to add Schedule 7.",
                          "minutes": "25"},
                    follow_redirects=False)
    assert r.status_code == 303
    with db.tx() as conn:
        audit = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
        activity = conn.execute("SELECT * FROM activities WHERE id = ?",
                                (audit["activity_id"],)).fetchone()
        evidence = conn.execute("SELECT * FROM evidence WHERE activity_id = ?",
                                (activity["id"],)).fetchall()
    assert audit["status"] == "signed_off"
    assert activity["category"] == 3 and activity["status"] == "confirmed"
    assert activity["minutes"] == 25
    assert activity["source_module"] == "medicolegal"
    assert len(evidence) == 1
    doc_text = Path(evidence[0]["path_or_url"]).read_text()
    assert "R2 to add Schedule 7" in doc_text
    assert "smith-v-jones" not in doc_text  # evidence stays de-identified
    assert "Reports audited" in doc_text

    # signed-off audits are immutable via sign-off and via late job results
    assert medicolegal.sign_off(audit_id, "overwrite attempt", 5) is None
    out3 = medicolegal.ensure_monthly_audit(period)
    assert out3["status"] == "signed_off"


def test_late_draft_cannot_touch_signed_off_audit(client):
    # queue a second audit for another period, sign it off, then post the draft
    _drop("late-report.txt", b"Opinion: fine. Qualifications listed. Dated 2/2/2026.")
    ids = medicolegal.scan_inbox()
    assert len(ids) == 1
    period = db.today_iso()[:7]
    with db.tx() as conn:
        # move the report into a fake earlier period to get a separate audit
        conn.execute("UPDATE reports SET detected_at = '2026-02-10T10:00:00+11:00'"
                     " WHERE id = ?", (ids[0],))
    out = medicolegal.ensure_monthly_audit("2026-02")
    audit_id = out["audit_id"]
    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    job = next(j for j in jobs if j["kind"] == "medicolegal_audit"
               and j["payload"].get("audit_id") == audit_id)
    assert medicolegal.sign_off(audit_id, "signed before the draft arrived", 10) is not None
    r = client.post(f"/api/jobs/{job['id']}/result", headers=KEY,
                    json={"audit_md": "stale draft"})
    assert r.status_code == 200
    assert r.json().get("skipped")
    with db.tx() as conn:
        audit = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
    assert audit["final_text"] == "signed before the draft arrived"
    assert "stale draft" not in (audit["draft_text"] or "")


def test_audits_page_renders_trend(client):
    login(client)
    page = client.get("/audits").text
    assert "Month-on-month" in page
    assert "2026-02" in page  # audit from the previous test
    assert "Scan inbox now" in page


def test_empty_month_creates_nothing(client):
    out = medicolegal.ensure_monthly_audit("2019-01")
    assert out["status"] == "no_reports"
    with db.tx() as conn:
        assert conn.execute("SELECT * FROM audits WHERE period = '2019-01'").fetchone() is None
