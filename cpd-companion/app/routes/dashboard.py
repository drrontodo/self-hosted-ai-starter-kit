import csv
import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .. import auth, config, db

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _minutes_to_hours(minutes: int) -> str:
    return f"{minutes / 60:.1f}"


templates.env.filters["hours"] = _minutes_to_hours


def _guard(request: Request) -> RedirectResponse | None:
    if not auth.is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return None


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login(request: Request, password: str = Form(...)):
    if not auth.check_password(password):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Wrong password (or CPD_DASHBOARD_PASSWORD not set)."},
            status_code=401,
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE, auth.session_token(),
        max_age=auth.SESSION_MAX_AGE, httponly=True, samesite="lax",
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE)
    return response


@router.get("/")
def home(request: Request):
    if r := _guard(request):
        return r
    now = datetime.now(config.TZ)
    year = now.year
    prog = db.progress(year)
    day_of_year = now.timetuple().tm_yday
    pace_min = int(config.ANNUAL_TARGET_MIN * day_of_year / 365)
    with db.tx() as conn:
        drafts = conn.execute(
            "SELECT COUNT(*) AS n FROM activities WHERE status = 'draft'"
        ).fetchone()["n"]
        recent = conn.execute(
            "SELECT * FROM activities WHERE status = 'confirmed' ORDER BY date DESC, id DESC LIMIT 8"
        ).fetchall()
    return templates.TemplateResponse(request, "home.html", {
        "prog": prog, "year": year, "drafts": drafts, "recent": recent, "pace_min": pace_min,
    })


@router.get("/log")
def log_page(request: Request, year: int | None = None, category: int | None = None):
    if r := _guard(request):
        return r
    year = year or datetime.now(config.TZ).year
    query = "SELECT * FROM activities WHERE status = 'confirmed' AND date BETWEEN ? AND ?"
    params: list = [f"{year}-01-01", f"{year}-12-31"]
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY date DESC, id DESC"
    with db.tx() as conn:
        rows = conn.execute(query, params).fetchall()
    return templates.TemplateResponse(request, "log.html", {
        "rows": rows, "year": year, "category": category,
        "activity_types": config.ACTIVITY_TYPES, "tag_options": config.TAG_OPTIONS,
        "today": db.today_iso(),
    })


@router.post("/log/add")
def log_add(
    request: Request,
    date: str = Form(...),
    category: int = Form(...),
    activity_type: str = Form(...),
    title: str = Form(...),
    minutes: int = Form(...),
    description: str = Form(""),
    reflection: str = Form(""),
    tags: list[str] = Form([]),
):
    if r := _guard(request):
        return r
    now = db.now_iso()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO activities (date, category, activity_type, title, description, reflection,"
            " minutes, source_module, status, tags, created_at, confirmed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', 'confirmed', ?, ?, ?)",
            (date, category, activity_type, title, description, reflection, minutes,
             ",".join(tags), now, now),
        )
    return RedirectResponse("/log", status_code=303)


@router.get("/inbox")
def inbox(request: Request):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT * FROM activities WHERE status = 'draft' ORDER BY date DESC, id DESC"
        ).fetchall()
    return templates.TemplateResponse(request, "inbox.html", {"rows": rows})


@router.post("/inbox/{activity_id}/confirm")
def inbox_confirm(request: Request, activity_id: int, minutes: int = Form(...), reflection: str = Form("")):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        conn.execute(
            "UPDATE activities SET status = 'confirmed', minutes = ?, reflection = ?, confirmed_at = ?"
            " WHERE id = ? AND status = 'draft'",
            (minutes, reflection, db.now_iso(), activity_id),
        )
    return RedirectResponse("/inbox", status_code=303)


@router.post("/inbox/{activity_id}/discard")
def inbox_discard(request: Request, activity_id: int):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        conn.execute(
            "UPDATE activities SET status = 'discarded' WHERE id = ? AND status = 'draft'",
            (activity_id,),
        )
    return RedirectResponse("/inbox", status_code=303)


@router.get("/activity/{activity_id}")
def activity_edit_form(request: Request, activity_id: int):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
    if row is None:
        return RedirectResponse("/log", status_code=303)
    return templates.TemplateResponse(request, "activity_edit.html", {
        "a": row, "activity_types": config.ACTIVITY_TYPES, "tag_options": config.TAG_OPTIONS,
    })


@router.post("/activity/{activity_id}")
def activity_edit(
    request: Request,
    activity_id: int,
    date: str = Form(...),
    category: int = Form(...),
    activity_type: str = Form(...),
    title: str = Form(...),
    minutes: int = Form(...),
    description: str = Form(""),
    reflection: str = Form(""),
    tags: list[str] = Form([]),
):
    if r := _guard(request):
        return r
    with db.tx() as conn:
        conn.execute(
            "UPDATE activities SET date = ?, category = ?, activity_type = ?, title = ?,"
            " minutes = ?, description = ?, reflection = ?, tags = ? WHERE id = ?",
            (date, category, activity_type, title, minutes, description, reflection,
             ",".join(tags), activity_id),
        )
    return RedirectResponse("/log", status_code=303)


@router.get("/export/mycpd.csv")
def export_csv(request: Request, year: int | None = None):
    if r := _guard(request):
        return r
    year = year or datetime.now(config.TZ).year
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT * FROM activities WHERE status = 'confirmed' AND date BETWEEN ? AND ?"
            " ORDER BY date, id",
            (f"{year}-01-01", f"{year}-12-31"),
        ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Category", "Activity type", "Title", "Hours", "Description",
                     "Reflection", "Tags"])
    for a in rows:
        writer.writerow([
            a["date"], a["category"], a["activity_type"], a["title"],
            f"{a['minutes'] / 60:.2f}", a["description"], a["reflection"], a["tags"],
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=mycpd-{year}.csv"},
    )
