"""In-process rate limits for the public API. Same approach as master's
signups route: a single uvicorn process, so in-memory counters are enough
(no Redis). Three layers:

- every /api request: a loose per-IP cap against scrapers and floods
- /api/search: a tighter per-IP cap, since each search is a paid LLM +
  embedding call
- /api/search: a global daily cap across everyone, a cost circuit breaker
  in case the per-IP limit is dodged (rotating IPs or a spoofed header)
"""
import os
import time
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse

GENERAL_PER_MINUTE = int(os.environ.get("RATE_GENERAL_PER_MINUTE", "120"))
SEARCH_PER_MINUTE = int(os.environ.get("RATE_SEARCH_PER_MINUTE", "12"))
SEARCH_PER_DAY = int(os.environ.get("RATE_SEARCH_PER_DAY", "300"))
SEARCH_GLOBAL_PER_DAY = int(os.environ.get("RATE_SEARCH_GLOBAL_PER_DAY", "5000"))


def client_ip(request: Request) -> str:
    # Behind Cloudflare's proxy every request reaches Caddy from a Cloudflare
    # edge IP, so the visitor's real address is CF-Connecting-IP. Without
    # Cloudflare, Caddy's X-Forwarded-For has it (uvicorn isn't started with
    # --proxy-headers, so request.client is Caddy itself).
    for header in ("cf-connecting-ip", "x-forwarded-for"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class Window:
    """Timestamps of recent hits per key, trimmed to the longest window."""

    def __init__(self, horizon_seconds: float):
        self.horizon = horizon_seconds
        self.hits: dict[str, deque] = {}
        self.last_sweep = time.time()

    def count(self, key: str, seconds: float, now: float) -> int:
        q = self.hits.get(key)
        if not q:
            return 0
        while q and now - q[0] > self.horizon:
            q.popleft()
        return sum(1 for t in q if now - t < seconds)

    def add(self, key: str, now: float) -> None:
        self.hits.setdefault(key, deque()).append(now)
        if now - self.last_sweep > 600:  # drop idle IPs so memory stays flat
            self.hits = {k: q for k, q in self.hits.items() if q and now - q[-1] < self.horizon}
            self.last_sweep = now


_general = Window(60)
_search = Window(86400)


def _too_many(message: str, retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limited", "message": message},
        headers={"Retry-After": str(retry_after)},
    )


async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path == "/api/health":
        return await call_next(request)
    ip, now = client_ip(request), time.time()

    if _general.count(ip, 60, now) >= GENERAL_PER_MINUTE:
        return _too_many("Too many requests. Please slow down.", 60)
    _general.add(ip, now)

    if path == "/api/search" and request.method == "POST":
        if _search.count("*", 86400, now) >= SEARCH_GLOBAL_PER_DAY:
            return _too_many("AI search has hit today's limit. Please try again tomorrow.", 3600)
        if _search.count(ip, 60, now) >= SEARCH_PER_MINUTE:
            return _too_many("You're searching very fast. Please wait a minute.", 60)
        if _search.count(ip, 86400, now) >= SEARCH_PER_DAY:
            return _too_many("You've reached today's search limit. Please come back tomorrow.", 3600)
        _search.add(ip, now)
        _search.add("*", now)

    return await call_next(request)
