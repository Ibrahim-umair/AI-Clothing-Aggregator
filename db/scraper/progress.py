"""
Live progress for one store's run, for the scrape admin page.

RunTracker writes the scrape_runs row when the run starts (status
'running'), refreshes it every few seconds from a background thread
(fetched so far, request counts by status, bytes received, heartbeat_at),
and finishes it with the final counts. It uses its own autocommit
connection so heartbeats never mix with the writer's transactions.

TrackedSession is a requests.Session that counts every response by status
and adds up bytes received (compressed body as read from the socket, plus
headers). Through a proxy that is close to what the proxy bills; it slightly
under-counts TLS overhead, so the admin page treats it as an estimate.

The egress label says which way the traffic went: 'direct', or the proxy's
host taken from HTTPS_PROXY. Credentials in that URL are never stored.
"""
import os
import threading
import time
from urllib.parse import urlparse

import psycopg2
import requests

from load_data import DSN

HEARTBEAT_SECONDS = 5


def egress_label():
    label = os.environ.get("SCRAPE_EGRESS_LABEL")
    if label:
        return label
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        return f"proxy ({urlparse(proxy).hostname})"
    return "direct"


class Counters:
    def __init__(self):
        self.lock = threading.Lock()
        self.ok = self.r429 = self.r403 = self.other = 0
        self.bytes_in = 0
        self.fetched = 0

    def add_response(self, resp):
        raw = getattr(resp.raw, "_fp_bytes_read", None)
        body = raw if isinstance(raw, int) and raw > 0 else len(resp.content or b"")
        headers = sum(len(k) + len(v) + 4 for k, v in resp.headers.items()) + 300  # +request line/headers
        with self.lock:
            self.bytes_in += body + headers
            if resp.status_code == 429:
                self.r429 += 1
            elif resp.status_code == 403:
                self.r403 += 1
            elif resp.status_code < 400:
                self.ok += 1
            else:
                self.other += 1

    def add_failure(self):
        with self.lock:
            self.other += 1

    def snapshot(self):
        with self.lock:
            return self.fetched, self.ok, self.r429, self.r403, self.other, self.bytes_in


class TrackedSession(requests.Session):
    def __init__(self, counters):
        super().__init__()
        self._counters = counters

    def request(self, *args, **kwargs):
        try:
            resp = super().request(*args, **kwargs)
        except requests.RequestException:
            self._counters.add_failure()
            raise
        self._counters.add_response(resp)
        return resp


class RunTracker:
    """One per store run. With dry_run it counts but writes nothing."""

    def __init__(self, bid, tier, started_at, expected_count, dry_run=False):
        self.counters = Counters()
        self.dry_run = dry_run
        self.run_id = None
        self.phase = "fetching"
        self._stop = threading.Event()
        self._thread = None
        if dry_run:
            return
        self.conn = psycopg2.connect(DSN)
        self.conn.autocommit = True
        job_id = os.environ.get("SCRAPE_JOB_ID")
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scrape_runs (brand_id, tier, started_at, status, phase, expected_count, "
                "heartbeat_at, egress, job_id) VALUES (%s,%s,%s,'running','fetching',%s,now(),%s,%s) RETURNING id",
                (bid, tier, started_at, expected_count, egress_label(), int(job_id) if job_id else None),
            )
            self.run_id = cur.fetchone()[0]
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()

    def session(self):
        return TrackedSession(self.counters)

    def fetched_one(self):
        with self.counters.lock:
            self.counters.fetched += 1

    def set_phase(self, phase):
        self.phase = phase
        self._write()

    def _write(self, extra_sql="", extra_args=()):
        if self.dry_run:
            return
        fetched, ok, r429, r403, other, nbytes = self.counters.snapshot()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE scrape_runs SET phase=%s, fetched_so_far=%s, requests_ok=%s, requests_429=%s, "
                    "requests_403=%s, requests_other=%s, bytes_in=%s, heartbeat_at=now()" + extra_sql +
                    " WHERE id=%s",
                    (self.phase, fetched, ok, r429, r403, other, nbytes, *extra_args, self.run_id),
                )
        except psycopg2.Error:
            # A dropped connection must not kill the run; reconnect for the next beat.
            try:
                self.conn = psycopg2.connect(DSN)
                self.conn.autocommit = True
            except psycopg2.Error:
                pass

    def _beat(self):
        while not self._stop.wait(HEARTBEAT_SECONDS):
            self._write()

    def finish(self, status, counts, removed=0, held=0, error_message=None):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=HEARTBEAT_SECONDS + 1)
        if self.dry_run:
            return
        self.phase = "done"
        self._write(
            ", status=%s, finished_at=now(), product_count=%s, products_new=%s, products_updated=%s, "
            "products_removed=%s, products_unchanged=%s, removals_held=%s, error_message=%s",
            (status, counts.get("fetched", 0), counts.get("new", 0), counts.get("updated", 0),
             removed, counts.get("unchanged", 0), held, error_message),
        )
        self.conn.close()
