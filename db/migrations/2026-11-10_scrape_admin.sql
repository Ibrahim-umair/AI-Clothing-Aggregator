-- Scrape admin page: live progress, egress (proxy) stats, change log, job queue.
-- Idempotent; safe to run twice.

-- Live progress: the row is now written when a run starts and refreshed while it runs.
ALTER TABLE scrape_runs
    ADD COLUMN IF NOT EXISTS phase           TEXT,         -- fetching | writing | removing | done
    ADD COLUMN IF NOT EXISTS fetched_so_far  INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS expected_count  INT,          -- last completed run's product_count
    ADD COLUMN IF NOT EXISTS heartbeat_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS egress          TEXT,         -- 'direct' or 'proxy #3 (1.2.3.4)'; never credentials
    ADD COLUMN IF NOT EXISTS requests_ok     INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS requests_429    INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS requests_403    INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS requests_other  INT DEFAULT 0, -- other HTTP errors and connection failures
    ADD COLUMN IF NOT EXISTS bytes_in        BIGINT DEFAULT 0, -- body + headers as received; an estimate of proxy bandwidth
    ADD COLUMN IF NOT EXISTS removals_held   INT DEFAULT 0, -- products not seen, NOT delisted because the run looked partial
    ADD COLUMN IF NOT EXISTS held_resolved   TEXT,          -- applied | discarded, once someone decides
    ADD COLUMN IF NOT EXISTS job_id          BIGINT;

CREATE INDEX IF NOT EXISTS idx_scrape_runs_brand ON scrape_runs(brand_id, tier, id DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_run ON variant_snapshots(scrape_run_id);

-- One row per change a run made to a product. Small before/after values only,
-- never whole records. Kinds: new, removed, returned, out_of_stock, back_in_stock,
-- price, sale_on, sale_off, title, category, photos.
CREATE TABLE IF NOT EXISTS product_events (
    id            BIGSERIAL PRIMARY KEY,
    scrape_run_id BIGINT REFERENCES scrape_runs(id) ON DELETE CASCADE,
    product_id    BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,
    before        JSONB,
    after         JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_run     ON product_events(scrape_run_id, kind);
CREATE INDEX IF NOT EXISTS idx_events_product ON product_events(product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_time    ON product_events(created_at);

-- Refresh buttons add a row here; the worker (started by a command) picks it up.
CREATE TABLE IF NOT EXISTS scrape_jobs (
    id            BIGSERIAL PRIMARY KEY,
    brand_id      INT NOT NULL REFERENCES brands(id),
    tier          TEXT NOT NULL DEFAULT 'daily',
    status        TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | failed | cancelled
    egress        TEXT,                             -- chosen by the worker
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    error         TEXT
);
-- At most one queued or running job per store.
CREATE UNIQUE INDEX IF NOT EXISTS uq_scrape_jobs_open ON scrape_jobs(brand_id) WHERE status IN ('queued', 'running');

-- "Test all proxies" results.
CREATE TABLE IF NOT EXISTS egress_checks (
    id          BIGSERIAL PRIMARY KEY,
    egress      TEXT NOT NULL,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    target      TEXT NOT NULL,     -- 'shopify' | 'cougar' | 'sfcc'
    http_status INT,
    latency_ms  INT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_egress_checks ON egress_checks(egress, checked_at DESC);
