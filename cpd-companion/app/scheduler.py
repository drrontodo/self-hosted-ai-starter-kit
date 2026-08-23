import logging
import sqlite3
import zipfile
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db, rollup

log = logging.getLogger("cpd.scheduler")

_scheduler: BackgroundScheduler | None = None


def backup() -> str:
    """Consistent nightly snapshot of the database plus evidence files; keep 30."""
    config.ensure_dirs()
    stamp = datetime.now(config.TZ).strftime("%Y%m%d-%H%M%S")
    out = config.BACKUP_DIR / f"cpd-backup-{stamp}.zip"
    snapshot = config.BACKUP_DIR / f"cpd-snapshot-{stamp}.db"
    src = db.connect()
    try:
        dest = sqlite3.connect(snapshot)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(snapshot, "cpd.db")
        for f in sorted(config.EVIDENCE_DIR.rglob("*")):
            if f.is_file():
                zf.write(f, f"evidence/{f.relative_to(config.EVIDENCE_DIR)}")
    snapshot.unlink(missing_ok=True)
    backups = sorted(config.BACKUP_DIR.glob("cpd-backup-*.zip"))
    for old in backups[:-30]:
        old.unlink()
    log.info("backup written: %s", out)
    return str(out)


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone=str(config.TZ))
    _scheduler.add_job(rollup.rollup_sessions, "cron", day_of_week="mon", hour=6, minute=0,
                       id="weekly_rollup")
    _scheduler.add_job(backup, "cron", hour=2, minute=30, id="nightly_backup")
    _scheduler.start()


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
