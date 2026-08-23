import secrets
import time

from fastapi import Header, HTTPException
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from . import config

SESSION_COOKIE = "cpd_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30

FAILURE_WINDOW = 60.0
FAILURE_LIMIT = 10
_failures: list[float] = []

_signer: TimestampSigner | None = None


def _signing_key() -> str:
    if config.SECRET_KEY:
        return config.SECRET_KEY
    # No configured key: persist a generated one so sessions survive restarts
    # and multiple workers agree on it.
    config.ensure_dirs()
    key_file = config.DATA_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key


def _get_signer() -> TimestampSigner:
    global _signer
    if _signer is None:
        _signer = TimestampSigner(_signing_key())
    return _signer


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not config.API_KEY:
        raise HTTPException(status_code=503, detail="CPD_API_KEY is not configured on the server")
    if not secrets.compare_digest(
        x_api_key.encode("utf-8", "replace"), config.API_KEY.encode("utf-8", "replace")
    ):
        raise HTTPException(status_code=401, detail="Invalid API key")


def login_throttled() -> bool:
    now = time.monotonic()
    while _failures and now - _failures[0] > FAILURE_WINDOW:
        _failures.pop(0)
    return len(_failures) >= FAILURE_LIMIT


def record_login_failure() -> None:
    _failures.append(time.monotonic())


def check_password(password: str) -> bool:
    if config.DASHBOARD_PASSWORD_HASH:
        import bcrypt

        try:
            return bcrypt.checkpw(password.encode(), config.DASHBOARD_PASSWORD_HASH.encode())
        except ValueError:
            return False
    if not config.DASHBOARD_PASSWORD:
        return False
    return secrets.compare_digest(password.encode(), config.DASHBOARD_PASSWORD.encode())


def session_token() -> str:
    return _get_signer().sign(b"ok").decode()


def is_logged_in_token(token: str) -> bool:
    if not token:
        return False
    try:
        _get_signer().unsign(token, max_age=SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def is_logged_in(request) -> bool:
    return is_logged_in_token(request.cookies.get(SESSION_COOKIE, ""))
