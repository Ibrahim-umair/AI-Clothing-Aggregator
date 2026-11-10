-- Scrape admin, step 4: the worker (db/scraper/admin.py). Idempotent; safe to run twice.

-- Which ways out a job tried, and how many runs it took.
ALTER TABLE scrape_jobs
    ADD COLUMN IF NOT EXISTS attempts   INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tried      TEXT[],          -- egress labels, in order
    ADD COLUMN IF NOT EXISTS batch      TEXT;            -- 'all' when queued by "Refresh all"

-- "Test ways out" requests count toward the Webshare month too.
ALTER TABLE egress_checks ADD COLUMN IF NOT EXISTS bytes_in BIGINT DEFAULT 0;

-- What the worker is doing, for the page.
ALTER TABLE scrape_worker
    ADD COLUMN IF NOT EXISTS current_job_id BIGINT,
    ADD COLUMN IF NOT EXISTS note           TEXT;

-- Runs before this change counted the unzipped body, about 14x the real wire
-- size (~4,800 vs ~350 bytes a product). Scale those down so the month's proxy
-- total is honest. Only rows still above 2,000 bytes a product match, so a
-- second run changes nothing.
UPDATE scrape_runs SET bytes_in = bytes_in / 14
WHERE product_count > 0 AND bytes_in > 2000::bigint * product_count;
