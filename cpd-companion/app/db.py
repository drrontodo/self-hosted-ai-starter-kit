import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    category INTEGER NOT NULL CHECK (category IN (1, 2, 3)),
    activity_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    reflection TEXT DEFAULT '',
    minutes INTEGER NOT NULL CHECK (minutes >= 0),
    source_module TEXT DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed', 'discarded')),
    tags TEXT DEFAULT '',
    external_ref TEXT UNIQUE,
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    path_or_url TEXT NOT NULL,
    sha256 TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions_log (
    id INTEGER PRIMARY KEY,
    project TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    active_minutes INTEGER NOT NULL CHECK (active_minutes >= 0),
    topics TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    artefacts TEXT DEFAULT '',
    cpd_relevant INTEGER NOT NULL DEFAULT 1,
    rolled_up INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    engine TEXT NOT NULL DEFAULT 'claude' CHECK (engine IN ('claude', 'whisper')),
    payload TEXT DEFAULT '',
    prompt TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'failed')),
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'rss' CHECK (kind IN ('rss', 'pubmed')),
    url TEXT NOT NULL UNIQUE,
    section TEXT DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_polled_at TEXT,
    last_status TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY,
    feed_id INTEGER REFERENCES feeds(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    guid TEXT NOT NULL UNIQUE,
    link TEXT DEFAULT '',
    title TEXT NOT NULL,
    summary TEXT DEFAULT '',
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    section TEXT DEFAULT '',
    llm_digest TEXT,
    digest_flags TEXT DEFAULT '',
    read_at TEXT,
    read_seconds INTEGER NOT NULL DEFAULT 0,
    rolled_up INTEGER NOT NULL DEFAULT 0,
    flagged_opportunity INTEGER NOT NULL DEFAULT 0,
    flagged_newsletter INTEGER NOT NULL DEFAULT 0,
    starred INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    taken_at TEXT NOT NULL,
    content TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS practice_outputs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    source_kind TEXT DEFAULT '',
    source_id INTEGER,
    target_site TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'idea'
        CHECK (status IN ('idea', 'draft', 'published', 'done', 'dismissed')),
    path TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    needs_refresh INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL UNIQUE,
    checklist TEXT NOT NULL DEFAULT '[]',
    metrics TEXT NOT NULL DEFAULT '{}',
    draft_text TEXT DEFAULT '',
    final_text TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'drafting'
        CHECK (status IN ('drafting', 'review', 'signed_off')),
    activity_id INTEGER,
    created_at TEXT NOT NULL,
    signed_off_at TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    detected_at TEXT NOT NULL,
    report_date TEXT,
    instruction_date TEXT,
    turnaround_days INTEGER,
    word_count INTEGER NOT NULL DEFAULT 0,
    sections TEXT NOT NULL DEFAULT '{}',
    parse_error TEXT DEFAULT '',
    audit_id INTEGER REFERENCES audits(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_activities_status_date ON activities(status, date);
CREATE INDEX IF NOT EXISTS idx_sessions_rollup ON sessions_log(rolled_up, cpd_relevant);
CREATE INDEX IF NOT EXISTS idx_jobs_status_engine ON jobs(status, engine);
CREATE INDEX IF NOT EXISTS idx_news_unread ON news_items(read_at, rolled_up);
CREATE INDEX IF NOT EXISTS idx_news_undigested ON news_items(llm_digest) WHERE llm_digest IS NULL;
CREATE INDEX IF NOT EXISTS idx_snapshots_source ON source_snapshots(source, id);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx():
    """Connection that commits on success, rolls back on error, and always closes."""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    config.ensure_dirs()
    with tx() as conn:
        conn.executescript(SCHEMA)


def now_iso() -> str:
    return datetime.now(config.TZ).isoformat(timespec="seconds")


def today_iso() -> str:
    return datetime.now(config.TZ).date().isoformat()


def get_setting(key: str, default: str = "") -> str:
    with tx() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def progress(year: int) -> dict:
    """Confirmed minutes per category for a CPD (calendar) year."""
    lo, hi = f"{year}-01-01", f"{year}-12-31"
    with tx() as conn:
        rows = conn.execute(
            "SELECT category, COALESCE(SUM(minutes), 0) AS m FROM activities "
            "WHERE status = 'confirmed' AND date BETWEEN ? AND ? GROUP BY category",
            (lo, hi),
        ).fetchall()
    per_cat = {1: 0, 2: 0, 3: 0}
    for r in rows:
        per_cat[r["category"]] = r["m"]
    total = sum(per_cat.values())
    return {
        "year": year,
        "total_min": total,
        "cat1_min": per_cat[1],
        "cat2_min": per_cat[2],
        "cat3_min": per_cat[3],
        "cat23_min": per_cat[2] + per_cat[3],
        "targets": {
            "total_min": config.ANNUAL_TARGET_MIN,
            "cat1_min": config.CAT1_MIN,
            "cat23_min": config.CAT23_COMBINED_MIN,
            "cat2_floor_min": config.CAT2_FLOOR_MIN,
            "cat3_floor_min": config.CAT3_FLOOR_MIN,
        },
    }
