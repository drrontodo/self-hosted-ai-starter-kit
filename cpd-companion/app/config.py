import os
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(os.environ.get("CPD_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "cpd.db"
EVIDENCE_DIR = DATA_DIR / "evidence"
BACKUP_DIR = DATA_DIR / "backups"

API_KEY = os.environ.get("CPD_API_KEY", "")
DASHBOARD_PASSWORD = os.environ.get("CPD_DASHBOARD_PASSWORD", "")
SECRET_KEY = os.environ.get("CPD_SECRET_KEY", "")
TZ = ZoneInfo(os.environ.get("CPD_TZ", "Australia/Sydney"))
SCHEDULER_ENABLED = os.environ.get("CPD_SCHEDULER", "1") == "1"

ANNUAL_TARGET_MIN = 50 * 60
CAT1_MIN = int(12.5 * 60)
CAT23_COMBINED_MIN = 25 * 60
CAT2_FLOOR_MIN = 5 * 60
CAT3_FLOOR_MIN = 5 * 60

ACTIVITY_TYPES = [
    "reading",
    "research_dev",
    "patient_feedback",
    "peer_discussion",
    "audit",
    "meeting",
    "teaching",
    "incident_review",
    "other",
]

TAG_OPTIONS = ["cultural_safety", "ethics"]


def ensure_dirs() -> None:
    for d in (DATA_DIR, EVIDENCE_DIR, BACKUP_DIR):
        d.mkdir(parents=True, exist_ok=True)
