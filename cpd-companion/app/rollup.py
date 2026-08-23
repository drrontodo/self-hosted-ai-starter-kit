"""Weekly rollup: turn raw Claude Code session reports into draft Cat 1 activities."""

import json
from datetime import date, datetime

from . import config, db


def _local_day(value: str | None, fallback: str) -> str:
    """Resolve a stored timestamp to a local (config.TZ) calendar date string."""
    for candidate in (value, fallback):
        if not candidate:
            continue
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(config.TZ)
        return parsed.date().isoformat()
    return db.today_iso()


def rollup_sessions() -> list[int]:
    """Group un-rolled, CPD-relevant session reports into draft activities.

    Grouping is per (project, calendar year, ISO week) so hours never bleed
    across a CPD-year boundary and a delayed rollup still yields weekly-sized
    entries. Drafts require sign-off on the dashboard before they count.
    """
    created: list[int] = []
    with db.tx() as conn:
        # Take the write lock before reading so concurrent rollups (scheduler +
        # manual trigger) cannot both see the same un-rolled rows.
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT * FROM sessions_log WHERE rolled_up = 0 AND cpd_relevant = 1"
            " ORDER BY project, created_at"
        ).fetchall()
        groups: dict[tuple, list] = {}
        days: dict[int, str] = {}
        for r in rows:
            day = _local_day(r["started_at"], r["created_at"])
            days[r["id"]] = day
            d = date.fromisoformat(day)
            key = (r["project"], d.year, d.isocalendar()[1])
            groups.setdefault(key, []).append(r)

        for (project, _year, _week), sessions in groups.items():
            minutes = sum(s["active_minutes"] for s in sessions)
            if minutes <= 0:
                conn.executemany(
                    "UPDATE sessions_log SET rolled_up = 1 WHERE id = ?",
                    [(s["id"],) for s in sessions],
                )
                continue
            topics: list[str] = []
            lines: list[str] = []
            for s in sessions:
                for t in json.loads(s["topics"] or "[]"):
                    if t not in topics:
                        topics.append(t)
                lines.append(f"- {days[s['id']]}: {s['summary']} ({s['active_minutes']} min)")
            first_day = min(days[s["id"]] for s in sessions)
            last_day = max(days[s["id"]] for s in sessions)
            period = first_day if first_day == last_day else f"{first_day} to {last_day}"
            description = (
                f"Research/development sessions on '{project}' ({period}).\n"
                f"Topics: {', '.join(topics) or 'n/a'}\n" + "\n".join(lines)
            )
            cur = conn.execute(
                "INSERT INTO activities (date, category, activity_type, title, description, minutes,"
                " source_module, status, created_at)"
                " VALUES (?, 1, 'research_dev', ?, ?, ?, 'sessions', 'draft', ?)",
                (
                    last_day,
                    f"Medical research & development — {project}",
                    description,
                    minutes,
                    db.now_iso(),
                ),
            )
            activity_id = cur.lastrowid
            conn.executemany(
                "UPDATE sessions_log SET rolled_up = 1 WHERE id = ?",
                [(s["id"],) for s in sessions],
            )
            created.append(activity_id)
    return created
