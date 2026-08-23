import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, rollup
from ..auth import require_api_key

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


class SessionReport(BaseModel):
    project: str = Field(min_length=1, max_length=200)
    started_at: str | None = None
    ended_at: str | None = None
    active_minutes: int = Field(ge=0, le=24 * 60)
    topics: list[str] = []
    summary: str = Field(min_length=1, max_length=4000)
    artefacts: list[str] = []
    cpd_relevant: bool = True


class ActivityIn(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    category: int = Field(ge=1, le=3)
    activity_type: str
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    reflection: str = ""
    minutes: int = Field(ge=0, le=24 * 60)
    source_module: str = "api"
    status: str = "draft"
    tags: list[str] = []


class ActivityPatch(BaseModel):
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    category: int | None = Field(default=None, ge=1, le=3)
    activity_type: str | None = None
    title: str | None = None
    description: str | None = None
    reflection: str | None = None
    minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    status: str | None = None
    tags: list[str] | None = None


@router.post("/sessions", status_code=201)
def create_session_report(report: SessionReport):
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO sessions_log (project, started_at, ended_at, active_minutes, topics,"
            " summary, artefacts, cpd_relevant, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report.project,
                report.started_at,
                report.ended_at,
                report.active_minutes,
                json.dumps(report.topics),
                report.summary,
                json.dumps(report.artefacts),
                1 if report.cpd_relevant else 0,
                db.now_iso(),
            ),
        )
        new_id = cur.lastrowid
    return {"id": new_id, "status": "logged"}


@router.post("/rollup")
def trigger_rollup():
    created = rollup.rollup_sessions()
    return {"created_draft_activity_ids": created}


@router.get("/activities")
def list_activities(year: int | None = None, category: int | None = None, status: str | None = None):
    query = "SELECT * FROM activities WHERE status != 'discarded'"
    params: list = []
    if year is not None:
        query += " AND date BETWEEN ? AND ?"
        params += [f"{year}-01-01", f"{year}-12-31"]
    if category is not None:
        query += " AND category = ?"
        params.append(category)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY date DESC, id DESC"
    with db.tx() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@router.post("/activities", status_code=201)
def create_activity(activity: ActivityIn):
    if activity.activity_type not in config.ACTIVITY_TYPES:
        raise HTTPException(422, f"activity_type must be one of {config.ACTIVITY_TYPES}")
    if activity.status not in ("draft", "confirmed"):
        raise HTTPException(422, "status must be draft or confirmed")
    now = db.now_iso()
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO activities (date, category, activity_type, title, description, reflection,"
            " minutes, source_module, status, tags, created_at, confirmed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                activity.date,
                activity.category,
                activity.activity_type,
                activity.title,
                activity.description,
                activity.reflection,
                activity.minutes,
                activity.source_module,
                activity.status,
                ",".join(activity.tags),
                now,
                now if activity.status == "confirmed" else None,
            ),
        )
        new_id = cur.lastrowid
    return {"id": new_id}


@router.patch("/activities/{activity_id}")
def patch_activity(activity_id: int, patch: ActivityPatch):
    fields = patch.model_dump(exclude_none=True)
    if "tags" in fields:
        fields["tags"] = ",".join(fields["tags"])
    if "status" in fields and fields["status"] not in ("draft", "confirmed", "discarded"):
        raise HTTPException(422, "invalid status")
    if not fields:
        raise HTTPException(422, "no fields to update")
    with db.tx() as conn:
        row = conn.execute("SELECT id, status FROM activities WHERE id = ?", (activity_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "activity not found")
        if fields.get("status") == "confirmed" and row["status"] != "confirmed":
            fields["confirmed_at"] = db.now_iso()
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE activities SET {sets} WHERE id = ?", (*fields.values(), activity_id))
    return {"id": activity_id, "updated": sorted(fields)}


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int):
    with db.tx() as conn:
        deleted = conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,)).rowcount
    if deleted == 0:
        raise HTTPException(404, "activity not found")
    return {"id": activity_id, "deleted": True}


@router.get("/progress")
def get_progress(year: int | None = None):
    from datetime import datetime

    return db.progress(year or datetime.now(config.TZ).year)
