"""POST /api/signups - the coming-soon page's email capture. No
email-validator dependency (not already in requirements.txt): a plain
regex is enough to catch typos/garbage without adding a new package to a
deploy that is supposed to be minimal.

Rate-limited in-process (10/min, 30/day per IP) because this endpoint now
triggers an outbound email per request (see email_resend.py) - without a
cap, a flood of fake submissions would burn through Resend's free-tier
quota and spam real strangers' inboxes. In-memory is fine here: a single
uvicorn process, no multi-worker/replica setup (see docker-compose.yml).
"""
import re
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from db_signups import save_signup
from email_resend import send_signup_confirmation
from models import SignupRequest

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_MINUTE_LIMIT = 10
_DAY_LIMIT = 30
_hits: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    # Caddy's reverse_proxy sets this automatically; uvicorn isn't started
    # with --proxy-headers, so request.client.host would otherwise be
    # Caddy's own container IP on every request, not the real visitor.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _hits.get(ip, []) if now - t < 86400]
    per_minute = sum(1 for t in hits if now - t < 60)
    limited = per_minute >= _MINUTE_LIMIT or len(hits) >= _DAY_LIMIT
    if not limited:
        hits.append(now)
    _hits[ip] = hits
    return limited


@router.post("/api/signups")
async def create_signup(body: SignupRequest, request: Request, background_tasks: BackgroundTasks):
    if _rate_limited(_client_ip(request)):
        raise HTTPException(status_code=429, detail={"error": "rate_limited"})

    email = body.email.strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail={"error": "invalid_email"})

    await save_signup(email)
    background_tasks.add_task(send_signup_confirmation, email)
    return {"ok": True}
