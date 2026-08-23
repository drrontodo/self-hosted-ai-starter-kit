import logging
import sqlite3
import zipfile
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db, growth, medicolegal, news, reviews, rollup

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


_lock_handle = None


def _acquire_singleton_lock() -> bool:
    """One scheduler across all workers. File lock on POSIX; on native Windows
    (no fcntl) fall back to the in-process guard — run a single process there."""
    global _lock_handle
    try:
        import fcntl
    except ImportError:
        return True
    config.ensure_dirs()
    _lock_handle = open(config.DATA_DIR / ".scheduler.lock", "w")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        _lock_handle.close()
        _lock_handle = None
        return False


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    if not _acquire_singleton_lock():
        log.info("scheduler already running in another worker; skipping")
        return
    _scheduler = BackgroundScheduler(timezone=str(config.TZ))
    _scheduler.add_job(rollup.rollup_sessions, "cron", day_of_week="mon", hour=6, minute=0,
                       id="weekly_rollup")
    _scheduler.add_job(backup, "cron", hour=2, minute=30, id="nightly_backup")
    # M3 news digest: poll feeds daily, then queue the claude digest job so the
    # nightly drain has fresh items; reading rolls up weekly alongside sessions.
    _scheduler.add_job(news.poll_all_feeds, "cron", hour=5, minute=30, id="news_poll")
    _scheduler.add_job(news.queue_digest_job, "cron", hour=5, minute=50, id="news_digest")
    _scheduler.add_job(news.rollup_reading, "cron", day_of_week="mon", hour=6, minute=5,
                       id="reading_rollup")
    _scheduler.add_job(news.pbs_monthly_diff, "cron", day=1, hour=6, minute=10,
                       id="pbs_diff")
    _scheduler.add_job(news.stroke_guidelines_diff, "cron", day=1, hour=6, minute=20,
                       id="stroke_diff")
    # M5 medicolegal: watch the inbox daily; audit the previous month on the 1st.
    _scheduler.add_job(medicolegal.scan_inbox, "cron", hour=5, minute=0,
                       id="medicolegal_scan")
    _scheduler.add_job(medicolegal.ensure_monthly_audit, "cron", day=1, hour=6, minute=30,
                       id="medicolegal_audit")
    # M2 reviews: poll daily; a cycle opens when due (quarterly by default).
    _scheduler.add_job(reviews.poll_reviews, "cron", hour=5, minute=10, id="reviews_poll")
    _scheduler.add_job(reviews.maybe_open_cycle, "cron", day=2, hour=6, minute=40,
                       id="review_cycle")
    # §5 practice growth: quarterly scans/newsletter; weekly refresh check.
    _scheduler.add_job(growth.quarterly_opportunity_scan, "cron", month="1,4,7,10",
                       day=3, hour=6, minute=50, id="opportunity_scan")
    _scheduler.add_job(growth.quarterly_referrer_newsletter, "cron", month="1,4,7,10",
                       day=3, hour=7, minute=0, id="referrer_newsletter")
    _scheduler.add_job(growth.flag_refreshes, "cron", day_of_week="mon", hour=6,
                       minute=15, id="refresh_check")
    _scheduler.start()


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
