import json
import sqlite3
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, rollup
from ..auth import require_api_key

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


class SessionReport(BaseModel):
    project: str = Field(min_length=1, max_length=200)
    started_at: dt.datetime | None = None
    ended_at: dt.datetime | None = None
    active_minutes: int = Field(ge=0, le=24 * 60)
    topics: list[str] = Field(default=[], max_length=50)
    summary: str = Field(min_length=1, max_length=4000)
    artefacts: list[str] = Field(default=[], max_length=50)
    cpd_relevant: bool = True


class ActivityIn(BaseModel):
    date: dt.date
    category: int = Field(ge=1, le=3)
    activity_type: str
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=20000)
    reflection: str = Field(default="", max_length=20000)
    minutes: int = Field(ge=0, le=24 * 60)
    source_module: str = "api"
    tags: list[str] = Field(default=[], max_length=10)
    external_ref: str | None = Field(default=None, max_length=300)


class ActivityPatch(BaseModel):
    date: dt.date | None = None
    category: int | None = Field(default=None, ge=1, le=3)
    activity_type: str | None = None
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    reflection: str | None = Field(default=None, max_length=20000)
    minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    status: str | None = None
    tags: list[str] | None = Field(default=None, max_length=10)


@router.post("/sessions", status_code=201)
def create_session_report(report: SessionReport):
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO sessions_log (project, started_at, ended_at, active_minutes, topics,"
            " summary, artefacts, cpd_relevant, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report.project,
                report.started_at.isoformat() if report.started_at else None,
                report.ended_at.isoformat() if report.ended_at else None,
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
    """API callers always create drafts: confirmation happens only through the
    dashboard, so an automated client can never self-certify CPD hours."""
    if activity.activity_type not in config.ACTIVITY_TYPES:
        raise HTTPException(422, f"activity_type must be one of {config.ACTIVITY_TYPES}")
    now = db.now_iso()
    try:
        with db.tx() as conn:
            cur = conn.execute(
                "INSERT INTO activities (date, category, activity_type, title, description,"
                " reflection, minutes, source_module, status, tags, external_ref, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
                (
                    activity.date.isoformat(),
                    activity.category,
                    activity.activity_type,
                    activity.title,
                    activity.description,
                    activity.reflection,
                    activity.minutes,
                    activity.source_module,
                    ",".join(activity.tags),
                    activity.external_ref,
                    now,
                ),
            )
            new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"an activity with external_ref {activity.external_ref!r} already exists")
    return {"id": new_id, "status": "draft"}


@router.patch("/activities/{activity_id}")
def patch_activity(activity_id: int, patch: ActivityPatch):
    fields = patch.model_dump(exclude_none=True)
    if "date" in fields:
        fields["date"] = fields["date"].isoformat()
    if "tags" in fields:
        fields["tags"] = ",".join(fields["tags"])
    if "activity_type" in fields and fields["activity_type"] not in config.ACTIVITY_TYPES:
        raise HTTPException(422, f"activity_type must be one of {config.ACTIVITY_TYPES}")
    if "status" in fields:
        # Only draft -> discarded is allowed over the API; confirming is dashboard-only.
        if fields["status"] != "discarded":
            raise HTTPException(422, "API callers may only set status to 'discarded'")
    if not fields:
        raise HTTPException(422, "no fields to update")
    with db.tx() as conn:
        row = conn.execute("SELECT id, status FROM activities WHERE id = ?", (activity_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "activity not found")
        if row["status"] == "confirmed" and "status" in fields:
            raise HTTPException(422, "confirmed activities can only be changed from the dashboard")
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE activities SET {sets} WHERE id = ?", (*fields.values(), activity_id))
    return {"id": activity_id, "updated": sorted(fields)}


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int):
    """Soft delete: the register keeps a trace, and evidence rows survive."""
    with db.tx() as conn:
        row = conn.execute("SELECT id FROM activities WHERE id = ?", (activity_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "activity not found")
        conn.execute("UPDATE activities SET status = 'discarded' WHERE id = ?", (activity_id,))
    return {"id": activity_id, "discarded": True}


@router.get("/progress")
def get_progress(year: int | None = None):
    return db.progress(year or dt.datetime.now(config.TZ).year)


@router.get("/jobs")
def list_jobs(engine: str | None = None, status: str = "pending"):
    query = "SELECT * FROM jobs WHERE status = ?"
    params: list = [status]
    if engine:
        query += " AND engine = ?"
        params.append(engine)
    query += " ORDER BY id"
    with db.tx() as conn:
        rows = conn.execute(query, params).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "kind": r["kind"], "engine": r["engine"], "status": r["status"],
            "payload": json.loads(r["payload"] or "{}"), "prompt": r["prompt"],
            "created_at": r["created_at"],
        })
    return out


@router.post("/jobs/{job_id}/result")
def post_job_result(job_id: int, result: dict):
    from .. import pipeline

    outcome = pipeline.handle_job_result(job_id, result)
    if "error" in outcome:
        raise HTTPException(422, outcome["error"])
    return outcome


@router.post("/jobs/{job_id}/fail")
def post_job_failure(job_id: int, body: dict):
    with db.tx() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "job not found")
        if row["status"] != "pending":
            raise HTTPException(422, f"job already {row['status']}")
        conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, completed_at = ? WHERE id = ?",
            (str(body.get("error", "unknown"))[:2000], db.now_iso(), job_id),
        )
    return {"job": job_id, "status": "failed"}
