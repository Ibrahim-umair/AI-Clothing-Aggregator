# Scraper pipeline — commands reference

Run everything from `db/scraper/` (or `db/`, either works since `run_scrape.py`
adds `db/` to the path itself). Requires the Postgres container to be up
(`docker compose up -d` from `db/`) and `brands` already seeded at least once
(`python ../load_data.py`, one-time).

## Day-to-day

```powershell
# Full sweep — one store, real writes
python run_scrape.py --store royal_tag

# Full sweep — every store, real writes (the daily job)
python run_scrape.py --all
python run_scrape.py --tier daily      # same thing, explicit tier name

# Availability-only pass — every store, cheap, no reclassification (the hourly job)
python run_scrape.py --tier hourly

# Preview only — fetches + classifies, prints stats, writes nothing to the DB
python run_scrape.py --dry-run --store cambridge
python run_scrape.py --dry-run --tier daily

# Last known run per store, per tier (started/status/counts/error)
python run_scrape.py --status
```

## Reading the per-store output line

```
{"slug": "royal_tag", "tier": "daily", "status": "completed",
 "fetched": 999, "excluded": 0, "new": 0, "updated": 2, "unchanged": 997,
 "removed": 0, "variants": 3801, "snapshots": 4, "errors": 0}
```

- `new` / `updated` / `unchanged` — a product counts as `updated` if EITHER
  its content changed (title/description/category) OR any of its variants
  had a real price/compare-at/availability flip, or gained a brand-new
  variant (e.g. a new size). A price change or a size going out of stock
  is a real change — it is never hidden behind "unchanged" here.
- `removed` — products that used to be active for this store but weren't in
  this run's fetch at all (soft-delisted: `is_active = false`, not deleted).
- `variants` — variants touched this run (full mode only; always 0 in hourly
  mode's output since that mode doesn't report this counter the same way).
- `snapshots` — how many variants had an actual price/compare-at/
  availability change vs. what was already stored (each one also counts
  toward that product being `updated` above). Checked on every run, full
  or hourly.
- `errors` — products that failed after all DB retry attempts and were
  skipped (not a store-level failure — see `status` for that).

## Configuration (environment variables, all optional)

| Variable | Default | Meaning |
|---|---|---|
| `SCRAPE_STORE_CONCURRENCY` | `5` | how many stores fetch in parallel |
| `SCRAPE_PER_STORE_DELAY` | `3` | seconds between requests *to the same store* |
| `SCRAPE_MAX_RETRIES` | `5` | retry attempts before a store is marked failed |
| `SCRAPE_CANARY_DROP_THRESHOLD` | `0.30` | fetched-count drop (vs. last daily run) that triggers an ALERT |
| `COUGAR_STOREFRONT_TOKEN` | unset | required for Cougar (GraphQL) only — see below |
| `ALERT_WEBHOOK_URL` | unset | if set, alerts are also POSTed here as `{"text": "..."}` (Slack-compatible) |

Alerts always go to `db/scraper/alerts.log` regardless of the webhook setting.

## Cougar (GraphQL store) setup

Every other store works with zero configuration. Cougar needs a Shopify
Storefront API access token, which is public (not a secret) but has to be
found by hand: open cougar.com.pk in a browser, open dev tools → Network,
reload, find a request to `/api/*/graphql.json`, and copy the
`X-Shopify-Storefront-Access-Token` header value.

**This is now persisted** in `db/scraper/.env` (loaded automatically by
`run_scrape.py` at startup — see `_load_dotenv()`), so day-to-day commands
need no extra setup. This is what a real production run on 2026-08-28
silently missed: the token was set by hand in one terminal session and
never persisted, so the next run (a fresh shell) had nothing and Cougar
failed cleanly while the other 14 stores completed. `.env` fixes that —
it's local machine config, not something to commit to a shared repo.

If Cougar ever rotates its token (a real `StoreFetchError`/`alerts.log`
entry saying the token is missing or a GraphQL auth error), refresh it the
same way and update the one line in `db/scraper/.env`:

```powershell
# one-off override without touching .env, e.g. to test a new token first:
$env:COUGAR_STOREFRONT_TOKEN = "paste-new-token-here"
python run_scrape.py --store cougar
```

An explicitly-set environment variable always wins over `.env`.

## Scheduling (once a deployment target is chosen)

`run_scrape.py` is a plain script — any scheduler just needs to run it on a
timer, no code changes:

```powershell
# Windows Task Scheduler — Action: "Start a program"
#   Program:   python.exe
#   Arguments: run_scrape.py --tier daily
#   Start in:  C:\Work\scraping-init\db\scraper
# Trigger: daily, e.g. 3:00 AM

#   Arguments: run_scrape.py --tier hourly
# Trigger: every 1 hour
```

```bash
# cron (Linux/deployed host) — equivalent
0 3 * * * cd /path/to/db/scraper && python3 run_scrape.py --tier daily
0 * * * * cd /path/to/db/scraper && python3 run_scrape.py --tier hourly
```

## One-off / maintenance commands (existing, not part of this pipeline)

```powershell
cd ../                              # db/
python test_classify.py             # regression suite for classify() — run before trusting any change
python reseed_categories.py         # run after adding a new leaf to CATEGORY_TREE
python backfill_categories.py       # recompute category_id for all products from stored raw_source
python load_data.py                 # one-time JSONL -> Postgres load/replay (dev/offline use)
```
