"""In-memory rate limiting for the expensive routes (POST /api/search makes
two OpenAI calls per request — extraction + embedding — so an unthrottled
loop against it is a direct bill, not just load).

In-memory on purpose: the API runs as a single uvicorn process on one EC2
host, so a process-local dict is the whole truth. If it's ever scaled to
multiple workers/hosts this needs to move to Redis or similar — each
process would otherwise enforce its own separate copy of every limit.

Three limits, all env-configurable (see server/.env.example):
  - per-IP per-minute  — stops a script hammering the endpoint
  - per-IP per-day     — stops one visitor slowly draining the budget
  - global per-day     — a hard spend ceiling no matter how many IPs are
                         involved (distributed abuse, a bot farm, a bug in
                         our own frontend retry loop)
"""
import ipaddress
import os
import time
from collections import deque

from fastapi import HTTPException, Request

PER_MINUTE = int(os.environ.get("SEARCH_RATE_PER_MINUTE", "10"))
PER_DAY = int(os.environ.get("SEARCH_RATE_PER_DAY", "300"))
GLOBAL_PER_DAY = int(os.environ.get("SEARCH_GLOBAL_DAILY_CAP", "5000"))

_MINUTE = 60.0
_DAY = 86400.0
# Bounds memory: an attacker rotating IPs can't grow the dict forever —
# stale entries are swept once it passes this size.
_MAX_TRACKED_IPS = 50_000

_hits: dict[str, deque] = {}
_global_hits: deque = deque()


def client_ip(request: Request) -> str:
    """The real visitor IP, not the reverse proxy's.

    In production Caddy sits in front of the API, so the TCP peer is Caddy
    (loopback, or the Docker bridge gateway when the API runs in a
    container) and the visitor is in X-Forwarded-For. Without this every
    visitor would share Caddy's one IP and the per-IP limit would throttle
    the whole site at once.

    X-Forwarded-For is only trusted when the peer is a private/loopback
    address — i.e. our own proxy. A direct hit on port 4000 from the public
    internet has a public peer IP, so a spoofed header from it is ignored.
    The rightmost entry is the one our proxy itself appended (the address it
    actually saw); anything left of it is client-supplied and spoofable.
    """
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        try:
            peer_addr = ipaddress.ip_address(peer)
            if peer_addr.is_private or peer_addr.is_loopback:
                return forwarded.split(",")[-1].strip() or peer
        except ValueError:
            pass
    return peer


def _prune(window: deque, now: float, span: float) -> None:
    while window and now - window[0] > span:
        window.popleft()


def _sweep(now: float) -> None:
    for ip in [ip for ip, w in _hits.items() if not w or now - w[-1] > _DAY]:
        del _hits[ip]


def _reject(retry_after: float, scope: str) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={"error": "rate_limited", "scope": scope},
        headers={"Retry-After": str(max(1, int(retry_after)))},
    )


async def limit_search(request: Request) -> None:
    """FastAPI dependency — attach with Depends(limit_search)."""
    now = time.monotonic()

    _prune(_global_hits, now, _DAY)
    if len(_global_hits) >= GLOBAL_PER_DAY:
        raise _reject(_DAY - (now - _global_hits[0]), "global")

    ip = client_ip(request)
    window = _hits.get(ip)
    if window is None:
        if len(_hits) >= _MAX_TRACKED_IPS:
            _sweep(now)
        window = _hits[ip] = deque()
    _prune(window, now, _DAY)

    if len(window) >= PER_DAY:
        raise _reject(_DAY - (now - window[0]), "daily")
    recent = sum(1 for t in reversed(window) if now - t <= _MINUTE) if len(window) >= PER_MINUTE else 0
    if recent >= PER_MINUTE:
        oldest_in_minute = window[-PER_MINUTE]
        raise _reject(_MINUTE - (now - oldest_in_minute), "minute")

    window.append(now)
    _global_hits.append(now)
