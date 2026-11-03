"""Rate limits for the public API. Three layers:

- every /api request: a loose per-IP cap against scrapers and floods
- /api/search: a tighter per-IP cap, since each search is a paid LLM +
  embedding call
- /api/search: a global daily cap across everyone, a cost circuit breaker
  in case the per-IP limit is dodged (rotating IPs or a spoofed header)

The API runs as several worker processes (Dockerfile, WEB_WORKERS), so the
search limits count in Postgres (api_rate_counts), shared by every worker:
one small read and one upsert per search, nothing next to the LLM call.
Minute windows are calendar minutes and day windows are UTC days.

The general cap stays in each worker's memory: a database write on every
request would cost more than it protects, and with N workers the
effective cap is up to N x the setting, which is fine for a flood guard.
"""
import os
import random
import time
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse

from db import get_pool

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

SEARCH_LIMITS = [  # (key prefix, window seconds, limit, message, retry-after)
    ("*", 86400, SEARCH_GLOBAL_PER_DAY, "AI search has hit today's limit. Please try again tomorrow.", 3600),
    ("ip", 60, SEARCH_PER_MINUTE, "You're searching very fast. Please wait a minute.", 60),
    ("ip", 86400, SEARCH_PER_DAY, "You've reached today's search limit. Please come back tomorrow.", 3600),
]


async def init_rate_limits() -> None:
    pool = await get_pool()
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS api_rate_counts (
            key    TEXT NOT NULL,          -- e.g. search:60:203.0.113.5, search:86400:*
            bucket TIMESTAMPTZ NOT NULL,   -- start of the minute or UTC day
            hits   INT NOT NULL,
            PRIMARY KEY (key, bucket)
        )""")


async def _search_limited(ip: str, now: float):
    """The message and retry-after of the first search limit reached, or
    None (and the search is counted against every limit)."""
    rows = [(f"search:{window}:{ip if who == 'ip' else '*'}", window, limit, msg, retry)
            for who, window, limit, msg, retry in SEARCH_LIMITS]
    keys = [r[0] for r in rows]
    buckets = [int(now // r[1] * r[1]) for r in rows]
    pool = await get_pool()
    counts = dict(await pool.fetch(
        """SELECT c.key, c.hits FROM api_rate_counts c
           JOIN unnest($1::text[], $2::bigint[]) AS w(key, b) ON c.key = w.key AND c.bucket = to_timestamp(w.b)""",
        keys, buckets))
    for key, _, limit, msg, retry in rows:
        if counts.get(key, 0) >= limit:
            return msg, retry
    await pool.execute(
        """INSERT INTO api_rate_counts (key, bucket, hits)
           SELECT key, to_timestamp(b), 1 FROM unnest($1::text[], $2::bigint[]) AS w(key, b)
           ON CONFLICT (key, bucket) DO UPDATE SET hits = api_rate_counts.hits + 1""",
        keys, buckets)
    if random.random() < 0.01:  # old windows are never read again
        await pool.execute("DELETE FROM api_rate_counts WHERE bucket < now() - interval '2 days'")
    return None


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
        limited = await _search_limited(ip, now)
        if limited:
            return _too_many(*limited)

    return await call_next(request)
