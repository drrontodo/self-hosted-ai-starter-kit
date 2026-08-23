"""Weekly rollup: turn raw Claude Code session reports into draft Cat 1 activities."""

import json

from . import db


def rollup_sessions() -> list[int]:
    """Group un-rolled, CPD-relevant session reports by project into draft activities.

    Returns the ids of the created draft activities. Drafts require sign-off on
    the dashboard before they count toward any category total.
    """
    created: list[int] = []
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions_log WHERE rolled_up = 0 AND cpd_relevant = 1 ORDER BY project, created_at"
        ).fetchall()
        by_project: dict[str, list] = {}
        for r in rows:
            by_project.setdefault(r["project"], []).append(r)

        for project, sessions in by_project.items():
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
                day = (s["started_at"] or s["created_at"])[:10]
                lines.append(f"- {day}: {s['summary']} ({s['active_minutes']} min)")
            first_day = min((s["started_at"] or s["created_at"])[:10] for s in sessions)
            last_day = max((s["started_at"] or s["created_at"])[:10] for s in sessions)
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
