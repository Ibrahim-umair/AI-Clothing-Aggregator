"""Scrape admin API (/api/admin/*), used by the /admin page.

Only mounted when ADMIN_TOKEN is set (see main.py), and every call needs that
token, as the X-Admin-Token header or ?token= (EventSource can't send headers).

Scrapes never run inside this process. A Refresh button adds a scrape_jobs
row; the worker started by `python db/scraper/admin.py` picks it up.
Proxy credentials are never read into a response: only proxy hosts. The
"test ways out" button is the one place this process uses them, in memory,
through db/scraper/egress.py.
"""
import asyncio
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db import get_pool


def require_admin(request: Request, token: str | None = Query(None)):
    expected = os.environ.get("ADMIN_TOKEN", "")
    given = request.headers.get("x-admin-token") or token or ""
    if not expected or not secrets.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail="admin token required")


router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])

STALE_HOURS = 48             # a store not fully scraped for this long is flagged
STALLED_SECONDS = 60         # a running run with no heartbeat for this long is probably dead
BYTES_PER_PRODUCT = 350      # gzipped on the wire (Edenrobe, 2026-11-10); used before a store has a measured run
MONTHLY_MB = float(os.environ.get("WEBSHARE_MONTHLY_MB", "1024"))
STOP_MB = float(os.environ.get("WEBSHARE_STOP_MB", "900"))
PROXIES_FILE = Path(os.environ.get(
    "WEBSHARE_PROXIES_FILE", Path(__file__).resolve().parents[2] / "local-notes" / "webshare_proxies.txt"))

_overview_cache: dict = {"at": 0.0, "data": None}


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _row(r) -> dict:
    return {k: _iso(v) for k, v in dict(r).items()}


def proxy_hosts() -> list[str]:
    """Hosts only, in file order (#0, #1, ...). The file's other fields are credentials."""
    try:
        return [line.split(":")[0] for line in PROXIES_FILE.read_text().split() if line.count(":") >= 3]
    except OSError:
        return []


async def month_proxy_bytes(pool) -> int:
    """Proxy bytes this month: scrape runs plus "test ways out" checks."""
    return await pool.fetchval(
        "SELECT ((SELECT coalesce(sum(bytes_in),0) FROM scrape_runs "
        "         WHERE egress LIKE 'proxy%' AND started_at >= date_trunc('month', now())) + "
        "        (SELECT coalesce(sum(bytes_in),0) FROM egress_checks "
        "         WHERE egress LIKE 'proxy%' AND checked_at >= date_trunc('month', now())))::bigint")


RUN_COLS = """sr.id, sr.brand_id, sr.tier, sr.status, sr.phase, sr.started_at, sr.finished_at, sr.heartbeat_at,
    sr.product_count, sr.fetched_so_far, sr.expected_count, sr.products_new, sr.products_updated,
    sr.products_removed, sr.products_unchanged, sr.removals_held, sr.held_resolved, sr.error_message,
    sr.egress, sr.requests_ok, sr.requests_429, sr.requests_403, sr.requests_other, sr.bytes_in, sr.job_id,
    extract(epoch FROM coalesce(sr.finished_at, now()) - sr.started_at)::int AS seconds,
    extract(epoch FROM now() - sr.heartbeat_at)::int AS heartbeat_age"""


def _run(r) -> dict:
    d = _row(r)
    if d["status"] == "running" and (d["heartbeat_age"] is None or d["heartbeat_age"] > STALLED_SECONDS):
        d["status"] = "stalled"
    return d


@router.get("/overview")
async def overview(fresh: bool = False):
    if not fresh and _overview_cache["data"] and time.time() - _overview_cache["at"] < 20:
        return _overview_cache["data"]
    pool = await get_pool()
    stores = await pool.fetch(
        """WITH prod AS (
               SELECT p.brand_id,
                      count(*) AS active,
                      count(a.product_id) AS in_stock,
                      count(a.product_id) FILTER (WHERE p.ai_meta IS NULL) AS not_enriched
               FROM products p
               LEFT JOIN (SELECT DISTINCT product_id FROM variants WHERE current_available) a
                      ON a.product_id = p.id
               WHERE p.is_active GROUP BY p.brand_id)
           SELECT b.id, b.slug, b.name, b.base_url, b.platform_type::text AS platform,
                  coalesce(prod.active,0) AS active, coalesce(prod.in_stock,0) AS in_stock,
                  coalesce(prod.active,0) - coalesce(prod.in_stock,0) AS out_of_stock,
                  coalesce(prod.not_enriched,0) AS not_enriched
           FROM brands b LEFT JOIN prod ON prod.brand_id = b.id ORDER BY b.name""")
    last = await pool.fetch(
        f"""SELECT DISTINCT ON (sr.brand_id, sr.tier) {RUN_COLS}
            FROM scrape_runs sr ORDER BY sr.brand_id, sr.tier, sr.id DESC""")
    last_ok = await pool.fetch(
        """SELECT DISTINCT ON (brand_id) brand_id, started_at, bytes_in, product_count
           FROM scrape_runs WHERE tier='daily' AND status='completed'
           ORDER BY brand_id, id DESC""")
    measured = await pool.fetch(
        """SELECT DISTINCT ON (brand_id) brand_id, bytes_in, product_count FROM scrape_runs
           WHERE status='completed' AND bytes_in > 0 AND product_count > 0 ORDER BY brand_id, id DESC""")
    jobs = await pool.fetch("SELECT id, brand_id, tier, status, requested_at FROM scrape_jobs "
                            "WHERE status IN ('queued','running')")

    by_store: dict[int, dict] = {}
    for s in stores:
        by_store[s["id"]] = {**dict(s), "last": {}, "last_ok_at": None, "job": None}
    for r in last:
        by_store[r["brand_id"]]["last"][r["tier"]] = _run(r)
    for r in last_ok:
        by_store[r["brand_id"]]["last_ok_at"] = _iso(r["started_at"])
    per_product = {r["brand_id"]: r["bytes_in"] / r["product_count"] for r in measured}
    for j in jobs:
        by_store[j["brand_id"]]["job"] = _row(j)

    now = datetime.now(timezone.utc)
    out = []
    for s in by_store.values():
        ok_at = s["last_ok_at"]
        age_h = (now - datetime.fromisoformat(ok_at)).total_seconds() / 3600 if ok_at else None
        daily = s["last"].get("daily") or {}
        flags = []
        if age_h is None or age_h > STALE_HOURS:
            flags.append("stale")
        if daily.get("status") in ("failed", "stalled"):
            flags.append(daily["status"])
        if (daily.get("removals_held") or 0) > 0 and not daily.get("held_resolved"):
            flags.append("held")
        s["hours_since_ok"] = round(age_h, 1) if age_h is not None else None
        s["flags"] = flags
        s["estimate_mb"] = round(s["active"] * per_product.get(s["id"], BYTES_PER_PRODUCT) / 1e6, 1)
        s["estimate_measured"] = s["id"] in per_product
        out.append(s)

    totals = {k: sum(s[k] for s in out) for k in ("active", "in_stock", "out_of_stock", "not_enriched")}
    data = {"stores": out, "totals": totals, "generated_at": now.isoformat()}
    _overview_cache.update(at=time.time(), data=data)
    return data


@router.get("/runs")
async def runs(brand_id: int | None = None, limit: int = Query(40, le=200)):
    pool = await get_pool()
    rows = await pool.fetch(
        f"""SELECT {RUN_COLS}, b.name AS store FROM scrape_runs sr JOIN brands b ON b.id = sr.brand_id
            WHERE ($1::int IS NULL OR sr.brand_id = $1) ORDER BY sr.id DESC LIMIT $2""", brand_id, limit)
    return {"runs": [_run(r) for r in rows]}


@router.get("/changes")
async def changes(run_id: int | None = None, brand_id: int | None = None, days: int = Query(7, le=90),
                  kind: str | None = None, limit: int = Query(60, le=300), offset: int = 0):
    """The change log: counts by kind, then one page of items with a photo and before/after."""
    pool = await get_pool()
    where = ("(($1::bigint IS NOT NULL AND e.scrape_run_id = $1) OR "
             "($1::bigint IS NULL AND e.created_at > now() - make_interval(days => $3))) "
             "AND ($2::int IS NULL OR p.brand_id = $2)")
    counts = await pool.fetch(
        f"SELECT e.kind, count(*) AS n FROM product_events e JOIN products p ON p.id = e.product_id "
        f"WHERE {where} GROUP BY e.kind ORDER BY n DESC", run_id, brand_id, days)
    items = await pool.fetch(
        f"""SELECT e.id, e.kind, e.before, e.after, e.created_at, e.scrape_run_id, p.id AS product_id,
                   p.title, p.is_active, b.name AS store,
                   (SELECT url FROM product_images i WHERE i.product_id = p.id ORDER BY position LIMIT 1) AS image,
                   (SELECT min(current_price) FROM variants v WHERE v.product_id = p.id) AS price,
                   cb.name AS cat_before, cbp.name AS cat_before_parent,
                   ca.name AS cat_after, cap.name AS cat_after_parent
            FROM product_events e
            JOIN products p ON p.id = e.product_id JOIN brands b ON b.id = p.brand_id
            LEFT JOIN categories cb ON cb.id = (e.before->>'category_id')::int
            LEFT JOIN categories cbp ON cbp.id = cb.parent_id
            LEFT JOIN categories ca ON ca.id = (e.after->>'category_id')::int
            LEFT JOIN categories cap ON cap.id = ca.parent_id
            WHERE {where} AND ($4::text IS NULL OR e.kind = $4)
            ORDER BY e.id DESC LIMIT $5 OFFSET $6""", run_id, brand_id, days, kind, limit, offset)
    out = []
    for r in items:
        d = _row(r)
        d["before"] = json.loads(d["before"]) if d["before"] else None
        d["after"] = json.loads(d["after"]) if d["after"] else None
        d["price"] = float(d["price"]) if d["price"] is not None else None
        out.append(d)
    return {"counts": {r["kind"]: r["n"] for r in counts}, "items": out}


@router.get("/egress")
async def egress():
    """One row per way out: direct plus each Webshare proxy, with how it did recently."""
    pool = await get_pool()
    stats = await pool.fetch(
        """SELECT egress,
                  max(started_at) AS last_used,
                  max(started_at) FILTER (WHERE status='completed' AND requests_ok > 0) AS last_ok,
                  coalesce(sum(requests_ok)    FILTER (WHERE started_at > now() - interval '1 day'),0)::bigint AS ok_24h,
                  coalesce(sum(requests_429)   FILTER (WHERE started_at > now() - interval '1 day'),0)::bigint AS r429_24h,
                  coalesce(sum(requests_403)   FILTER (WHERE started_at > now() - interval '1 day'),0)::bigint AS r403_24h,
                  coalesce(sum(requests_other) FILTER (WHERE started_at > now() - interval '1 day'),0)::bigint AS other_24h,
                  coalesce(sum(bytes_in) FILTER (WHERE started_at >= date_trunc('month', now())),0)::bigint AS bytes_month
           FROM scrape_runs WHERE egress IS NOT NULL GROUP BY egress""")
    last_store = await pool.fetch(
        """SELECT DISTINCT ON (sr.egress) sr.egress, b.name AS store, sr.status, sr.requests_429, sr.requests_403
           FROM scrape_runs sr JOIN brands b ON b.id = sr.brand_id WHERE sr.egress IS NOT NULL
           ORDER BY sr.egress, sr.id DESC""")
    checks = await pool.fetch(
        """SELECT DISTINCT ON (egress, target) egress, target, checked_at, http_status, latency_ms, error
           FROM egress_checks ORDER BY egress, target, checked_at DESC""")
    by = {r["egress"]: _row(r) for r in stats}
    ls = {r["egress"]: _row(r) for r in last_store}
    ck: dict[str, list] = {}
    for c in checks:
        ck.setdefault(c["egress"], []).append(_row(c))

    labels = ["direct"] + [f"proxy ({h})" for h in proxy_hosts()]
    labels += [e for e in by if e not in labels]  # anything seen in runs but no longer in the file
    rows = []
    for i, label in enumerate(labels):
        rows.append({"egress": label, "index": i - 1 if 0 < i <= len(proxy_hosts()) else None,
                     "is_proxy": label.startswith("proxy"), **(by.get(label) or {}),
                     "last_run": ls.get(label), "checks": ck.get(label, [])})
    used = await month_proxy_bytes(pool)
    return {"egress": rows, "usage": {"month_bytes": used, "monthly_mb": MONTHLY_MB, "stop_mb": STOP_MB,
                                      "counted_since": "2026-11-10"}}


class JobIn(BaseModel):
    brand_id: int
    tier: str = "daily"


@router.post("/jobs")
async def create_job(job: JobIn):
    if job.tier not in ("daily", "hourly"):
        raise HTTPException(422, "tier must be daily or hourly")
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            "INSERT INTO scrape_jobs (brand_id, tier) VALUES ($1,$2) RETURNING id, status, requested_at",
            job.brand_id, job.tier)
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "this store already has a refresh queued or running")
    except asyncpg.ForeignKeyViolationError:
        raise HTTPException(404, "no such store")
    _overview_cache["data"] = None
    return _row(row)


class AllJobsIn(BaseModel):
    tier: str = "daily"
    stale_hours: float | None = None   # only stores not refreshed for this long


@router.post("/jobs/all")
async def create_all_jobs(body: AllJobsIn):
    """Queue every store that has no open job, the longest-unrefreshed first."""
    if body.tier not in ("daily", "hourly"):
        raise HTTPException(422, "tier must be daily or hourly")
    pool = await get_pool()
    rows = await pool.fetch(
        """INSERT INTO scrape_jobs (brand_id, tier, batch)
           SELECT b.id, $1, 'all' FROM brands b
           LEFT JOIN LATERAL (SELECT max(started_at) AS t FROM scrape_runs r
                              WHERE r.brand_id = b.id AND r.tier = 'daily' AND r.status = 'completed') l ON true
           WHERE NOT EXISTS (SELECT 1 FROM scrape_jobs j WHERE j.brand_id = b.id
                             AND j.status IN ('queued','running','cancelling'))
             AND ($2::float8 IS NULL OR l.t IS NULL OR l.t < now() - $2::float8 * interval '1 hour')
           ORDER BY l.t NULLS FIRST, b.id
           RETURNING id""", body.tier, body.stale_hours)
    _overview_cache["data"] = None
    return {"queued": len(rows)}


def _egress_module():
    """db/scraper/egress.py: the proxy list and the one-request check. Importable
    only where the repo's db/ folder sits next to server/ (the laptop)."""
    path = str(Path(__file__).resolve().parents[2] / "db" / "scraper")
    if path not in sys.path:
        sys.path.append(path)
    try:
        import egress as mod
    except ImportError:
        return None
    return mod


@router.post("/egress/test")
async def test_egress():
    """One small request per way out per platform (a few KB each), saved to egress_checks."""
    mod = _egress_module()
    if mod is None:
        raise HTTPException(501, "the egress checker (db/scraper/egress.py) is not available here")
    tasks = [(label, url, target) for label, url in mod.all_egress() for target in mod.CHECK_TARGETS]
    sem = asyncio.Semaphore(6)

    async def one(label, url, target):
        async with sem:
            return label, await asyncio.to_thread(mod.check, url, target)

    results = await asyncio.gather(*(one(*t) for t in tasks))
    pool = await get_pool()
    await pool.executemany(
        "INSERT INTO egress_checks (egress, target, http_status, latency_ms, error, bytes_in) "
        "VALUES ($1,$2,$3,$4,$5,$6)",
        [(label, r["target"], r["http_status"], r["latency_ms"], r["error"], r["bytes_in"]) for label, r in results])
    return {"checks": [{"egress": label, **r, "ok": mod.check_ok(r)} for label, r in results]}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int):
    """Queued jobs are dropped; a running one is stopped by the worker at its next check."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "UPDATE scrape_jobs SET status = CASE WHEN status='queued' THEN 'cancelled' ELSE 'cancelling' END "
        "WHERE id=$1 AND status IN ('queued','running') RETURNING id, status", job_id)
    if not row:
        raise HTTPException(404, "no open job with that id")
    _overview_cache["data"] = None
    return _row(row)


class HeldIn(BaseModel):
    action: str  # apply | discard


@router.post("/runs/{run_id}/held")
async def resolve_held(run_id: int, body: HeldIn):
    """Apply or discard removals a partial-looking run held back."""
    if body.action not in ("apply", "discard"):
        raise HTTPException(422, "action must be apply or discard")
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        run = await conn.fetchrow(
            "SELECT id, brand_id, started_at, removals_held, held_resolved FROM scrape_runs WHERE id=$1 FOR UPDATE",
            run_id)
        if not run or not run["removals_held"] or run["held_resolved"]:
            raise HTTPException(409, "nothing held on this run, or already decided")
        removed = 0
        if body.action == "apply":
            newer = await conn.fetchval(
                "SELECT 1 FROM scrape_runs WHERE brand_id=$1 AND tier='daily' AND status='completed' AND id > $2",
                run["brand_id"], run_id)
            if newer:
                raise HTTPException(409, "a newer run has finished for this store; it decides removals now")
            result = await conn.execute(
                """WITH gone AS (
                       UPDATE products SET is_active=false
                       WHERE brand_id=$1 AND is_active=true AND last_seen_at < $2 RETURNING id, title)
                   INSERT INTO product_events (scrape_run_id, product_id, kind, before)
                   SELECT $3, id, 'removed', jsonb_build_object('title', left(title, 200)) FROM gone""",
                run["brand_id"], run["started_at"], run_id)
            removed = int(result.split()[-1])
        await conn.execute(
            "UPDATE scrape_runs SET held_resolved=$2, products_removed = products_removed + $3 WHERE id=$1",
            run_id, "applied" if body.action == "apply" else "discarded", removed)
    _overview_cache["data"] = None
    return {"run_id": run_id, "action": body.action, "removed": removed}


async def _live_snapshot(pool) -> dict:
    running = await pool.fetch(
        f"""SELECT {RUN_COLS}, b.name AS store FROM scrape_runs sr JOIN brands b ON b.id = sr.brand_id
            WHERE sr.status='running' OR sr.finished_at > now() - interval '2 minutes' ORDER BY sr.id""")
    jobs = await pool.fetch(
        """SELECT j.id, j.brand_id, b.name AS store, j.tier, j.status, j.egress, j.attempts, j.tried,
                  j.requested_at, j.started_at
           FROM scrape_jobs j JOIN brands b ON b.id = j.brand_id
           WHERE j.status IN ('queued','running','cancelling') ORDER BY j.id""")
    # Jobs that failed in the last 12 hours and were not redone since, so an overnight failure stays visible.
    failed = await pool.fetch(
        """SELECT j.id, j.brand_id, b.name AS store, j.tier, j.status, j.egress, j.attempts, j.tried, j.error,
                  j.finished_at
           FROM scrape_jobs j JOIN brands b ON b.id = j.brand_id
           WHERE j.status = 'failed' AND j.finished_at > now() - interval '12 hours'
             AND NOT EXISTS (SELECT 1 FROM scrape_jobs k WHERE k.brand_id = j.brand_id AND k.id > j.id
                             AND k.status IN ('queued','running','done'))
           ORDER BY j.id DESC LIMIT 20""")
    # Progress of the latest "Refresh all".
    batch = await pool.fetchrow(
        """WITH last AS (SELECT max(requested_at) AS t FROM scrape_jobs WHERE batch = 'all')
           SELECT count(*) AS total,
                  count(*) FILTER (WHERE status = 'done') AS done,
                  count(*) FILTER (WHERE status = 'failed') AS failed,
                  count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
                  count(*) FILTER (WHERE status IN ('queued','running','cancelling')) AS open,
                  min(requested_at) AS requested_at, max(finished_at) AS last_finished_at
           FROM scrape_jobs, last
           WHERE batch = 'all' AND requested_at > last.t - interval '1 minute'""")
    worker = await pool.fetchrow(
        "SELECT extract(epoch FROM now() - max(heartbeat_at))::int AS age, max(note) AS note FROM scrape_worker")
    last_id = await pool.fetchval("SELECT coalesce(max(id),0) FROM scrape_runs WHERE status <> 'running'")
    online = bool(worker and worker["age"] is not None and worker["age"] < 15)
    return {"runs": [_run(r) for r in running], "jobs": [_row(j) for j in jobs],
            "failed_jobs": [_row(j) for j in failed],
            "batch": _row(batch) if batch and batch["total"] else None,
            "worker_online": online, "worker_note": worker["note"] if online else None,
            "month_proxy_bytes": await month_proxy_bytes(pool), "last_finished_run": last_id,
            "at": datetime.now(timezone.utc).isoformat()}


@router.get("/live")
async def live(request: Request):
    """Server-sent events: a snapshot of running runs, queued jobs and the worker every 2 seconds."""
    pool = await get_pool()

    async def stream():
        while not await request.is_disconnected():
            try:
                snap = await _live_snapshot(pool)
                yield f"data: {json.dumps(snap)}\n\n"
            except Exception as e:  # keep the stream up; the page shows the error
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
