#!/usr/bin/env python
"""
Scrape admin: one command for the /admin page and the worker behind its
Refresh buttons.

    python db/scraper/admin.py                # API + page + worker, opens /admin in the browser
                                              # (page only if a worker is already running)
    python db/scraper/admin.py --worker       # worker only (the page runs elsewhere)
    python db/scraper/admin.py --queue-all    # queue a full refresh of every store, oldest first
    python db/scraper/admin.py --queue equator --via direct   # one store, trying this route first
    python db/scraper/admin.py --test-egress  # one small request per way out, saved for the page
    python db/scraper/admin.py --status       # the queue and the worker, in the terminal

Ctrl+C stops everything. A refresh that was running goes back in the queue.

The worker takes queued scrape_jobs one at a time, oldest first, and runs
`run_scrape.py --store <slug> --tier <tier>` as a child process. One job at
a time means one request every SCRAPE_WORKER_DELAY seconds (default 3) in
total, the slow pace Shopify tolerates from a single IP.

Which way out (egress) a job uses:
  1. direct first (this machine's IP; free),
  2. then each Webshare proxy in file order,
skipping any way out that was blocked (a failed run with 429/403, or a
failed "test ways out" check) in the last BLOCK_HOURS for that platform
(Shopify blocks per IP across all its stores; Khaadi/Sapphire separately).
If a run fails with 429/403 or a connection error, the job is retried on the
next way out, up to MAX_ATTEMPTS runs. A proxy is only used while this
month's proxy bytes plus 1.5x the store's estimate stay under
WEBSHARE_STOP_MB (default 900 of the free plan's 1,024).

While a job runs the worker keeps Windows from sleeping (not from a closed
lid). Proxy credentials only ever reach the child's HTTPS_PROXY; logs
(db/scraper/logs/) and the database get labels, and every line is scrubbed.
"""
import argparse
import collections
import ctypes
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import psycopg2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))  # db/ for load_data
sys.path.insert(0, str(HERE))

from load_data import DSN  # noqa: E402
from egress import all_egress, check, check_ok, scrub, CHECK_TARGETS  # noqa: E402

LOG_DIR = HERE / "logs"
SERVER_DIR = ROOT / "server"
FRONTEND_DIR = ROOT / "frontend"
API_PORT, PAGE_PORT = 4000, 5173

POLL_SECONDS = 2
HEARTBEAT_SECONDS = 5
WORKER_ONLINE_SECONDS = 15
RUN_STALLED_SECONDS = 60
BLOCK_HOURS = float(os.environ.get("SCRAPE_BLOCK_HOURS", "6"))
MAX_ATTEMPTS = int(os.environ.get("SCRAPE_MAX_ATTEMPTS", "3"))
REQUEST_DELAY = os.environ.get("SCRAPE_WORKER_DELAY", "3")
STOP_MB = float(os.environ.get("WEBSHARE_STOP_MB", "900"))
BYTES_PER_PRODUCT = 350        # measured on the wire (gzipped), Nov 2026
ESTIMATE_SAFETY = 1.5

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def say(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def connect():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    return conn


def keep_awake(on):
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def family(platform):
    return "sfcc" if platform == "sfcc" else "shopify"


# ---------------------------------------------------------------- queue

def queue_all(cur, tier="daily", stale_hours=None):
    """One job per store without an open one, the longest-unrefreshed first."""
    cur.execute(
        """INSERT INTO scrape_jobs (brand_id, tier, batch)
           SELECT b.id, %s, 'all' FROM brands b
           LEFT JOIN LATERAL (SELECT max(started_at) AS t FROM scrape_runs r
                              WHERE r.brand_id = b.id AND r.tier = 'daily' AND r.status = 'completed') l ON true
           WHERE NOT EXISTS (SELECT 1 FROM scrape_jobs j WHERE j.brand_id = b.id
                             AND j.status IN ('queued','running','cancelling'))
             AND (%s::float IS NULL OR l.t IS NULL OR l.t < now() - %s::float * interval '1 hour')
           ORDER BY l.t NULLS FIRST, b.id
           RETURNING id""",
        (tier, stale_hours, stale_hours))
    return len(cur.fetchall())


# ---------------------------------------------------------------- egress

def blocked(cur, fam, brand_id):
    """Ways out blocked in the last BLOCK_HOURS, unless a later run on the same way out completed.
    A 429 is the platform's rate limit (Shopify counts per IP across all its stores), so it
    blocks the route for the whole platform family. A 403 is one store refusing that IP
    (Equator refuses proxy IPs), so it blocks the route for that store only."""
    cur.execute(
        """WITH r AS (
               SELECT sr.egress, sr.brand_id, sr.started_at, sr.status, sr.requests_429, sr.requests_403,
                      CASE WHEN b.platform_type::text = 'sfcc' THEN 'sfcc' ELSE 'shopify' END AS fam
               FROM scrape_runs sr JOIN brands b ON b.id = sr.brand_id
               WHERE sr.egress IS NOT NULL AND sr.started_at > now() - %s * interval '1 hour')
           SELECT egress FROM r
           WHERE fam = %s AND status = 'failed'
             AND (requests_429 > 0 OR (requests_403 > 0 AND brand_id = %s))
             AND NOT EXISTS (SELECT 1 FROM r r2 WHERE r2.egress = r.egress AND r2.fam = r.fam
                             AND r2.status = 'completed' AND r2.started_at > r.started_at
                             AND (r.requests_429 > 0 OR r2.brand_id = r.brand_id))
           UNION
           SELECT egress FROM (
               SELECT DISTINCT ON (egress) egress, http_status, checked_at FROM egress_checks
               WHERE target = %s AND checked_at > now() - %s * interval '1 hour'
               ORDER BY egress, checked_at DESC) c
           WHERE (c.http_status IS NULL OR c.http_status >= 400)
             AND NOT EXISTS (SELECT 1 FROM r WHERE r.egress = c.egress AND r.fam = %s
                             AND r.status = 'completed' AND r.started_at > c.checked_at)""",
        (BLOCK_HOURS, fam, brand_id, fam, BLOCK_HOURS, fam))
    return {r[0] for r in cur.fetchall()}


def month_proxy_bytes(cur):
    cur.execute(
        """SELECT (SELECT coalesce(sum(bytes_in),0) FROM scrape_runs
                   WHERE egress LIKE 'proxy%' AND started_at >= date_trunc('month', now()))
                + (SELECT coalesce(sum(bytes_in),0) FROM egress_checks
                   WHERE egress LIKE 'proxy%' AND checked_at >= date_trunc('month', now()))""")
    return int(cur.fetchone()[0])


def store_estimate(cur, bid):
    cur.execute("SELECT count(*) FROM products WHERE brand_id=%s AND is_active", (bid,))
    active = cur.fetchone()[0]
    cur.execute("SELECT bytes_in, product_count FROM scrape_runs WHERE brand_id=%s AND status='completed' "
                "AND bytes_in > 0 AND product_count > 0 ORDER BY id DESC LIMIT 1", (bid,))
    row = cur.fetchone()
    per = row[0] / row[1] if row else BYTES_PER_PRODUCT
    return int(max(active, 250) * per * ESTIMATE_SAFETY)


def pick_egress(cur, job, tried):
    """(label, proxy_url) for the next attempt, or (None, reason)."""
    bad = blocked(cur, family(job["platform"]), job["brand_id"])
    over_budget = None
    routes = all_egress()
    routes.sort(key=lambda r: r[0] != job.get("via"))  # the asked-for route first
    for label, url in routes:
        if label in tried or (label in bad and label != job.get("via")):
            continue
        if url:
            used, need = month_proxy_bytes(cur), store_estimate(cur, job["brand_id"])
            if used + need > STOP_MB * 1e6:
                over_budget = (f"proxies paused: {used/1e6:.0f} MB used this month + ~{need/1e6:.0f} MB "
                               f"for this store would pass the {STOP_MB:.0f} MB stop")
                continue
        return label, url
    return None, over_budget or f"no way out left (tried: {', '.join(tried) or 'none'}; blocked: {', '.join(sorted(bad)) or 'none'})"


def test_egress(conn):
    """One request per way out per target, saved to egress_checks. Returns the rows."""
    jobs = [(label, url, target) for label, url in all_egress() for target in CHECK_TARGETS]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda j: (j[0], check(j[1], j[2])), jobs))
    with conn.cursor() as cur:
        for label, r in results:
            cur.execute("INSERT INTO egress_checks (egress, target, http_status, latency_ms, error, bytes_in) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (label, r["target"], r["http_status"], r["latency_ms"], r["error"], r["bytes_in"]))
    return results


# ---------------------------------------------------------------- worker

class Worker:
    def __init__(self):
        self.conn = connect()
        self.cur = self.conn.cursor()
        self.current_job = None
        self.note = "starting"
        self.proc = None
        self.tail = []
        self._stop = threading.Event()
        LOG_DIR.mkdir(exist_ok=True)

    # heartbeat on its own connection, so a long query on the main one never makes the page say "offline"
    def _beat(self):
        conn = connect()
        while not self._stop.is_set():
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE scrape_worker SET heartbeat_at=now(), pid=%s, current_job_id=%s, note=%s "
                                "WHERE id=1", (os.getpid(), self.current_job, self.note))
            except psycopg2.Error:
                try:
                    conn = connect()
                except psycopg2.Error:
                    pass
            self._stop.wait(HEARTBEAT_SECONDS)
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE scrape_worker SET heartbeat_at=NULL, current_job_id=NULL, note='stopped' WHERE id=1")
        except psycopg2.Error:
            pass

    def start(self):
        cur = self.cur
        cur.execute("INSERT INTO scrape_worker (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        cur.execute("SELECT pid, extract(epoch FROM now() - heartbeat_at) FROM scrape_worker WHERE id=1")
        pid, age = cur.fetchone()
        if age is not None and age < WORKER_ONLINE_SECONDS and pid != os.getpid():
            raise SystemExit(f"another worker is running (pid {pid}); stop it first")
        cur.execute("UPDATE scrape_worker SET started_at=now(), heartbeat_at=now(), pid=%s WHERE id=1", (os.getpid(),))
        # Whatever a previous worker left behind.
        cur.execute("UPDATE scrape_jobs SET status='cancelled', finished_at=now() WHERE status='cancelling'")
        # An interrupted job starts over with every way out available: being
        # stopped is not a sign that the way out was blocked.
        cur.execute("UPDATE scrape_jobs SET status='queued', started_at=NULL, attempts=0, tried=NULL "
                    "WHERE status='running' RETURNING id")
        requeued = [r[0] for r in cur.fetchall()]
        # Runs of those jobs died with the previous worker; other runs only once their heartbeat is old
        # (a scrape started by hand may still be going).
        cur.execute(
            "UPDATE scrape_runs SET status='failed', phase='done', finished_at=coalesce(heartbeat_at, now()), "
            "error_message='stopped: the scrape process ended mid-run (worker or laptop stopped)' "
            "WHERE status='running' AND (job_id = ANY(%s) OR heartbeat_at IS NULL "
            "OR heartbeat_at < now() - make_interval(secs => %s)) RETURNING id", (requeued, RUN_STALLED_SECONDS))
        orphans = cur.fetchall()
        if requeued or orphans:
            say(f"recovered: {len(requeued)} job(s) back in the queue, {len(orphans)} dead run(s) marked failed")
        threading.Thread(target=self._beat, daemon=True).start()

    def stop(self):
        self._stop.set()
        keep_awake(False)

    def claim(self):
        self.cur.execute(
            """UPDATE scrape_jobs j SET status='running', started_at=now()
               FROM brands b
               WHERE j.id = (SELECT id FROM scrape_jobs WHERE status='queued' ORDER BY id
                             FOR UPDATE SKIP LOCKED LIMIT 1) AND b.id = j.brand_id
               RETURNING j.id, j.brand_id, j.tier, coalesce(j.attempts,0), coalesce(j.tried,'{}'),
                         b.slug, b.name, b.platform_type::text, j.via""")
        row = self.cur.fetchone()
        if not row:
            return None
        keys = ("id", "brand_id", "tier", "attempts", "tried", "slug", "name", "platform", "via")
        return dict(zip(keys, row))

    def job_status(self, job_id):
        self.cur.execute("SELECT status FROM scrape_jobs WHERE id=%s", (job_id,))
        return self.cur.fetchone()[0]

    def finish_job(self, job_id, status, error=None):
        self.cur.execute("UPDATE scrape_jobs SET status=%s, finished_at=now(), error=%s WHERE id=%s",
                         (status, scrub(error)[:500] if error else None, job_id))

    def spawn(self, job, label, url):
        """Run one scrape. Returns 'exited' or 'cancelled'."""
        env = {k: v for k, v in os.environ.items()
               if k.lower() not in ("https_proxy", "http_proxy", "all_proxy")}
        if url:
            env["HTTPS_PROXY"] = env["HTTP_PROXY"] = url
        env.update(SCRAPE_EGRESS_LABEL=label, SCRAPE_JOB_ID=str(job["id"]), SCRAPE_PER_STORE_DELAY=REQUEST_DELAY,
                   PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        cmd = [sys.executable, "run_scrape.py", "--store", job["slug"], "--tier", job["tier"], "--concurrency", "1"]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.proc = subprocess.Popen(cmd, cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", creationflags=flags)
        tail = collections.deque(maxlen=20)
        log_path = LOG_DIR / f"job-{job['id']}.log"

        def pump(proc=self.proc):
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} {job['slug']} {job['tier']} via {label}\n")
                for line in proc.stdout:
                    line = scrub(line)
                    tail.append(line.rstrip())
                    log.write(line)
                    log.flush()

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        cancelled = False
        while self.proc.poll() is None:
            time.sleep(POLL_SECONDS)
            if not cancelled and self.job_status(job["id"]) == "cancelling":
                cancelled = True
                say(f"  cancelling job {job['id']}")
                self.kill_child()
        reader.join(timeout=5)
        self.proc = None
        self.tail = list(tail)
        return "cancelled" if cancelled else "exited"

    def kill_child(self):
        if self.proc and self.proc.poll() is None:
            kill_tree(self.proc)
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def close_dead_runs(self, job_id, status, message):
        """Runs of this job the killed child left as 'running'."""
        self.cur.execute("UPDATE scrape_runs SET status=%s, phase='done', finished_at=now(), error_message=%s "
                         "WHERE job_id=%s AND status='running'", (status, message, job_id))

    def last_run(self, job_id, after_id):
        self.cur.execute("SELECT id, status, requests_429, requests_403, requests_other, error_message, product_count "
                         "FROM scrape_runs WHERE job_id=%s AND id > %s ORDER BY id DESC LIMIT 1", (job_id, after_id))
        row = self.cur.fetchone()
        keys = ("id", "status", "r429", "r403", "other", "error", "count")
        return dict(zip(keys, row)) if row else None

    def run_job(self, job):
        tried = list(job["tried"])
        attempts = job["attempts"]
        self.cur.execute("SELECT coalesce(max(id),0) FROM scrape_runs")
        last_id = self.cur.fetchone()[0]
        while attempts < MAX_ATTEMPTS:
            label, url = pick_egress(self.cur, job, tried)
            if label is None:
                self.finish_job(job["id"], "failed", url)
                say(f"  {job['name']}: failed, {url}")
                return
            tried.append(label)
            attempts += 1
            self.cur.execute("UPDATE scrape_jobs SET egress=%s, attempts=%s, tried=%s WHERE id=%s",
                             (label, attempts, tried, job["id"]))
            self.note = f"{job['name']} via {label}"
            say(f"  {job['name']} ({job['tier']}) via {label}, attempt {attempts}")
            outcome = self.spawn(job, label, url)
            if outcome == "cancelled":
                self.close_dead_runs(job["id"], "cancelled", "cancelled from the admin page")
                self.finish_job(job["id"], "cancelled")
                return
            self.close_dead_runs(job["id"], "failed", "stopped: the scrape process exited mid-run")
            run = self.last_run(job["id"], last_id)
            if run is None:
                err = " | ".join(self.tail[-3:]) or "the scrape never started"
                self.finish_job(job["id"], "failed", f"no run recorded: {err}")
                say(f"  {job['name']}: no run recorded; see {LOG_DIR / ('job-%d.log' % job['id'])}")
                return
            last_id = run["id"]
            if run["status"] == "completed":
                self.finish_job(job["id"], "done")
                say(f"  {job['name']}: done, {run['count']} products (run {run['id']})")
                return
            err = run["error"] or ""
            blocked_like = run["r429"] or run["r403"] or any(
                s in err for s in ("429", "403", "ProxyError", "ConnectionError", "ConnectTimeout", "Timeout"))
            if not blocked_like:
                self.finish_job(job["id"], "failed", err or "run failed")
                say(f"  {job['name']}: failed, {err[:160]}")
                return
            say(f"  {job['name']}: blocked via {label} ({run['r429']}x429, {run['r403']}x403); trying the next way out")
        self.finish_job(job["id"], "failed", f"blocked on every way out tried: {', '.join(tried)}")

    def loop(self):
        self.start()
        say("worker on: waiting for refreshes (Ctrl+C stops)")
        idle_said = False
        job = None
        try:
            while True:
                job = self.claim()
                if not job:
                    if not idle_said:
                        say("queue empty")
                        idle_said = True
                    self.note = "idle"
                    self.current_job = None
                    keep_awake(False)
                    time.sleep(POLL_SECONDS)
                    continue
                idle_said = False
                keep_awake(True)
                self.current_job = job["id"]
                say(f"job {job['id']}: {job['name']}")
                self.run_job(job)
                job = None
        except KeyboardInterrupt:
            say("stopping")
            if job:
                self.kill_child()
                self.close_dead_runs(job["id"], "failed", "stopped: the worker was closed")
                self.cur.execute("UPDATE scrape_jobs SET status='queued', started_at=NULL, attempts=0, tried=NULL "
                                 "WHERE id=%s AND status IN ('running','cancelling')", (job["id"],))
                say(f"job {job['id']} is back in the queue")
        finally:
            self.stop()


# ---------------------------------------------------------------- launcher

def kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":  # npx and python.exe start the real process as a child
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_db():
    try:
        connect().close()
        return
    except psycopg2.OperationalError:
        pass
    docker = shutil.which("docker")
    if not docker:
        raise SystemExit("Postgres is not reachable and docker is not on PATH. Start Docker, then libas-postgres.")
    say("Postgres is down: starting libas-postgres (Docker Desktop must be running)")
    subprocess.run([docker, "start", "libas-postgres"], check=False)
    for _ in range(30):
        time.sleep(2)
        try:
            connect().close()
            return
        except psycopg2.OperationalError:
            pass
    raise SystemExit("Postgres did not come up. Is Docker Desktop running?")


def build_is_stale():
    index = FRONTEND_DIR / "dist" / "index.html"
    if not index.exists():
        return True
    built = index.stat().st_mtime
    return any(p.stat().st_mtime > built for p in (FRONTEND_DIR / "src").rglob("*") if p.is_file())


def start_servers():
    procs = []
    LOG_DIR.mkdir(exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    if port_open(API_PORT):
        say(f"API already on :{API_PORT}")
    else:
        say(f"starting API on :{API_PORT}  (log: {LOG_DIR / 'api.log'})")
        procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(API_PORT)],
                                      cwd=SERVER_DIR, stdout=open(LOG_DIR / "api.log", "a"),
                                      stderr=subprocess.STDOUT, creationflags=flags))
    if port_open(PAGE_PORT):
        say(f"page already on :{PAGE_PORT}")
    else:
        npm = shutil.which("npm")
        npx = shutil.which("npx")
        if not (npm and npx):
            raise SystemExit("npm/npx not found: install Node, or run the page yourself (npx vite in frontend/)")
        if build_is_stale():
            say("building the page (npm run build)")
            subprocess.run([npm, "run", "build"], cwd=FRONTEND_DIR, check=True,
                           stdout=open(LOG_DIR / "build.log", "w"), stderr=subprocess.STDOUT)
        say(f"serving the page on :{PAGE_PORT}  (log: {LOG_DIR / 'page.log'})")
        procs.append(subprocess.Popen([npx, "vite", "preview", "--port", str(PAGE_PORT), "--strictPort"],
                                      cwd=FRONTEND_DIR, stdout=open(LOG_DIR / "page.log", "a"),
                                      stderr=subprocess.STDOUT, creationflags=flags))
    for _ in range(60):
        if port_open(API_PORT) and port_open(PAGE_PORT):
            break
        time.sleep(1)
    else:
        say("the API or the page did not come up; see the logs above")
    return procs


def worker_online(cur):
    cur.execute("SELECT extract(epoch FROM now()-heartbeat_at) FROM scrape_worker WHERE id=1")
    row = cur.fetchone()
    return bool(row and row[0] is not None and row[0] < WORKER_ONLINE_SECONDS)


def print_status(cur):
    cur.execute("SELECT extract(epoch FROM now()-heartbeat_at)::int, pid, note FROM scrape_worker WHERE id=1")
    w = cur.fetchone()
    online = w and w[0] is not None and w[0] < WORKER_ONLINE_SECONDS
    print(f"worker: {'on' if online else 'off'}" + (f" (pid {w[1]}, {w[2]})" if online else ""))
    cur.execute("SELECT j.id, b.name, j.tier, j.status, j.egress, j.attempts FROM scrape_jobs j "
                "JOIN brands b ON b.id=j.brand_id WHERE j.status IN ('queued','running','cancelling') ORDER BY j.id")
    rows = cur.fetchall()
    print(f"open jobs: {len(rows)}")
    for r in rows[:40]:
        print(f"  #{r[0]:<5} {r[1]:22} {r[2]:6} {r[3]:10} {r[4] or ''} {('x%d' % r[5]) if r[5] else ''}")
    print(f"proxy bytes this month: {month_proxy_bytes(cur)/1e6:.1f} MB (stop at {STOP_MB:.0f} MB)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", action="store_true", help="run only the worker")
    ap.add_argument("--queue-all", action="store_true", help="queue a refresh of every store, then exit")
    ap.add_argument("--queue", metavar="SLUG", help="queue a refresh of one store, then exit")
    ap.add_argument("--via", help="with --queue: route to try first ('direct', a proxy host, or '#N')")
    ap.add_argument("--stale-hours", type=float, help="with --queue-all: only stores not refreshed for this long")
    ap.add_argument("--tier", choices=["daily", "hourly"], default="daily")
    ap.add_argument("--test-egress", action="store_true", help="test every way out, then exit")
    ap.add_argument("--status", action="store_true", help="print the queue and the worker, then exit")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    ensure_db()
    conn = connect()
    cur = conn.cursor()
    if args.queue_all:
        print(f"queued {queue_all(cur, args.tier, args.stale_hours)} store(s)")
        return
    if args.queue:
        via = args.via
        if via and via.startswith("#"):
            via = [label for label, _ in all_egress()][int(via[1:]) + 1]
        elif via and via != "direct" and not via.startswith("proxy"):
            via = f"proxy ({via})"
        if via and via not in [label for label, _ in all_egress()]:
            raise SystemExit(f"unknown route {via!r}; see --test-egress for the list")
        cur.execute("INSERT INTO scrape_jobs (brand_id, tier, via) SELECT id, %s, %s FROM brands WHERE slug=%s "
                    "ON CONFLICT DO NOTHING RETURNING id", (args.tier, via, args.queue))
        row = cur.fetchone()
        print(f"queued job {row[0]}" + (f" via {via}" if via else "") if row else
              "not queued: unknown store, or it already has a refresh queued or running")
        return
    if args.test_egress:
        for label, r in test_egress(conn):
            res = r["http_status"] if r["http_status"] is not None else r["error"]
            print(f"  {'ok ' if check_ok(r) else 'BAD'} {label:24} {r['target']:8} {res}  {r['latency_ms']} ms")
        return
    if args.status:
        print_status(cur)
        return

    procs = [] if args.worker else start_servers()
    if not args.worker and not args.no_browser:
        webbrowser.open(f"http://localhost:{PAGE_PORT}/admin")
    try:
        if not args.worker and worker_online(cur):
            say("a worker is already running (started earlier): serving the page only. Ctrl+C stops.")
            while True:
                time.sleep(60)
        else:
            Worker().loop()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            kill_tree(p)


if __name__ == "__main__":
    main()
