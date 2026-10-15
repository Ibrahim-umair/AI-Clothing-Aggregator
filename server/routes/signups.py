"""POST /api/signups — the coming-soon page's email capture. No
email-validator dependency (not already in requirements.txt): a plain
regex is enough to catch typos/garbage without adding a new package to a
deploy that's supposed to be minimal.
"""
import re

from fastapi import APIRouter, HTTPException

from db_signups import save_signup
from models import SignupRequest

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/api/signups")
async def create_signup(body: SignupRequest):
    email = body.email.strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail={"error": "invalid_email"})
    await save_signup(email)
    return {"ok": True}
