import secrets

from fastapi import Header, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from . import config

SESSION_COOKIE = "cpd_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30

# Without CPD_SECRET_KEY, sessions are signed with an ephemeral key and reset
# on restart — fine for a LAN dashboard, set the env var for persistence.
_signer = TimestampSigner(config.SECRET_KEY or secrets.token_hex(32))


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not config.API_KEY:
        raise HTTPException(status_code=503, detail="CPD_API_KEY is not configured on the server")
    if not secrets.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")


def check_password(password: str) -> bool:
    if not config.DASHBOARD_PASSWORD:
        return False
    return secrets.compare_digest(password, config.DASHBOARD_PASSWORD)


def session_token() -> str:
    return _signer.sign(b"ok").decode()


def is_logged_in(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        return False
    try:
        _signer.unsign(token, max_age=SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False
