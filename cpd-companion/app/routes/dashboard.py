import calendar
import csv
import datetime as dt
import io
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from .. import auth, config, db, growth, medicolegal, news, pdp, pipeline, reviews

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _minutes_to_hours(minutes: int) -> str:
    return f"{minutes / 60:.1f}"


templates.env.filters["hours"] = _minutes_to_hours

MANDATORY_TOGGLES = ("pdp", "annual_conversation")


def _guard(request: Request) -> Response | None:
    if not auth.is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    if request.method == "POST":
        # Same-origin check for cookie-authenticated writes (defence in depth on
        # top of SameSite=Lax, for when the app is exposed beyond the LAN).
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            from urllib.parse import urlparse

            if urlparse(origin).netloc not in ("", request.url.netloc):
                return Response("cross-origin request rejected", status_code=403)
    return None


def _csv_cell(value) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login(request: Request, password: str = Form(...)):
    if auth.login_throttled():
        return templates.TemplateResponse(
            request, "login.html", {"error": "Too many attempts — wait a minute and retry."},
            status_code=429,
        )
    if not auth.check_password(password):
        auth.record_login_failure()
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Wrong password (or no dashboard password configured)."},
            status_code=401,
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE, auth.session_token(),
        max_age=auth.SESSION_MAX_AGE, httponly=True, samesite="lax",
        secure=config.COOKIE_SECURE,
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE)
    return response


def _mandatory_summary(year: int) -> dict:
    lo, hi = f"{year}-01-01", f"{year}-12-31"
    with db.tx() as conn:
        cultural = conn.execute(
            "SELECT COUNT(*) AS n FROM activities WHERE status = 'confirmed'"
            " AND date BETWEEN ? AND ? AND tags LIKE '%cultural_safety%'", (lo, hi),
        ).fetchone()["n"]
        ethics = conn.execute(
            "SELECT COUNT(*) AS n FROM activities WHERE status = 'confirmed'"
            " AND date BETWEEN ? AND ? AND tags LIKE '%ethics%'", (lo, hi),
        ).fetchone()["n"]
        totals = conn.execute(
            "SELECT COUNT(*) AS total, SUM(EXISTS(SELECT 1 FROM evidence e"
            " WHERE e.activity_id = a.id)) AS with_evidence"
            " FROM activities a WHERE a.status = 'confirmed' AND a.date BETWEEN ? AND ?",
            (lo, hi),
        ).fetchone()
    total = totals["total"] or 0
    with_evidence = totals["with_evidence"] or 0
    # When a mandatory counter is behind, suggest recent digest items the
    # nightly digest flagged as plausibly qualifying (SPEC M6).
    suggestions: dict[str, list] = {"cultural_safety": [], "ethics": []}
    if cultural < 2 or ethics < 2:
        with db.tx() as conn:
            flagged = conn.execute(
                "SELECT id, title, link, digest_flags FROM news_items"
                " WHERE digest_flags != '' ORDER BY id DESC LIMIT 30").fetchall()
        for item in flagged:
            for flag in ("cultural_safety", "ethics"):
                if flag in item["digest_flags"] and len(suggestions[flag]) < 3:
                    suggestions[flag].append(item)
    return {
        "cultural_safety": cultural,
        "ethics": ethics,
        "pdp_done": db.get_setting(f"pdp_done_{year}") == "1",
        "annual_conversation_done": db.get_setting(f"annual_conversation_done_{year}") == "1",
        "evidence_total": total,
        "evidence_with": with_evidence,
        "evidence_pct": round(100 * with_evidence / total) if total else 0,
        "suggestions": suggestions,
    }


@router.get("/")
def home(request: Request, year: int | None = None):
    if r := _guard(request):
        return r
    now = dt.datetime.now(config.TZ)
    current_year = now.year
    year = year or current_year
    prog = db.progress(year)
    if year == current_year:
        days_in_year = 366 if calendar.isleap(year) else 365
        pace_min = min(
            config.ANNUAL_TARGET_MIN,
            int(config.ANNUAL_TARGET_MIN * now.timetuple().tm_yday / days_in_year),
        )
    else:
        pace_min = config.ANNUAL_TARGET_MIN
    with db.tx() as conn:
        drafts = conn.execute(
            "SELECT COUNT(*) AS n FROM activities WHERE status = 'draft'"
        ).fetchone()["n"]
        recent = conn.execute(
            "SELECT * FROM activities WHERE status = 'confirmed' AND date BETWEEN ? AND ?"
            " ORDER BY date DESC, id DESC LIMIT 8",
            (f"{year}-01-01", f"{year}-12-31"),
        ).fetchall()
    return templates.TemplateResponse(request, "home.html", {
        "prog": prog, "year": year, "current_year": current_year, "drafts": drafts,
        "recent": recent, "pace_min": pace_min, "mandatory": _mandatory_summary(year),
    })


@router.post("/mandatory/{item}/toggle")
def mandatory_toggle(request: Request, item: str, year: int = Form(...)):
    if r := _guard(request):
        return r
    if item in MANDATORY_TOGGLES:
        key = f"{item}_done_{year}"
        db.set_setting(key, "0" if db.get_setting(key) == "1" else "1")
    return RedirectResponse(f"/?year={year}", status_code=303)


@router.get("/log")
def log_page(request: Request, year: int | None = None, category: int | None = None):
    if r := _guard(request):
        return r
    current_year = dt.datetime.now(config.TZ).year
    year = year or current_year
    query = "SELECT * FROM activities WHERE status = 'confirmed' AND date BETWEEN ? AND ?"
    params: list = [f"{year}-01-01", f"{year}-12-31"]
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY date DESC, id DESC"
    with db.tx() as conn:
        rows = conn.execute(query, params).fetchall()
    return templates.TemplateResponse(request, "log.html", {
        "rows": rows, "year": year, "current_year": current_year, "category": category,
        "activity_types": config.ACTIVITY_TYPES, "tag_options": config.TAG_OPTIONS,
        "today": db.today_iso(),
    })


@router.post("/log/add")
def log_add(
    request: Request,
    date: dt.date = Form(...),
    category: int = Form(..., ge=1, le=3),
    activity_type: str = Form(...),
    title: str = Form(..., max_length=300),
    minutes: int = Form(..., ge=1, le=1440),
    description: str = Form("", max_length=20000),
    reflection: str = Form("", max_length=20000),
    tags: list[str] = Form([]),
):
    if r := _guard(request):
        return r
    if activity_type not in config.ACTIVITY_TYPES:
        return RedirectResponse("/log", status_code=303)
    now = db.now_iso()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO activities (date, category, activity_type, title, description, reflection,"
            " minutes, source_module, status, tags, created_at, confirmed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', 'confirmed', ?, ?, ?)",
            (date.isoformat(), category, activity_type, title, description, reflection, minutes,
             ",".join(t for t in tags if t in config.TAG_OPTIONS), now, now),
        )
    return RedirectResponse(f"/log?year={date.year}", status_code=303)


@router.get("/inbox")
def inbox(request: Request, stale: int | None = None):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT * FROM activities WHERE status = 'draft' ORDER BY date DESC, id DESC"
        ).fetchall()
    return templates.TemplateResponse(request, "inbox.html", {"rows": rows, "stale": stale})


@router.post("/inbox/{activity_id}/confirm")
def inbox_confirm(
    request: Request,
    activity_id: int,
    minutes: int = Form(..., ge=1, le=1440),
    reflection: str = Form("", max_length=20000),
):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        changed = conn.execute(
            "UPDATE activities SET status = 'confirmed', minutes = ?, reflection = ?, confirmed_at = ?"
            " WHERE id = ? AND status = 'draft'",
            (minutes, reflection, db.now_iso(), activity_id),
        ).rowcount
    if changed == 0:
        return RedirectResponse(f"/inbox?stale={activity_id}", status_code=303)
    return RedirectResponse("/inbox", status_code=303)


@router.post("/inbox/{activity_id}/discard")
def inbox_discard(request: Request, activity_id: int):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        changed = conn.execute(
            "UPDATE activities SET status = 'discarded' WHERE id = ? AND status = 'draft'",
            (activity_id,),
        ).rowcount
    if changed == 0:
        return RedirectResponse(f"/inbox?stale={activity_id}", status_code=303)
    return RedirectResponse("/inbox", status_code=303)


@router.get("/activity/{activity_id}")
def activity_edit_form(request: Request, activity_id: int):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
        evidence = conn.execute(
            "SELECT * FROM evidence WHERE activity_id = ? ORDER BY id", (activity_id,)
        ).fetchall()
    if row is None:
        return RedirectResponse("/log", status_code=303)
    return templates.TemplateResponse(request, "activity_edit.html", {
        "a": row, "activity_types": config.ACTIVITY_TYPES, "tag_options": config.TAG_OPTIONS,
        "evidence": evidence,
    })


@router.post("/activity/{activity_id}")
def activity_edit(
    request: Request,
    activity_id: int,
    date: dt.date = Form(...),
    category: int = Form(..., ge=1, le=3),
    activity_type: str = Form(...),
    title: str = Form(..., max_length=300),
    minutes: int = Form(..., ge=0, le=1440),
    description: str = Form("", max_length=20000),
    reflection: str = Form("", max_length=20000),
    tags: list[str] = Form([]),
):
    if r := _guard(request):
        return r
    if activity_type not in config.ACTIVITY_TYPES:
        return RedirectResponse(f"/activity/{activity_id}", status_code=303)
    with db.tx() as conn:
        conn.execute(
            "UPDATE activities SET date = ?, category = ?, activity_type = ?, title = ?,"
            " minutes = ?, description = ?, reflection = ?, tags = ? WHERE id = ?",
            (date.isoformat(), category, activity_type, title, minutes, description, reflection,
             ",".join(t for t in tags if t in config.TAG_OPTIONS), activity_id),
        )
    return RedirectResponse(f"/log?year={date.year}", status_code=303)


@router.get("/meetings")
def meetings(request: Request):
    if r := _guard(request):
        return r
    return templates.TemplateResponse(request, "meetings.html", {
        "meeting_types": config.MEETING_TYPES,
        "queue": pipeline.meeting_queue_overview(),
        "today": db.today_iso(),
    })


@router.post("/meetings/upload")
async def meetings_upload(
    request: Request,
    audio: UploadFile = File(...),
    meeting_type: str = Form(...),
    date: dt.date = Form(...),
    participants: str = Form("", max_length=500),
    duration_minutes: int = Form(..., ge=1, le=600),
    notes: str = Form("", max_length=2000),
    consent: str = Form(...),
):
    if r := _guard(request):
        return r
    if meeting_type not in config.MEETING_TYPES or consent != "yes":
        return RedirectResponse("/meetings", status_code=303)
    audio_bytes = await audio.read()
    if audio_bytes:
        pipeline.create_meeting(
            audio_filename=audio.filename or "recording",
            audio_bytes=audio_bytes,
            meeting_type=meeting_type,
            date=date.isoformat(),
            participants=participants,
            duration_minutes=duration_minutes,
            notes=notes,
        )
    return RedirectResponse("/meetings", status_code=303)


@router.get("/digest")
def digest_page(request: Request):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        unread = conn.execute(
            "SELECT * FROM news_items WHERE read_at IS NULL"
            " ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC LIMIT 200"
        ).fetchall()
        recent_read = conn.execute(
            "SELECT * FROM news_items WHERE read_at IS NOT NULL"
            " ORDER BY read_at DESC LIMIT 20"
        ).fetchall()
    sections: dict[str, list] = {}
    for item in unread:
        key = item["section"] if item["section"] in news.SECTIONS else "General"
        sections.setdefault(key, []).append(item)
    ordered = [(s, sections[s]) for s in news.SECTIONS if s in sections]
    return templates.TemplateResponse(request, "digest.html", {
        "sections": ordered, "unread_count": len(unread), "recent_read": recent_read,
        "overview_md": db.get_setting("digest_overview_md"),
        "overview_date": db.get_setting("digest_overview_date"),
    })


@router.post("/digest/{item_id}/read")
def digest_mark_read(request: Request, item_id: int, seconds: int = Form(0, ge=0)):
    if r := _guard(request):
        return r
    news.mark_read(item_id, seconds)
    return RedirectResponse("/digest", status_code=303)


@router.post("/digest/{item_id}/action/{action}")
def digest_item_action(request: Request, item_id: int, action: str):
    if r := _guard(request):
        return r
    if action == "info_sheet":
        growth.request_info_sheet(item_id)
    elif action in ("opportunity", "newsletter"):
        news.item_action(item_id, action)
    return RedirectResponse("/digest", status_code=303)


@router.get("/feeds")
def feeds_page(request: Request):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        feeds = conn.execute("SELECT * FROM feeds ORDER BY kind, id").fetchall()
        undigested = conn.execute(
            "SELECT COUNT(*) AS n FROM news_items WHERE llm_digest IS NULL"
        ).fetchone()["n"]
    return templates.TemplateResponse(request, "feeds.html", {
        "feeds": feeds, "undigested": undigested,
        "pbs_status": db.get_setting("pbs_last_status", "never run"),
        "pbs_run": db.get_setting("pbs_last_run"),
        "stroke_status": db.get_setting("stroke_last_status", "never run"),
        "stroke_run": db.get_setting("stroke_last_run"),
    })


@router.post("/feeds/add")
def feeds_add(
    request: Request,
    name: str = Form(..., max_length=120),
    kind: str = Form(...),
    url: str = Form(..., max_length=1000),
    section: str = Form("", max_length=60),
):
    if r := _guard(request):
        return r
    if kind in ("rss", "pubmed") and name.strip() and url.strip():
        with db.tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO feeds (name, kind, url, section, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (name.strip(), kind, url.strip(),
                 section if section in news.SECTIONS else "", db.now_iso()),
            )
    return RedirectResponse("/feeds", status_code=303)


@router.post("/feeds/{feed_id}/toggle")
def feeds_toggle(request: Request, feed_id: int):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        conn.execute("UPDATE feeds SET enabled = 1 - enabled WHERE id = ?", (feed_id,))
    return RedirectResponse("/feeds", status_code=303)


@router.post("/feeds/{feed_id}/delete")
def feeds_delete(request: Request, feed_id: int):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    return RedirectResponse("/feeds", status_code=303)


@router.post("/feeds/poll")
def feeds_poll(request: Request):
    if r := _guard(request):
        return r
    news.poll_all_feeds()
    return RedirectResponse("/feeds", status_code=303)


@router.post("/feeds/pbs")
def feeds_pbs(request: Request):
    if r := _guard(request):
        return r
    news.pbs_monthly_diff()
    return RedirectResponse("/feeds", status_code=303)


@router.post("/feeds/stroke")
def feeds_stroke(request: Request):
    if r := _guard(request):
        return r
    news.stroke_guidelines_diff()
    return RedirectResponse("/feeds", status_code=303)


@router.post("/feeds/digest")
def feeds_queue_digest(request: Request):
    if r := _guard(request):
        return r
    news.queue_digest_job()
    return RedirectResponse("/feeds", status_code=303)


@router.get("/audits")
def audits_page(request: Request):
    if r := _guard(request):
        return r
    import json as json_mod

    with db.tx() as conn:
        recent_reports = conn.execute(
            "SELECT * FROM reports ORDER BY id DESC LIMIT 15").fetchall()
        unassigned = conn.execute(
            "SELECT COUNT(*) AS n FROM reports WHERE audit_id IS NULL").fetchone()["n"]
    checklist = medicolegal.get_checklist()
    return templates.TemplateResponse(request, "audits.html", {
        "trend": medicolegal.trend_rows(), "checklist": checklist,
        "recent_reports": recent_reports, "unassigned": unassigned,
        "prev_period": medicolegal.previous_month(),
        "report_sections": {r["id"]: json_mod.loads(r["sections"] or "{}")
                            for r in recent_reports},
    })


@router.post("/audits/scan")
def audits_scan(request: Request):
    if r := _guard(request):
        return r
    medicolegal.scan_inbox()
    return RedirectResponse("/audits", status_code=303)


@router.post("/audits/run")
def audits_run(request: Request, period: str = Form("")):
    if r := _guard(request):
        return r
    period = period.strip()
    if period and not re.fullmatch(r"\d{4}-\d{2}", period):
        return RedirectResponse("/audits", status_code=303)
    medicolegal.ensure_monthly_audit(period or None)
    return RedirectResponse("/audits", status_code=303)


@router.get("/audits/{audit_id}")
def audit_detail(request: Request, audit_id: int):
    if r := _guard(request):
        return r
    import json as json_mod

    with db.tx() as conn:
        audit = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
        if audit is None:
            return RedirectResponse("/audits", status_code=303)
        reports = conn.execute(
            "SELECT * FROM reports WHERE audit_id = ? ORDER BY id", (audit_id,)).fetchall()
    checklist = json_mod.loads(audit["checklist"] or "[]") or medicolegal.get_checklist()
    return templates.TemplateResponse(request, "audit_detail.html", {
        "audit": audit, "reports": reports, "checklist": checklist,
        "metrics": json_mod.loads(audit["metrics"] or "{}"),
        "report_sections": {r["id"]: json_mod.loads(r["sections"] or "{}")
                            for r in reports},
    })


@router.post("/audits/{audit_id}/signoff")
def audit_signoff(
    request: Request,
    audit_id: int,
    final_text: str = Form(..., max_length=60000),
    minutes: int = Form(..., ge=1, le=1440),
):
    if r := _guard(request):
        return r
    if not final_text.strip():
        return RedirectResponse(f"/audits/{audit_id}", status_code=303)
    medicolegal.sign_off(audit_id, final_text, minutes)
    return RedirectResponse("/audits", status_code=303)


@router.get("/library")
def library_page(request: Request, q: str = ""):
    if r := _guard(request):
        return r
    q = q[:200]
    with db.tx() as conn:
        drafts = conn.execute(
            "SELECT s.*, r.filename AS source_filename FROM response_snippets s"
            " LEFT JOIN reports r ON r.id = s.source_report_id"
            " WHERE s.status = 'draft' ORDER BY s.id LIMIT 40").fetchall()
        counts = {row["extract_status"]: row["n"] for row in conn.execute(
            "SELECT extract_status, COUNT(*) AS n FROM reports"
            " WHERE parse_error = '' GROUP BY extract_status")}
        approved_total = conn.execute(
            "SELECT COUNT(*) AS n FROM response_snippets WHERE status = 'approved'"
        ).fetchone()["n"]
    return templates.TemplateResponse(request, "library.html", {
        "q": q, "drafts": drafts,
        "approved": medicolegal.search_snippets(q),
        "counts": counts, "approved_total": approved_total,
        "batch": db.get_setting("report_extract_batch",
                                str(medicolegal.DEFAULT_EXTRACT_BATCH)),
    })


@router.post("/library/queue")
def library_queue(request: Request, batch: int = Form(0, ge=0, le=50)):
    if r := _guard(request):
        return r
    if batch:
        db.set_setting("report_extract_batch", str(batch))
    medicolegal.queue_extractions(batch or None)
    return RedirectResponse("/library", status_code=303)


@router.post("/library/{snippet_id}/review")
def library_review(
    request: Request,
    snippet_id: int,
    action: str = Form(...),
    condition: str = Form("", max_length=200),
    topic: str = Form("", max_length=200),
    question: str = Form("", max_length=2000),
    answer: str = Form("", max_length=10000),
):
    if r := _guard(request):
        return r
    medicolegal.review_snippet(snippet_id, action, {
        "condition": condition, "topic": topic, "question": question, "answer": answer,
    })
    return RedirectResponse("/library", status_code=303)


@router.post("/library/log-session")
def library_log_session(request: Request, minutes: int = Form(..., ge=1, le=1440)):
    if r := _guard(request):
        return r
    medicolegal.log_curation_session(minutes)
    return RedirectResponse("/library", status_code=303)


@router.get("/library/export.md")
def library_export_md(request: Request):
    if r := _guard(request):
        return r
    return Response(
        content=medicolegal.library_export_md(), media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=response-library.md"},
    )


@router.get("/library/export.json")
def library_export_json(request: Request):
    if r := _guard(request):
        return r
    rows = medicolegal.search_snippets()
    return [{"condition": s["condition"], "topic": s["topic"],
             "question": s["question"], "answer": s["answer"]} for s in rows]


@router.get("/reviews")
def reviews_page(request: Request):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        cycle = conn.execute(
            "SELECT * FROM review_cycles WHERE status != 'signed_off'"
            " ORDER BY id DESC LIMIT 1").fetchone()
        cycle_reviews = []
        if cycle:
            cycle_reviews = conn.execute(
                "SELECT * FROM reviews WHERE cycle_id = ? ORDER BY review_date, id",
                (cycle["id"],)).fetchall()
        pending_count = conn.execute(
            "SELECT COUNT(*) AS n FROM reviews WHERE cycle_id IS NULL").fetchone()["n"]
        history = conn.execute(
            "SELECT * FROM review_cycles WHERE status = 'signed_off'"
            " ORDER BY id DESC LIMIT 8").fetchall()
        backlog = conn.execute(
            "SELECT * FROM practice_outputs WHERE kind = 'improvement_action'"
            " AND status NOT IN ('done', 'dismissed') ORDER BY id DESC").fetchall()
        done_recent = conn.execute(
            "SELECT * FROM practice_outputs WHERE kind = 'improvement_action'"
            " AND status IN ('done', 'dismissed') ORDER BY updated_at DESC LIMIT 8"
        ).fetchall()
    return templates.TemplateResponse(request, "reviews.html", {
        "cycle": cycle, "cycle_reviews": cycle_reviews, "pending_count": pending_count,
        "history": history, "backlog": backlog, "done_recent": done_recent,
        "poll_status": db.get_setting("reviews_last_status", "never run"),
        "poll_run": db.get_setting("reviews_last_run"),
    })


@router.post("/reviews/poll")
def reviews_poll(request: Request):
    if r := _guard(request):
        return r
    reviews.poll_reviews()
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/open-cycle")
def reviews_open_cycle(request: Request):
    if r := _guard(request):
        return r
    reviews.maybe_open_cycle(force=True)
    return RedirectResponse("/reviews", status_code=303)


@router.post("/reviews/{cycle_id}/signoff")
def reviews_signoff(
    request: Request,
    cycle_id: int,
    final_text: str = Form(..., max_length=60000),
    reflection: str = Form("", max_length=20000),
    minutes: int = Form(..., ge=1, le=1440),
):
    if r := _guard(request):
        return r
    if final_text.strip():
        reviews.sign_off_cycle(cycle_id, final_text, reflection, minutes)
    return RedirectResponse("/reviews", status_code=303)


@router.post("/outputs/{output_id}/status")
def output_set_status(request: Request, output_id: int, status: str = Form(...)):
    if r := _guard(request):
        return r
    if status in ("idea", "draft", "published", "done", "dismissed"):
        with db.tx() as conn:
            conn.execute(
                "UPDATE practice_outputs SET status = ?, updated_at = ? WHERE id = ?",
                (status, db.now_iso(), output_id))
    target = request.headers.get("referer") or "/reviews"
    from urllib.parse import urlparse

    return RedirectResponse(urlparse(target).path or "/reviews", status_code=303)


@router.get("/outputs")
def outputs_page(request: Request):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        flagged_newsletter = conn.execute(
            "SELECT COUNT(*) AS n FROM news_items WHERE flagged_newsletter = 1"
        ).fetchone()["n"]
    return templates.TemplateResponse(request, "outputs.html", {
        "grouped": growth.outputs_by_kind(),
        "flagged_newsletter": flagged_newsletter,
        "kind_labels": {
            "info_sheet": "Patient info sheets",
            "opportunity_brief": "Service opportunity briefs",
            "newsletter": "Referrer newsletters",
            "improvement_action": "Practice improvement actions",
        },
    })


@router.post("/outputs/run/{job_kind}")
def outputs_run(request: Request, job_kind: str):
    if r := _guard(request):
        return r
    if job_kind == "scan":
        growth.quarterly_opportunity_scan()
    elif job_kind == "newsletter":
        growth.quarterly_referrer_newsletter()
    elif job_kind == "refresh-check":
        growth.flag_refreshes()
    return RedirectResponse("/outputs", status_code=303)


@router.post("/outputs/{output_id}/refresh-clear")
def output_refresh_clear(request: Request, output_id: int):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        conn.execute(
            "UPDATE practice_outputs SET needs_refresh = 0, updated_at = ? WHERE id = ?",
            (db.now_iso(), output_id))
    return RedirectResponse("/outputs", status_code=303)


@router.get("/outputs/{output_id}/download")
def output_download(request: Request, output_id: int):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM practice_outputs WHERE id = ?",
                           (output_id,)).fetchone()
    if row is None or not row["path"]:
        return RedirectResponse("/outputs", status_code=303)
    path = Path(row["path"]).resolve()
    if not path.is_file() or not path.is_relative_to(config.DATA_DIR.resolve()):
        return Response("output file not found", status_code=404)
    from fastapi.responses import FileResponse

    return FileResponse(path, filename=path.name)


@router.get("/pdp")
def pdp_page(request: Request, year: int | None = None):
    if r := _guard(request):
        return r
    year = year or dt.datetime.now(config.TZ).year
    row = pdp.get_or_create(year)
    with db.tx() as conn:
        drafting = conn.execute(
            "SELECT 1 FROM jobs WHERE kind = 'pdp_draft' AND status = 'pending'"
        ).fetchone() is not None
    return templates.TemplateResponse(request, "pdp.html", {
        "p": row, "year": year, "current_year": dt.datetime.now(config.TZ).year,
        "drafting": drafting,
    })


@router.post("/pdp/{year}/save")
async def pdp_save(request: Request, year: int):
    if r := _guard(request):
        return r
    form = await request.form()
    pdp.save_form(year, {k: form.get(k, "") for k in pdp.FORM_FIELDS})
    if form.get("queue_draft"):
        pdp.queue_draft(year)
    return RedirectResponse(f"/pdp?year={year}", status_code=303)


@router.post("/pdp/{year}/complete")
def pdp_complete(
    request: Request,
    year: int,
    final_md: str = Form(..., max_length=60000),
    minutes: int = Form(..., ge=1, le=1440),
):
    if r := _guard(request):
        return r
    if final_md.strip():
        pdp.complete(year, final_md, minutes)
    return RedirectResponse(f"/pdp?year={year}", status_code=303)


@router.post("/activity/{activity_id}/evidence")
async def evidence_upload(request: Request, activity_id: int,
                          upload: UploadFile = File(...)):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        activity = conn.execute("SELECT id FROM activities WHERE id = ?",
                                (activity_id,)).fetchone()
    if activity is None:
        return RedirectResponse("/log", status_code=303)
    data = await upload.read()
    if data:
        import hashlib
        import re as re_mod

        safe = re_mod.sub(r"[^A-Za-z0-9._-]", "_", upload.filename or "evidence")
        path = config.EVIDENCE_DIR / f"a{activity_id}_{safe}"
        # never silently overwrite an existing evidence file
        counter = 1
        while path.exists():
            path = config.EVIDENCE_DIR / f"a{activity_id}_{counter}_{safe}"
            counter += 1
        path.write_bytes(data)
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO evidence (activity_id, kind, path_or_url, sha256, created_at)"
                " VALUES (?, 'file', ?, ?, ?)",
                (activity_id, str(path), hashlib.sha256(data).hexdigest(), db.now_iso()),
            )
    return RedirectResponse(f"/activity/{activity_id}", status_code=303)


@router.get("/evidence/{evidence_id}")
def evidence_download(request: Request, evidence_id: int):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
    if row is None or row["kind"] in ("url", "email_ref"):
        return RedirectResponse("/log", status_code=303)
    path = Path(row["path_or_url"]).resolve()
    if not path.is_file() or not path.is_relative_to(config.DATA_DIR.resolve()):
        return Response("evidence file not found", status_code=404)
    from fastapi.responses import FileResponse

    return FileResponse(path, filename=path.name)


def _confirmed_activities(year: int) -> list:
    with db.tx() as conn:
        return conn.execute(
            "SELECT * FROM activities WHERE status = 'confirmed' AND date BETWEEN ? AND ?"
            " ORDER BY date, id",
            (f"{year}-01-01", f"{year}-12-31"),
        ).fetchall()


def _mycpd_csv(rows) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Category", "Activity type", "Title", "Hours", "Description",
                     "Reflection", "Tags"])
    for a in rows:
        writer.writerow([
            a["date"], a["category"], _csv_cell(a["activity_type"]), _csv_cell(a["title"]),
            f"{a['minutes'] / 60:.2f}", _csv_cell(a["description"]), _csv_cell(a["reflection"]),
            _csv_cell(a["tags"]),
        ])
    return buf.getvalue()


@router.get("/export/mycpd.csv")
def export_csv(request: Request, year: int | None = None):
    if r := _guard(request):
        return r
    year = year or dt.datetime.now(config.TZ).year
    return StreamingResponse(
        iter([_mycpd_csv(_confirmed_activities(year))]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=mycpd-{year}.csv"},
    )


@router.get("/export/audit-bundle/{year}")
def export_audit_bundle(request: Request, year: int):
    """The 30-June audit response, pre-built: one zip with the year's register
    (CSV + readable markdown) and every evidence artefact for its confirmed
    entries."""
    if r := _guard(request):
        return r
    import zipfile

    rows = _confirmed_activities(year)
    with db.tx() as conn:
        evidence_by_activity: dict[int, list] = {}
        for e in conn.execute(
            "SELECT e.* FROM evidence e JOIN activities a ON a.id = e.activity_id"
            " WHERE a.status = 'confirmed' AND a.date BETWEEN ? AND ? ORDER BY e.id",
            (f"{year}-01-01", f"{year}-12-31"),
        ).fetchall():
            evidence_by_activity.setdefault(e["activity_id"], []).append(e)

    prog = db.progress(year)
    md = [f"# CPD register — {year}", "",
          f"Total confirmed: {prog['total_min'] / 60:.1f} h"
          f" (Cat 1: {prog['cat1_min'] / 60:.1f} h, Cat 2: {prog['cat2_min'] / 60:.1f} h,"
          f" Cat 3: {prog['cat3_min'] / 60:.1f} h)", "",
          f"Entries: {len(rows)}. Generated {db.now_iso()}.", ""]
    missing: list[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"register-{year}.csv", _mycpd_csv(rows))
        for a in rows:
            md += [f"## {a['date']} — {a['title']}", "",
                   f"Category {a['category']} · {a['activity_type'].replace('_', ' ')}"
                   f" · {a['minutes'] / 60:.2f} h"
                   + (f" · tags: {a['tags']}" if a["tags"] else ""), ""]
            if a["description"]:
                md += [a["description"], ""]
            if a["reflection"]:
                md += [f"*Reflection:* {a['reflection']}", ""]
            attached = evidence_by_activity.get(a["id"], [])
            if not attached:
                md += ["Evidence: none attached", ""]
                continue
            md.append("Evidence:")
            for e in attached:
                if e["kind"] in ("url", "email_ref"):
                    md.append(f"- {'Email reference' if e['kind'] == 'email_ref' else 'URL'}:"
                              f" {e['path_or_url']}")
                    continue
                path = Path(e["path_or_url"])
                arcname = f"evidence/activity-{a['id']}/{path.name}"
                if path.is_file():
                    zf.write(path, arcname)
                    md.append(f"- {arcname}"
                              + (f" (sha256 {e['sha256'][:16]}…)" if e["sha256"] else ""))
                else:
                    missing.append(arcname)
                    md.append(f"- MISSING FILE: {e['path_or_url']}")
            md.append("")
        if missing:
            md += ["---", "", f"⚠ {len(missing)} evidence file(s) referenced in the"
                   " register could not be found on disk.", ""]
        zf.writestr(f"register-{year}.md", "\n".join(md))
    return Response(
        content=buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition":
                 f"attachment; filename=cpd-audit-bundle-{year}.zip"},
    )
