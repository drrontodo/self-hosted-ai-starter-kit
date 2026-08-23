"""M2 — East Neurology Google reviews (Cat 2: patient feedback).

Reviews accrue silently from a daily Google Places poll (hash-deduped; the API
only returns ~5 at a time, so daily polling accumulates them) plus manual JSON
exports dropped into /data/inbox/reviews. Every quarter (configurable via the
`review_cycle_months` setting) a review cycle opens: a `review_themes` claude
job drafts praise/complaint themes and suggested practice actions, the
suggested actions land in the practice-improvement backlog, and sign-off on
the dashboard creates a confirmed Cat 2 activity with a generated feedback
summary as evidence.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

import httpx

from . import config, db
from .news import safe_err

log = logging.getLogger("cpd.reviews")

PLACES_URL = "https://maps.googleapis.com/maps/api/place/details/json"


def _review_hash(author: str, text: str, review_date: str) -> str:
    return hashlib.sha256(f"{author}\x00{text}\x00{review_date}".encode()).hexdigest()


def _store_reviews(conn, entries: list[dict]) -> int:
    new = 0
    for e in entries:
        author = str(e.get("author", "")).strip()[:200]
        text = str(e.get("text", "")).strip()[:5000]
        rating = e.get("rating")
        try:
            rating = int(rating) if rating is not None else None
        except (TypeError, ValueError):
            rating = None
        review_date = str(e.get("date", "")).strip()[:10] or None
        if not text and rating is None:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO reviews (review_hash, author, rating, text,"
            " review_date, first_seen) VALUES (?, ?, ?, ?, ?, ?)",
            (_review_hash(author, text, review_date or ""), author, rating, text,
             review_date, db.now_iso()),
        )
        new += cur.rowcount
    return new


def _fetch_place_reviews() -> list[dict]:
    resp = httpx.get(PLACES_URL, params={
        "place_id": config.GOOGLE_PLACE_ID,
        "fields": "reviews",
        "reviews_sort": "newest",
        "key": config.GOOGLE_PLACES_API_KEY,
    }, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "OK":
        raise RuntimeError(
            f"Places API status {body.get('status')}: {body.get('error_message', '')}")
    out = []
    for r in body.get("result", {}).get("reviews", []):
        review_date = ""
        if r.get("time"):
            review_date = datetime.fromtimestamp(
                int(r["time"]), tz=timezone.utc).astimezone(config.TZ).date().isoformat()
        out.append({"author": r.get("author_name", ""), "rating": r.get("rating"),
                    "text": r.get("text", ""), "date": review_date})
    return out


def ingest_inbox() -> int:
    """Parse JSON review exports in /data/inbox/reviews (idempotent via hash).

    Accepted shape: a JSON array of {author, rating, text, date} objects.
    """
    config.ensure_dirs()
    new = 0
    for path in sorted(config.REVIEWS_INBOX.glob("*.json")):
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                raise ValueError("expected a JSON array of review objects")
        except (ValueError, OSError) as exc:
            log.warning("could not parse %s: %s", path.name, exc)
            continue
        with db.tx() as conn:
            new += _store_reviews(conn, [e for e in entries if isinstance(e, dict)])
    return new


def poll_reviews() -> dict:
    """Daily poll: Places API (if configured) + the manual-export inbox."""
    inbox_new = ingest_inbox()
    if not config.GOOGLE_PLACES_API_KEY or not config.GOOGLE_PLACE_ID:
        db.set_setting("reviews_last_status",
                       f"inbox only ({inbox_new} new) — set GOOGLE_PLACES_API_KEY and"
                       " EAST_NEURO_PLACE_ID for daily Places polling")
        db.set_setting("reviews_last_run", db.now_iso())
        return {"inbox_new": inbox_new, "places": "not configured"}
    try:
        entries = _fetch_place_reviews()
        with db.tx() as conn:
            places_new = _store_reviews(conn, entries)
        db.set_setting("reviews_last_status",
                       f"ok: {places_new} new from Places, {inbox_new} from inbox")
        db.set_setting("reviews_last_run", db.now_iso())
        return {"inbox_new": inbox_new, "places_new": places_new}
    except Exception as exc:  # noqa: BLE001 - surfaced on the reviews page
        db.set_setting("reviews_last_status", f"error: {safe_err(exc)[:300]}")
        db.set_setting("reviews_last_run", db.now_iso())
        return {"inbox_new": inbox_new, "error": safe_err(exc)}


# --- review cycles --------------------------------------------------------------

def _themes_prompt(count: int) -> str:
    return (
        f"You are drafting a patient-feedback review for a neurology practice as RACP"
        f" Category 2 CPD evidence. The payload contains {count} Google reviews"
        " (author, rating, text, date) accumulated since the last review cycle.\n"
        "Return a JSON result with keys:\n"
        "  themes_md: markdown with sections — Praise themes, Complaint/suggestion"
        " themes, Overall picture (each theme grounded in the actual review texts,"
        " quoting short snippets where helpful)\n"
        "  actions: array of 0-6 short concrete practice-improvement actions drawn"
        " strictly from the complaint/suggestion themes (e.g. booking friction,"
        " communication, waiting times). Empty array if nothing actionable.\n"
        "STRICT RULES: use only the supplied reviews — never invent feedback,"
        " patients, or events; if reviews are overwhelmingly positive, say so"
        " rather than manufacturing complaints."
    )


def maybe_open_cycle(force: bool = False) -> dict:
    """Open a review cycle if one is due (quarterly by default) and reviews exist."""
    months = 3
    try:
        months = max(1, int(db.get_setting("review_cycle_months", "3")))
    except ValueError:
        pass
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        unfinished = conn.execute(
            "SELECT id, status FROM review_cycles WHERE status != 'signed_off'"
            " ORDER BY id DESC LIMIT 1").fetchone()
        if unfinished:
            if unfinished["status"] == "drafting":
                pending = conn.execute(
                    "SELECT 1 FROM jobs WHERE kind = 'review_themes'"
                    " AND status = 'pending'").fetchone()
                if not pending:
                    # The drafting job failed: re-queue it from the cycle's own
                    # reviews so the cycle cannot wedge in 'drafting' forever.
                    cycle_reviews = conn.execute(
                        "SELECT * FROM reviews WHERE cycle_id = ?"
                        " ORDER BY review_date, id", (unfinished["id"],)).fetchall()
                    payload = {
                        "cycle_id": unfinished["id"],
                        "reviews": [
                            {"author": r["author"], "rating": r["rating"],
                             "text": r["text"], "date": r["review_date"]}
                            for r in cycle_reviews
                        ],
                    }
                    conn.execute(
                        "INSERT INTO jobs (kind, engine, payload, prompt, created_at)"
                        " VALUES ('review_themes', 'claude', ?, ?, ?)",
                        (json.dumps(payload), _themes_prompt(len(cycle_reviews)),
                         db.now_iso()),
                    )
                    return {"status": "requeued", "cycle_id": unfinished["id"]}
            return {"status": "cycle_in_progress", "cycle_id": unfinished["id"]}
        if not force:
            last = conn.execute(
                "SELECT opened_at FROM review_cycles ORDER BY id DESC LIMIT 1").fetchone()
            if last:
                opened = datetime.fromisoformat(last["opened_at"])
                now = datetime.now(config.TZ)
                elapsed = (now.year - opened.year) * 12 + now.month - opened.month
                if elapsed < months:
                    return {"status": "not_due", "months_elapsed": elapsed}
        pending = conn.execute(
            "SELECT * FROM reviews WHERE cycle_id IS NULL ORDER BY review_date, id"
        ).fetchall()
        if not pending:
            return {"status": "no_new_reviews"}
        cur = conn.execute(
            "INSERT INTO review_cycles (opened_at, status) VALUES (?, 'drafting')",
            (db.now_iso(),),
        )
        cycle_id = cur.lastrowid
        conn.executemany("UPDATE reviews SET cycle_id = ? WHERE id = ?",
                         [(cycle_id, r["id"]) for r in pending])
        payload = {
            "cycle_id": cycle_id,
            "reviews": [
                {"author": r["author"], "rating": r["rating"], "text": r["text"],
                 "date": r["review_date"]}
                for r in pending
            ],
        }
        conn.execute(
            "INSERT INTO jobs (kind, engine, payload, prompt, created_at)"
            " VALUES ('review_themes', 'claude', ?, ?, ?)",
            (json.dumps(payload), _themes_prompt(len(pending)), db.now_iso()),
        )
    return {"status": "opened", "cycle_id": cycle_id, "review_count": len(pending)}


def apply_themes_result(conn, job, result: dict) -> dict:
    themes_md = str(result.get("themes_md", "")).strip()
    if not themes_md:
        return {"error": "result must include a non-empty 'themes_md'"}
    payload = json.loads(job["payload"] or "{}")
    cycle_id = payload.get("cycle_id")
    cycle = conn.execute("SELECT * FROM review_cycles WHERE id = ?", (cycle_id,)).fetchone()
    if cycle is None:
        return {"error": f"review cycle {cycle_id} not found"}
    now = db.now_iso()
    if cycle["status"] == "signed_off":
        conn.execute(
            "UPDATE jobs SET status = 'done', result = ?, completed_at = ? WHERE id = ?",
            (json.dumps({"skipped": "cycle already signed off"}), now, job["id"]),
        )
        return {"job": job["id"], "status": "done", "skipped": "cycle already signed off"}
    conn.execute("UPDATE review_cycles SET themes_draft = ?, status = 'review' WHERE id = ?",
                 (themes_md[:60000], cycle_id))
    actions = result.get("actions") or []
    created_actions = 0
    if isinstance(actions, list):
        for action in actions[:6]:
            action = str(action).strip()
            if not action:
                continue
            conn.execute(
                "INSERT INTO practice_outputs (kind, title, source_kind, source_id,"
                " status, created_at) VALUES ('improvement_action', ?, 'review_cycle',"
                " ?, 'idea', ?)",
                (action[:300], cycle_id, now),
            )
            created_actions += 1
    conn.execute(
        "UPDATE jobs SET status = 'done', result = ?, completed_at = ? WHERE id = ?",
        (json.dumps({"cycle_id": cycle_id, "actions": created_actions}), now, job["id"]),
    )
    return {"job": job["id"], "status": "done", "cycle_id": cycle_id,
            "improvement_actions": created_actions}


def sign_off_cycle(cycle_id: int, final_text: str, reflection: str, minutes: int) -> int | None:
    """Dashboard sign-off: confirmed Cat 2 activity + feedback-summary evidence."""
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cycle = conn.execute("SELECT * FROM review_cycles WHERE id = ?", (cycle_id,)).fetchone()
        if cycle is None or cycle["status"] == "signed_off":
            return None
        reviews = conn.execute(
            "SELECT * FROM reviews WHERE cycle_id = ? ORDER BY review_date, id",
            (cycle_id,)).fetchall()
        ratings = [r["rating"] for r in reviews if r["rating"] is not None]
        done_actions = conn.execute(
            "SELECT title FROM practice_outputs WHERE kind = 'improvement_action'"
            " AND status = 'done' ORDER BY updated_at DESC LIMIT 10").fetchall()
        now = db.now_iso()
        period = f"{cycle['opened_at'][:10]}"
        cur = conn.execute(
            "INSERT INTO activities (date, category, activity_type, title, description,"
            " reflection, minutes, source_module, status, created_at, confirmed_at)"
            " VALUES (?, 2, 'patient_feedback', ?, ?, ?, ?, 'reviews', 'confirmed', ?, ?)",
            (db.today_iso(),
             f"Patient feedback review — cycle opened {period}",
             f"Review of {len(reviews)} patient reviews; themes, actions and"
             " reflection in the attached feedback summary.",
             reflection, minutes, now, now),
        )
        activity_id = cur.lastrowid
        doc = config.EVIDENCE_DIR / f"feedback-review-{period}-a{activity_id}.md"
        lines = [f"# Patient feedback review — cycle opened {period}", "",
                 f"Reviews considered: {len(reviews)}"]
        if ratings:
            lines.append(f"Mean rating: {sum(ratings) / len(ratings):.1f} / 5"
                         f" ({len(ratings)} rated)")
        lines += ["", "## Themes", "", final_text.strip(), "", "## Reflection", "",
                  reflection.strip() or "(recorded on the activity)"]
        if done_actions:
            lines += ["", "## Actions completed from previous cycles", ""]
            lines += [f"- {a['title']}" for a in done_actions]
        db.add_generated_evidence(conn, activity_id, doc,
                                  "\n".join(lines).encode("utf-8"))
        conn.execute(
            "UPDATE review_cycles SET final_text = ?, status = 'signed_off',"
            " activity_id = ?, signed_off_at = ? WHERE id = ?",
            (final_text[:60000], activity_id, now, cycle_id),
        )
    return activity_id
