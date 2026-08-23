import os
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(os.environ.get("CPD_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "cpd.db"
EVIDENCE_DIR = DATA_DIR / "evidence"
BACKUP_DIR = DATA_DIR / "backups"

API_KEY = os.environ.get("CPD_API_KEY", "")
NCBI_API_KEY = os.environ.get("CPD_NCBI_API_KEY", "")
GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
GOOGLE_PLACE_ID = os.environ.get("EAST_NEURO_PLACE_ID", "")
PBS_API_BASE = os.environ.get("CPD_PBS_API_BASE", "https://data-api.health.gov.au/pbs/api/v3")
PBS_SUBSCRIPTION_KEY = os.environ.get("CPD_PBS_SUBSCRIPTION_KEY", "")
DASHBOARD_PASSWORD = os.environ.get("CPD_DASHBOARD_PASSWORD", "")
DASHBOARD_PASSWORD_HASH = os.environ.get("CPD_DASHBOARD_PASSWORD_HASH", "")
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
    "pdp",
    "other",
]

TAG_OPTIONS = ["cultural_safety", "ethics"]


# Meeting recordings (M7): how each meeting type maps onto the RACP framework.
MEETING_TYPES = {
    "annual_conversation": {"label": "Annual Conversation", "category": 2, "activity_type": "meeting"},
    "peer_discussion": {"label": "Peer case discussion", "category": 2, "activity_type": "peer_discussion"},
    "mm_meeting": {"label": "Morbidity & mortality / outcomes meeting", "category": 3, "activity_type": "incident_review"},
    "journal_club": {"label": "Journal club", "category": 1, "activity_type": "meeting"},
    "other": {"label": "Other professional meeting", "category": 1, "activity_type": "meeting"},
}

AUDIO_DIR = DATA_DIR / "audio"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
INBOX_DIR = DATA_DIR / "inbox"
MEDICOLEGAL_INBOX = INBOX_DIR / "medicolegal"
REVIEWS_INBOX = INBOX_DIR / "reviews"


def ensure_dirs() -> None:
    for d in (DATA_DIR, EVIDENCE_DIR, BACKUP_DIR, AUDIO_DIR, TRANSCRIPT_DIR,
              MEDICOLEGAL_INBOX, REVIEWS_INBOX):
        d.mkdir(parents=True, exist_ok=True)
