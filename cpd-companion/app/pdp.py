"""M6 — Professional Development Plan builder (Cat 2 + mandatory tracker).

A guided form following the RACP PDP template structure (development goals,
planned activities per category, timeframes, success measures). A `pdp_draft`
claude job can pre-draft the document from the stated goals plus the activity
register; completing the PDP on the dashboard generates the evidence document,
creates a confirmed Cat 2 activity, and ticks the mandatory-items tracker.
"""

import json

from . import config, db

FORM_FIELDS = ("goals", "planned_cat1", "planned_cat2", "planned_cat3",
               "timeframes", "success_measures")


def get_or_create(year: int) -> dict:
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM pdp WHERE year = ?", (year,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO pdp (year, created_at) VALUES (?, ?)",
                         (year, db.now_iso()))
            row = conn.execute("SELECT * FROM pdp WHERE year = ?", (year,)).fetchone()
    return dict(row)


def save_form(year: int, fields: dict) -> None:
    row = get_or_create(year)
    if row["status"] == "completed":
        return
    sets = {k: str(fields.get(k, ""))[:8000] for k in FORM_FIELDS}
    with db.tx() as conn:
        conn.execute(
            "UPDATE pdp SET goals = ?, planned_cat1 = ?, planned_cat2 = ?,"
            " planned_cat3 = ?, timeframes = ?, success_measures = ? WHERE year = ?",
            (*[sets[k] for k in FORM_FIELDS], year),
        )


def _register_summary(conn, year: int) -> dict:
    rows = conn.execute(
        "SELECT category, activity_type, title, minutes FROM activities"
        " WHERE status = 'confirmed' AND date BETWEEN ? AND ?"
        " ORDER BY category, date DESC LIMIT 60",
        (f"{year - 1}-01-01", f"{year}-12-31"),
    ).fetchall()
    return {
        "recent_confirmed_activities": [
            {"category": r["category"], "type": r["activity_type"],
             "title": r["title"], "minutes": r["minutes"]}
            for r in rows
        ],
        "progress_this_year": db.progress(year),
    }


def _draft_prompt(year: int) -> str:
    return (
        f"You are pre-drafting a {year} RACP Professional Development Plan for a"
        " consultant neurologist, following the RACP PDP template structure.\n"
        "The payload contains the doctor's own stated goals and planned activities"
        " (verbatim), plus their recent confirmed CPD register and current-year"
        " progress against the RACP minimums.\n"
        "Return a JSON result with key:\n"
        "  pdp_md: a markdown PDP with sections — 1) Development goals (refine the"
        " stated goals into specific, measurable goals; keep their intent),"
        " 2) Planned CPD activities per category (Cat 1 / Cat 2 / Cat 3) with how"
        " each maps to a goal, 3) Timeframes, 4) Success measures, 5) Gaps to watch"
        " (categories currently behind, mandatory cultural-safety/ethics items).\n"
        "STRICT RULES: build only on the stated goals and the supplied register —"
        " never invent achievements, roles, or commitments the doctor did not state;"
        " where a section has no input, leave a clearly marked placeholder for the"
        " doctor to fill in."
    )


def queue_draft(year: int) -> int | None:
    """Queue the claude pre-draft job for a year's PDP (one pending at a time)."""
    row = get_or_create(year)
    if row["status"] == "completed":
        return None
    with db.tx() as conn:
        pending = conn.execute(
            "SELECT id FROM jobs WHERE kind = 'pdp_draft' AND status = 'pending'"
        ).fetchone()
        if pending:
            return None
        payload = {
            "year": year,
            "stated": {k: row[k] for k in FORM_FIELDS},
            **_register_summary(conn, year),
        }
        cur = conn.execute(
            "INSERT INTO jobs (kind, engine, payload, prompt, created_at)"
            " VALUES ('pdp_draft', 'claude', ?, ?, ?)",
            (json.dumps(payload), _draft_prompt(year), db.now_iso()),
        )
        conn.execute("UPDATE pdp SET status = 'drafting' WHERE year = ?", (year,))
        return cur.lastrowid


def apply_draft_result(conn, job, result: dict) -> dict:
    pdp_md = str(result.get("pdp_md", "")).strip()
    if not pdp_md:
        return {"error": "result must include a non-empty 'pdp_md'"}
    payload = json.loads(job["payload"] or "{}")
    year = payload.get("year")
    row = conn.execute("SELECT * FROM pdp WHERE year = ?", (year,)).fetchone()
    now = db.now_iso()
    if row is None or row["status"] == "completed":
        conn.execute(
            "UPDATE jobs SET status = 'done', result = ?, completed_at = ? WHERE id = ?",
            (json.dumps({"skipped": "pdp missing or completed"}), now, job["id"]),
        )
        return {"job": job["id"], "status": "done", "skipped": "pdp missing or completed"}
    conn.execute("UPDATE pdp SET draft_md = ?, status = 'editing' WHERE year = ?",
                 (pdp_md[:60000], year))
    conn.execute(
        "UPDATE jobs SET status = 'done', result = ?, completed_at = ? WHERE id = ?",
        (json.dumps({"year": year}), now, job["id"]),
    )
    return {"job": job["id"], "status": "done", "year": year}


def complete(year: int, final_md: str, minutes: int) -> int | None:
    """Dashboard completion: evidence doc + confirmed Cat 2 activity + mandatory tick."""
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM pdp WHERE year = ?", (year,)).fetchone()
        if row is None or row["status"] == "completed":
            return None
        now = db.now_iso()
        cur = conn.execute(
            "INSERT INTO activities (date, category, activity_type, title, description,"
            " minutes, source_module, status, created_at, confirmed_at)"
            " VALUES (?, 2, 'pdp', ?, ?, ?, 'pdp', 'confirmed', ?, ?)",
            (db.today_iso(), f"Professional Development Plan — {year}",
             "PDP prepared per the RACP template; completed plan attached as evidence.",
             minutes, now, now),
        )
        activity_id = cur.lastrowid
        doc = config.EVIDENCE_DIR / f"pdp-{year}-a{activity_id}.md"
        doc.write_text(f"# Professional Development Plan — {year}\n\n{final_md.strip()}\n",
                       encoding="utf-8")
        conn.execute(
            "INSERT INTO evidence (activity_id, kind, path_or_url, created_at)"
            " VALUES (?, 'generated_doc', ?, ?)",
            (activity_id, str(doc), now),
        )
        conn.execute(
            "UPDATE pdp SET draft_md = ?, status = 'completed', activity_id = ?,"
            " completed_at = ? WHERE year = ?",
            (final_md[:60000], activity_id, now, year),
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, '1')"
            " ON CONFLICT(key) DO UPDATE SET value = '1'",
            (f"pdp_done_{year}",),
        )
    return activity_id
