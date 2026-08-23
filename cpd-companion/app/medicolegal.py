"""M5 — Medicolegal report audit (Cat 3).

Finished reports dropped into /data/inbox/medicolegal are detected by hash,
their text extracted locally (docx/pdf/txt — reports never leave the server),
and objective metrics computed in code: dates, turnaround, section presence
against a configurable checklist (default: NSW UCPR Schedule 7 expert-report
elements). A monthly `medicolegal_audit` claude job drafts the audit narrative
from the metrics alone — the payload contains no filenames and no report text,
so the draft is de-identified by construction. Sign-off on the dashboard turns
it into a confirmed Cat 3 activity with the audit document as evidence.
"""

import hashlib
import json
import logging
import re
import statistics
import zipfile
from datetime import date, datetime, timedelta

from . import config, db

log = logging.getLogger("cpd.medicolegal")

REPORT_EXTENSIONS = (".docx", ".pdf", ".txt")

# NSW UCPR Schedule 7 (Expert witness code of conduct) report elements, as
# case-insensitive regex alternatives. Override via the 'medicolegal_checklist'
# setting (JSON array of {key, label, patterns}).
DEFAULT_CHECKLIST = [
    {"key": "qualifications", "label": "Expert's qualifications",
     "patterns": [r"qualifications?", r"training and experience", r"curriculum vitae"]},
    {"key": "instructions", "label": "Instructions / questions addressed",
     "patterns": [r"letter of instruction", r"instruct(?:ed|ions)", r"brief(?:ing)? (?:received|provided)"]},
    {"key": "facts_assumptions", "label": "Facts and assumptions relied on",
     "patterns": [r"facts?(?:\W+\w+){0,4}\W+assumptions?", r"assumed facts", r"factual basis", r"history"]},
    {"key": "examinations", "label": "Examinations / investigations relied on",
     "patterns": [r"examination", r"investigations?", r"tests? (?:performed|relied)"]},
    {"key": "opinion", "label": "Opinion",
     "patterns": [r"\bopinion\b"]},
    {"key": "reasons", "label": "Reasons for the opinion",
     "patterns": [r"reasons? for (?:my |the |each )?opinion", r"basis (?:of|for) (?:my |the )?opinion"]},
    {"key": "materials", "label": "Literature / materials relied on",
     "patterns": [r"literature", r"materials? (?:relied|reviewed|considered)", r"documents? (?:reviewed|provided)"]},
    {"key": "code_acknowledgement", "label": "Expert code of conduct acknowledgement",
     "patterns": [r"expert witness code of conduct", r"schedule 7", r"uniform civil procedure"]},
]

_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
_DATE_WORDY = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\b", re.I)

_INSTRUCTION_CONTEXT = re.compile(
    r"(?:letter of instruction|instructions?(?: were)? (?:dated|received)|"
    r"your letter|brief(?:ing)?(?: was)? (?:dated|received))", re.I)
_REPORT_DATE_CONTEXT = re.compile(
    r"(?:date of (?:this )?report|report (?:is )?dated|dated this)", re.I)


def get_checklist() -> list[dict]:
    raw = db.get_setting("medicolegal_checklist")
    if raw:
        try:
            checklist = json.loads(raw)
            if isinstance(checklist, list) and checklist:
                return checklist
        except (ValueError, TypeError):
            log.warning("bad medicolegal_checklist setting; using default")
    return DEFAULT_CHECKLIST


# --- text extraction (local only) ---------------------------------------------

def _extract_docx(path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml_text = zf.read("word/document.xml").decode("utf-8", "replace")
    xml_text = re.sub(r"</w:p>", "\n", xml_text)
    text = re.sub(r"<[^>]+>", "", xml_text)
    import html as html_mod

    return html_mod.unescape(text)


def _extract_pdf(path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract_text(path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".pdf":
        return _extract_pdf(path)
    return path.read_text(encoding="utf-8", errors="replace")


# --- objective metrics ----------------------------------------------------------

def _dates_near(pattern: re.Pattern, text: str, window: int = 120) -> list[date]:
    found = []
    for match in pattern.finditer(text):
        chunk = text[match.end():match.end() + window]
        found.extend(_parse_dates(chunk))
    return found


def _parse_dates(text: str) -> list[date]:
    dates = []
    for m in _DATE_NUMERIC.finditer(text):
        day, month, year = int(m[1]), int(m[2]), int(m[3])
        try:
            dates.append(date(year, month, day))
        except ValueError:
            continue
    for m in _DATE_WORDY.finditer(text):
        try:
            dates.append(date(int(m[3]), _MONTHS.index(m[2].lower()) + 1, int(m[1])))
        except ValueError:
            continue
    return dates


def compute_metrics(text: str, checklist: list[dict]) -> dict:
    sections = {}
    for item in checklist:
        sections[item["key"]] = any(
            re.search(p, text, re.I) for p in item.get("patterns", []))
    all_dates = _parse_dates(text)
    report_dates = _dates_near(_REPORT_DATE_CONTEXT, text)
    report_date = report_dates[0] if report_dates else (max(all_dates) if all_dates else None)
    instruction_dates = _dates_near(_INSTRUCTION_CONTEXT, text)
    instruction_date = min(instruction_dates) if instruction_dates else None
    turnaround = None
    if report_date and instruction_date:
        diff = (report_date - instruction_date).days
        if 0 <= diff <= 400:
            turnaround = diff
    return {
        "word_count": len(text.split()),
        "sections": sections,
        "report_date": report_date.isoformat() if report_date else None,
        "instruction_date": instruction_date.isoformat() if instruction_date else None,
        "turnaround_days": turnaround,
    }


def scan_inbox() -> list[int]:
    """Detect new report files by content hash; extract + measure locally.

    Old reports dropped into the `backfill/` subfolder are marked so they feed
    the response library but stay out of the monthly audits (which measure the
    month's actual output)."""
    config.ensure_dirs()
    checklist = get_checklist()
    new_ids: list[int] = []
    folders = ((config.MEDICOLEGAL_INBOX, 0), (config.MEDICOLEGAL_BACKFILL, 1))
    for folder, backfill in folders:
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix.lower() not in REPORT_EXTENSIONS:
                continue
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            with db.tx() as conn:
                if conn.execute("SELECT 1 FROM reports WHERE sha256 = ?", (sha,)).fetchone():
                    continue
                parse_error = ""
                metrics = {"word_count": 0, "sections": {}, "report_date": None,
                           "instruction_date": None, "turnaround_days": None}
                try:
                    metrics = compute_metrics(extract_text(path), checklist)
                except Exception as exc:  # noqa: BLE001 - record and keep scanning
                    parse_error = str(exc)[:500]
                    log.warning("failed to parse %s: %s", path.name, exc)
                cur = conn.execute(
                    "INSERT INTO reports (filename, sha256, detected_at, report_date,"
                    " instruction_date, turnaround_days, word_count, sections,"
                    " parse_error, backfill) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (path.name, sha, db.now_iso(), metrics["report_date"],
                     metrics["instruction_date"], metrics["turnaround_days"],
                     metrics["word_count"], json.dumps(metrics["sections"]),
                     parse_error, backfill),
                )
                new_ids.append(cur.lastrowid)
    return new_ids


# --- monthly audit --------------------------------------------------------------

def _aggregate(reports: list, checklist: list[dict]) -> dict:
    turnarounds = [r["turnaround_days"] for r in reports if r["turnaround_days"] is not None]
    section_pct = {}
    for item in checklist:
        present = sum(
            1 for r in reports if json.loads(r["sections"] or "{}").get(item["key"]))
        section_pct[item["key"]] = round(100 * present / len(reports)) if reports else 0
    return {
        "report_count": len(reports),
        "median_turnaround_days": statistics.median(turnarounds) if turnarounds else None,
        "turnaround_known_for": len(turnarounds),
        "mean_word_count": round(statistics.mean([r["word_count"] for r in reports]))
        if reports else 0,
        "sections_pct": section_pct,
    }


def _audit_prompt(period: str, checklist: list[dict]) -> str:
    labels = {c["key"]: c["label"] for c in checklist}
    return (
        f"You are drafting the monthly medicolegal report audit for {period} as RACP"
        " Category 3 (measuring outcomes) CPD evidence.\n"
        "The payload contains objective metrics computed in code: per-report metrics"
        " (anonymised ids R1, R2, ...), this month's aggregate, and aggregates for"
        " previous months. Section keys mean: "
        + json.dumps(labels) + "\n"
        "Return a JSON result with key:\n"
        "  audit_md: a markdown audit document with sections — 1) summary,"
        " 2) checklist compliance table (section, % of reports, which anonymised"
        " reports are missing it), 3) turnaround analysis, 4) month-on-month trends"
        " vs the previous aggregates, 5) 2-4 concrete improvement suggestions.\n"
        "STRICT RULES: use only the metrics provided — never invent report contents,"
        " parties, or numbers; refer to reports only by their anonymised ids; note"
        " explicitly where data is missing (e.g. turnaround unknown) rather than"
        " estimating it."
    )


def previous_month(today: date | None = None) -> str:
    today = today or datetime.now(config.TZ).date()
    first = today.replace(day=1)
    prev = first - timedelta(days=1)
    return f"{prev.year:04d}-{prev.month:02d}"


def ensure_monthly_audit(period: str | None = None) -> dict:
    """Create (or update) the audit for a month and queue its drafting job.

    Re-running is safe: unattached reports are swept in and a fresh draft is
    queued unless the audit is already signed off. Called without a period
    (the scheduler path), it audits the previous month and then re-queues any
    older audit stuck in 'drafting' with no live job.
    """
    if period is not None:
        return _ensure_period(period)
    result = _ensure_period(previous_month())
    with db.tx() as conn:
        stale = conn.execute(
            "SELECT period FROM audits WHERE status = 'drafting' AND period < ?"
            " AND NOT EXISTS (SELECT 1 FROM jobs WHERE kind = 'medicolegal_audit'"
            "  AND status = 'pending'"
            "  AND json_extract(payload, '$.audit_id') = audits.id)"
            " ORDER BY period",
            (previous_month(),),
        ).fetchall()
    requeued = [row["period"] for row in stale
                if _ensure_period(row["period"]).get("status") == "drafting"]
    if requeued:
        result = dict(result, requeued_stale_periods=requeued)
    return result


def _ensure_period(period: str) -> dict:
    checklist = get_checklist()
    current_month = datetime.now(config.TZ).strftime("%Y-%m")
    if period > current_month:
        # A future (or typo'd) period must never sweep up the report pool.
        return {"period": period, "status": "future_period"}
    year, month = int(period[:4]), int(period[5:7])
    period_end = f"{year + (month == 12):04d}-{(month % 12) + 1:02d}-01"
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        audit = conn.execute("SELECT * FROM audits WHERE period = ?", (period,)).fetchone()
        if audit is not None and audit["status"] == "signed_off":
            return {"period": period, "status": "signed_off", "audit_id": audit["id"]}
        # Sweep every unattached report detected up to the period's end, not
        # just the period's own month — reports detected after an earlier month
        # was signed off roll forward instead of being stranded.
        unattached = conn.execute(
            "SELECT * FROM reports WHERE audit_id IS NULL AND backfill = 0"
            " AND detected_at < ?",
            (period_end,),
        ).fetchall()
        if audit is None:
            if not unattached:
                return {"period": period, "status": "no_reports"}
            cur = conn.execute(
                "INSERT INTO audits (period, checklist, created_at) VALUES (?, ?, ?)",
                (period, json.dumps(checklist), db.now_iso()),
            )
            audit_id = cur.lastrowid
        else:
            audit_id = audit["id"]
            if not unattached:
                pending = conn.execute(
                    "SELECT 1 FROM jobs WHERE kind = 'medicolegal_audit'"
                    " AND status = 'pending'"
                    " AND json_extract(payload, '$.audit_id') = ?",
                    (audit_id,)).fetchone()
                if audit["status"] != "drafting" or pending:
                    return {"period": period, "status": audit["status"],
                            "audit_id": audit_id}
                # 'drafting' with no live job: the drafting job failed — fall
                # through to recompute metrics and queue a fresh one.
        conn.executemany("UPDATE reports SET audit_id = ? WHERE id = ?",
                         [(audit_id, r["id"]) for r in unattached])
        reports = conn.execute(
            "SELECT * FROM reports WHERE audit_id = ? ORDER BY id", (audit_id,)
        ).fetchall()
        aggregate = _aggregate(reports, checklist)
        previous = [
            {"period": r["period"], "aggregate": json.loads(r["metrics"] or "{}").get("aggregate")}
            for r in conn.execute(
                "SELECT period, metrics FROM audits WHERE period < ? ORDER BY period DESC LIMIT 6",
                (period,),
            ).fetchall()
        ]
        # Anonymised ids only — no filenames and no report text leave this module.
        per_report = [
            {"id": f"R{i + 1}", "word_count": r["word_count"],
             "turnaround_days": r["turnaround_days"],
             "sections": json.loads(r["sections"] or "{}"),
             "parse_error": bool(r["parse_error"])}
            for i, r in enumerate(reports)
        ]
        metrics = {"aggregate": aggregate, "per_report": per_report, "previous": previous}
        conn.execute(
            "UPDATE audits SET metrics = ?, status = 'drafting', checklist = ? WHERE id = ?",
            (json.dumps(metrics), json.dumps(checklist), audit_id),
        )
        # An audit only ever has one live drafting job: a re-run with fresh
        # reports supersedes the stale pending one.
        conn.execute(
            "UPDATE jobs SET status = 'failed', error = 'superseded by audit re-run',"
            " completed_at = ? WHERE kind = 'medicolegal_audit' AND status = 'pending'"
            " AND json_extract(payload, '$.audit_id') = ?",
            (db.now_iso(), audit_id),
        )
        payload = {"period": period, "audit_id": audit_id, **metrics}
        conn.execute(
            "INSERT INTO jobs (kind, engine, payload, prompt, created_at)"
            " VALUES ('medicolegal_audit', 'claude', ?, ?, ?)",
            (json.dumps(payload), _audit_prompt(period, checklist), db.now_iso()),
        )
    return {"period": period, "status": "drafting", "audit_id": audit_id,
            "report_count": aggregate["report_count"]}


def apply_audit_result(conn, job, result: dict) -> dict:
    """Store the drafted audit narrative (inside the caller's transaction)."""
    audit_md = str(result.get("audit_md", "")).strip()
    if not audit_md:
        return {"error": "result must include a non-empty 'audit_md'"}
    payload = json.loads(job["payload"] or "{}")
    audit_id = payload.get("audit_id")
    audit = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
    if audit is None:
        return {"error": f"audit {audit_id} not found"}
    now = db.now_iso()
    if audit["status"] == "signed_off":
        # A stale draft must never overwrite a signed-off audit.
        conn.execute(
            "UPDATE jobs SET status = 'done', result = ?, completed_at = ? WHERE id = ?",
            (json.dumps({"skipped": "audit already signed off"}), now, job["id"]),
        )
        return {"job": job["id"], "status": "done", "skipped": "audit already signed off"}
    conn.execute(
        "UPDATE audits SET draft_text = ?, status = 'review' WHERE id = ?",
        (audit_md[:60000], audit_id),
    )
    conn.execute(
        "UPDATE jobs SET status = 'done', result = ?, completed_at = ? WHERE id = ?",
        (json.dumps({"audit_id": audit_id}), now, job["id"]),
    )
    return {"job": job["id"], "status": "done", "audit_id": audit_id}


def sign_off(audit_id: int, final_text: str, minutes: int) -> int | None:
    """Dashboard sign-off: confirmed Cat 3 activity + de-identified evidence doc.

    Returns the activity id, or None if the audit is missing/already signed off.
    """
    with db.tx() as conn:
        # BEGIN IMMEDIATE serialises the check-then-act so a double-submitted
        # sign-off cannot create two confirmed activities (same convention as
        # the rollups).
        conn.execute("BEGIN IMMEDIATE")
        audit = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
        if audit is None or audit["status"] == "signed_off":
            return None
        checklist = json.loads(audit["checklist"] or "[]")
        metrics = json.loads(audit["metrics"] or "{}")
        now = db.now_iso()
        cur = conn.execute(
            "INSERT INTO activities (date, category, activity_type, title, description,"
            " minutes, source_module, status, created_at, confirmed_at)"
            " VALUES (?, 3, 'audit', ?, ?, ?, 'medicolegal', 'confirmed', ?, ?)",
            (db.today_iso(),
             f"Medicolegal report audit — {audit['period']}",
             f"Standards-based audit of {metrics.get('aggregate', {}).get('report_count', '?')}"
             f" medicolegal reports against the expert-report checklist."
             " De-identified audit document attached as evidence.",
             minutes, now, now),
        )
        activity_id = cur.lastrowid
        doc = config.EVIDENCE_DIR / f"medicolegal-audit-{audit['period']}-a{activity_id}.md"
        labels = {c["key"]: c["label"] for c in checklist}
        lines = [f"# Medicolegal report audit — {audit['period']}", "",
                 final_text.strip(), "", "---", "",
                 "## Appendix: objective metrics (computed in code, de-identified)", ""]
        aggregate = metrics.get("aggregate", {})
        lines.append(f"- Reports audited: {aggregate.get('report_count')}")
        lines.append(f"- Median turnaround: {aggregate.get('median_turnaround_days')} days"
                     f" (known for {aggregate.get('turnaround_known_for')} reports)")
        lines.append(f"- Mean length: {aggregate.get('mean_word_count')} words")
        lines += ["", "| Checklist element | Present |", "|---|---|"]
        for key, pct in aggregate.get("sections_pct", {}).items():
            lines.append(f"| {labels.get(key, key)} | {pct}% |")
        db.add_generated_evidence(conn, activity_id, doc,
                                  "\n".join(lines).encode("utf-8"))
        conn.execute(
            "UPDATE audits SET final_text = ?, status = 'signed_off', activity_id = ?,"
            " signed_off_at = ? WHERE id = ?",
            (final_text[:60000], activity_id, now, audit_id),
        )
    return activity_id


# --- response library (Q&A extraction) -----------------------------------------
#
# Beyond auditing, each report's question-and-answer sections and opinion
# passages are worth mining: a `report_extract` claude job de-identifies the
# report and distils the doctor's own answers into generic, reusable template
# responses per condition/topic. Drafts are curated (approve / edit / reject)
# on the Library page, searched when writing the next report, and exported to
# the practice's medicolegal app. Old reports go through the same pipeline
# gradually via the backfill folder + weekly batches.

EXTRACT_TEXT_LIMIT = 60000
DEFAULT_EXTRACT_BATCH = 5


def _prescrub(text: str) -> str:
    """Best-effort code-level redaction before report text enters the job
    queue; the extraction prompt does the real de-identification and the
    curation step is the human check."""
    text = re.sub(r"(?im)^\s*(re|regarding)\s*:.*$", "RE: [redacted]", text)
    # Redact only the date-like token, not the rest of the line — an inline
    # "…whose date of birth is 12 March 1965, presented with…" must keep the
    # clinical content that follows.
    text = re.sub(
        r"(?i)date of birth\s*(?:is|was)?\s*[:\-]?\s*"
        r"(?:\d{1,2}(?:st|nd|rd|th)?\s+\w+,?\s+\d{2,4}|\w+\s+\d{1,2},?\s+\d{2,4}|[\d/.\-]+)",
        "Date of birth: [redacted]", text)
    text = re.sub(r"(?i)\bd\.?o\.?b\.?\s*[:\-]?\s*[\d/.\-]+", "DOB: [redacted]", text)
    text = re.sub(r"(?i)\b(claim|matter|file|reference)\s*(no\.?|number)\s*[:\-]?\s*\S+",
                  r"\1 number: [redacted]", text)
    return text


def _extract_prompt() -> str:
    return (
        "You are mining one of the doctor's own finished medicolegal reports for"
        " their RESPONSE LIBRARY: reusable, generic answers to the questions"
        " solicitors ask, so future reports can reuse the doctor's established"
        " wording.\n"
        "The payload contains the report text (partially pre-redacted).\n"
        "Return a JSON result with key:\n"
        "  snippets: array (0-10) of {condition, topic, question, answer} where\n"
        "    condition: the clinical condition the answer concerns (e.g. 'mild"
        " traumatic brain injury', 'cervical radiculopathy', 'functional neurological"
        " disorder')\n"
        "    topic: the question theme — e.g. causation, diagnosis, prognosis,"
        " treatment capacity, work capacity, permanent impairment, credibility of"
        " symptoms, need for further investigations\n"
        "    question: the generic form of the question asked\n"
        "    answer: the doctor's answer rewritten as a GENERIC template — keep the"
        " doctor's own reasoning, structure and turns of phrase (that is the value),"
        " but replace every case-specific detail with placeholders like [duration],"
        " [side], [occupation], [mechanism].\n"
        "STRICT RULES: de-identify absolutely — no names, initials, dates of birth,"
        " addresses, employers, insurers, claim numbers, specific dates, or any"
        " detail that could identify the examinee or parties; extract only"
        " reasoning that is actually in the report — never add medical content the"
        " doctor did not write; skip boilerplate (qualifications, declarations,"
        " code-of-conduct text); return an empty array if the report has no"
        " reusable Q&A material."
    )


def _find_report_file(filename: str, sha256: str):
    """Resolve a report row back to its file by content hash, not just name —
    same-named files in inbox/ and backfill/ must never mine the wrong text."""
    for folder in (config.MEDICOLEGAL_INBOX, config.MEDICOLEGAL_BACKFILL):
        candidate = folder / filename
        if candidate.is_file() and hashlib.sha256(
                candidate.read_bytes()).hexdigest() == sha256:
            return candidate
    return None


def queue_extractions(limit: int | None = None) -> dict:
    """Queue the next batch of un-mined reports (weekly; gradual by design)."""
    if limit is None:
        try:
            limit = max(1, int(db.get_setting("report_extract_batch",
                                              str(DEFAULT_EXTRACT_BATCH))))
        except ValueError:
            limit = DEFAULT_EXTRACT_BATCH
    # Phase 1: pick the batch and parse the files with NO write lock held —
    # pdf/docx extraction can be slow and must not block other writers.
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT * FROM reports WHERE extract_status = 'pending'"
            " AND parse_error = '' ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    prepared: list[tuple[int, str | None]] = []
    for r in rows:
        path = _find_report_file(r["filename"], r["sha256"])
        if path is None:
            prepared.append((r["id"], None))
            continue
        try:
            prepared.append((r["id"], _prescrub(extract_text(path))[:EXTRACT_TEXT_LIMIT]))
        except Exception as exc:  # noqa: BLE001 - mark and continue
            log.warning("re-extraction failed for %s: %s", r["filename"], exc)
            prepared.append((r["id"], None))
    # Phase 2: claim each report atomically (guarded UPDATE) and queue its job.
    queued: list[int] = []
    skipped: list[int] = []
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for report_id, text in prepared:
            if text is None:
                if conn.execute(
                    "UPDATE reports SET extract_status = 'skipped'"
                    " WHERE id = ? AND extract_status = 'pending'", (report_id,)
                ).rowcount:
                    skipped.append(report_id)
                continue
            if not conn.execute(
                "UPDATE reports SET extract_status = 'queued'"
                " WHERE id = ? AND extract_status = 'pending'", (report_id,)
            ).rowcount:
                continue  # claimed by a concurrent run
            conn.execute(
                "INSERT INTO jobs (kind, engine, payload, prompt, created_at)"
                " VALUES ('report_extract', 'claude', ?, ?, ?)",
                (json.dumps({"report_id": report_id, "text": text}), _extract_prompt(),
                 db.now_iso()),
            )
            queued.append(report_id)
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM reports WHERE extract_status = 'pending'"
            " AND parse_error = ''").fetchone()["n"]
    return {"queued": queued, "skipped": skipped, "remaining": remaining}


def apply_extract_result(conn, job, result: dict) -> dict:
    snippets = result.get("snippets")
    if not isinstance(snippets, list):
        return {"error": "result must include a 'snippets' array"}
    payload = json.loads(job["payload"] or "{}")
    report_id = payload.get("report_id")
    now = db.now_iso()
    created = 0
    for s in snippets[:10]:
        if not isinstance(s, dict):
            continue
        question = str(s.get("question", "")).strip()
        answer = str(s.get("answer", "")).strip()
        if not question or not answer:
            continue
        conn.execute(
            "INSERT INTO response_snippets (condition, topic, question, answer,"
            " source_report_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(s.get("condition", "")).strip()[:200],
             str(s.get("topic", "")).strip()[:200],
             question[:2000], answer[:10000], report_id, now),
        )
        created += 1
    conn.execute("UPDATE reports SET extract_status = 'done' WHERE id = ?", (report_id,))
    # Scrub the report text out of the completed job so the jobs table never
    # becomes a lingering mirror of the report archive (backups included).
    conn.execute(
        "UPDATE jobs SET status = 'done', result = ?, payload = ?, completed_at = ?"
        " WHERE id = ?",
        (json.dumps({"report_id": report_id, "snippets": created}),
         json.dumps({"report_id": report_id}), now, job["id"]),
    )
    return {"job": job["id"], "status": "done", "snippets_created": created}


def review_snippet(snippet_id: int, action: str, fields: dict | None = None) -> bool:
    if action not in ("approved", "rejected"):
        return False
    sets = {}
    if fields:
        for key in ("condition", "topic", "question", "answer"):
            if key in fields and str(fields[key]).strip():
                sets[key] = str(fields[key]).strip()[:10000]
    with db.tx() as conn:
        row = conn.execute("SELECT id FROM response_snippets WHERE id = ? AND"
                           " status = 'draft'", (snippet_id,)).fetchone()
        if row is None:
            return False
        assignments = ", ".join([f"{k} = ?" for k in sets] + ["status = ?", "reviewed_at = ?"])
        conn.execute(
            f"UPDATE response_snippets SET {assignments} WHERE id = ?",
            (*sets.values(), action, db.now_iso(), snippet_id),
        )
    return True


def log_curation_session(minutes: int) -> int | None:
    """Confirmed Cat 2 activity for the curation work done since the last log.

    Reviewing one's own report answers and distilling them into standardised
    responses is review of own work product (Cat 2); minutes come from the
    page timer, and the evidence document lists the (generic, de-identified)
    snippets reviewed. Counted snippets are marked `logged` inside the same
    transaction, so a double submit finds nothing to log and no snippet can be
    counted twice or slip between a timestamp watermark and the log."""
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        reviewed = conn.execute(
            "SELECT * FROM response_snippets WHERE reviewed_at IS NOT NULL"
            " AND logged = 0 ORDER BY reviewed_at, id",
        ).fetchall()
        if not reviewed:
            return None
        approved = [s for s in reviewed if s["status"] == "approved"]
        now = db.now_iso()
        cur = conn.execute(
            "INSERT INTO activities (date, category, activity_type, title, description,"
            " minutes, source_module, status, created_at, confirmed_at)"
            " VALUES (?, 2, 'self_review', ?, ?, ?, 'library', 'confirmed', ?, ?)",
            (db.today_iso(),
             "Medicolegal response review — standardising report answers",
             f"Reviewed {len(reviewed)} extracted Q&A responses from own medicolegal"
             f" reports ({len(approved)} standardised into the response library)."
             " De-identified summary attached as evidence.",
             minutes, now, now),
        )
        activity_id = cur.lastrowid
        doc = config.EVIDENCE_DIR / f"response-library-session-{now[:10]}-a{activity_id}.md"
        lines = [f"# Medicolegal response library — curation session {now[:10]}", "",
                 f"Snippets reviewed: {len(reviewed)} (approved: {len(approved)},"
                 f" rejected: {len(reviewed) - len(approved)})", ""]
        for s in approved:
            lines += [f"## {s['condition'] or 'General'} — {s['topic'] or 'untopiced'}",
                      "", f"**Q:** {s['question']}", "", f"**A:** {s['answer']}", ""]
        db.add_generated_evidence(conn, activity_id, doc,
                                  "\n".join(lines).encode("utf-8"))
        conn.executemany("UPDATE response_snippets SET logged = 1 WHERE id = ?",
                         [(s["id"],) for s in reviewed])
    return activity_id


def search_snippets(query: str = "", status: str = "approved") -> list:
    sql = "SELECT * FROM response_snippets WHERE status = ?"
    params: list = [status]
    if query.strip():
        like = f"%{query.strip()}%"
        sql += (" AND (condition LIKE ? OR topic LIKE ? OR question LIKE ?"
                " OR answer LIKE ?)")
        params += [like, like, like, like]
    sql += " ORDER BY condition, topic, id"
    with db.tx() as conn:
        return conn.execute(sql, params).fetchall()


def library_export_md() -> str:
    rows = search_snippets()
    lines = ["# Medicolegal response library", ""]
    current = None
    for s in rows:
        condition = s["condition"] or "General"
        if condition != current:
            lines += [f"## {condition}", ""]
            current = condition
        lines += [f"### {s['topic'] or 'General'} — {s['question']}", "",
                  s["answer"], ""]
    return "\n".join(lines)


def trend_rows() -> list[dict]:
    """Month-on-month table for the audits page."""
    with db.tx() as conn:
        audits = conn.execute("SELECT * FROM audits ORDER BY period DESC").fetchall()
    rows = []
    for a in audits:
        aggregate = json.loads(a["metrics"] or "{}").get("aggregate", {})
        rows.append({
            "id": a["id"], "period": a["period"], "status": a["status"],
            "report_count": aggregate.get("report_count"),
            "median_turnaround_days": aggregate.get("median_turnaround_days"),
            "mean_word_count": aggregate.get("mean_word_count"),
            "sections_pct": aggregate.get("sections_pct", {}),
        })
    return rows
