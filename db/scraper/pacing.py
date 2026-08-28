"""
Per-store rate limiting for the live scraper. Each store gets its own Pacer
instance — enforces a minimum delay between consecutive requests *to that
store*, independent of what other stores are doing concurrently (they're
separate domains/origins, so there's no shared bucket to coordinate across).

This deliberately does NOT reproduce the original one-time scrape's 25s
GLOBAL cross-store delay (see scraped_data/progress.log) — that was
sequential/single-store-at-a-time by construction, so a global delay and a
per-store delay were the same thing. Running stores concurrently means the
right unit is per-store pacing; see CHANGELOG/plan notes for why this is a
deliberate, flagged behavior change, not an oversight.
"""
import threading
import time


class Pacer:
    def __init__(self, min_interval_seconds):
        self.min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def wait(self):
        """Blocks until at least min_interval seconds have passed since the
        last call to wait() on this instance. Thread-safe (a single Pacer
        is only ever used by the one worker thread handling its store, but
        the lock costs nothing and removes any doubt)."""
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self.min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_at = time.monotonic()
