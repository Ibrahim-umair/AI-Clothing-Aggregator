#!/usr/bin/env python
"""
CLI entrypoint for the recurring scraping pipeline.

    python run_scrape.py --all                 # every store, full sweep
    python run_scrape.py --store cougar         # one store, full sweep
    python run_scrape.py --tier daily           # all 15, full sweep (the daily schedule)
    python run_scrape.py --tier hourly          # all 15, availability-only pass (the hourly schedule)
    python run_scrape.py --dry-run --store X    # fetch + classify, print stats, write nothing
    python run_scrape.py --status               # last scrape_runs row per brand, per tier

See C:\\Users\\Admin\\.claude\\plans\\logical-weaving-puffin.md for the full design.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import psycopg2
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # db/ (load_data.py etc.)

from load_data import BRANDS_ALL, DSN, strip_html, classify
from product_normalize import normalize_product_fields
from category_lookup import build_category_lookup, resolve_category_id

from pacing import Pacer
from fetchers import fetch_rest_store, fetch_graphql_store, StoreFetchError
from fetch_ucp import fetch_ucp_store
from fetch_sfcc import fetch_sfcc_store
from writer import (ConnHolder, with_reconnect_retry, upsert_product_full, upsert_variant_availability_only,
                    mark_stale_inactive, count_stale)
from progress import RunTracker


def _load_dotenv():
    # No dependency on python-dotenv for one file. COUGAR_STOREFRONT_TOKEN
    # is a real value (not a secret — see fetchers.py/COMMANDS.md) but
    # setting it by hand every session was the reason a real daily run
    # (2026-08-28) silently skipped Cougar: the token was set in one
    # terminal session and never persisted anywhere, so the next run (a
    # fresh shell, or a scheduled task) had nothing. `.env` here is
    # git-ignored-by-convention local config, read once at import time;
    # an already-set real environment variable always wins over it.
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

STORE_CONCURRENCY = int(os.environ.get("SCRAPE_STORE_CONCURRENCY", "5"))
PER_STORE_DELAY_SECONDS = float(os.environ.get("SCRAPE_PER_STORE_DELAY", "3"))
MAX_RETRIES = int(os.environ.get("SCRAPE_MAX_RETRIES", "5"))
CANARY_DROP_THRESHOLD = float(os.environ.get("SCRAPE_CANARY_DROP_THRESHOLD", "0.30"))  # 30%
# A run that would delist more than this share of a store's active products
# (and at least HOLD_MIN of them) looks partial: removals are held for a
# person to apply or discard on the admin page instead of happening silently.
HOLD_REMOVALS_SHARE = float(os.environ.get("SCRAPE_HOLD_REMOVALS_SHARE", "0.20"))
HOLD_REMOVALS_MIN = int(os.environ.get("SCRAPE_HOLD_REMOVALS_MIN", "25"))
COUGAR_STOREFRONT_TOKEN = os.environ.get("COUGAR_STOREFRONT_TOKEN")
# Where Cougar's GraphQL API is fetched from. cougar.com.pk's own front door
# started returning 403 "Access denied" to AWS and many proxy IPs (Oct 2026),
# while Shopify's direct domain for the same store serves the same token
# fine. base_url stays cougar.com.pk because shopper-facing product links
# are built from it (server/routes/products.py).
COUGAR_API_BASE_URL = os.environ.get("COUGAR_API_BASE_URL", "https://cougar-online.myshopify.com")
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL")
ALERTS_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alerts.log")


def write_alert(message):
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] ALERT {message}"
    print(line, file=sys.stderr)
    with open(ALERTS_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    if ALERT_WEBHOOK_URL:
        try:
            requests.post(ALERT_WEBHOOK_URL, json={"text": line}, timeout=10)
        except Exception:
            pass  # alerting must never itself take down a run


def fetch_iterator(slug, base_url, platform, pacer, session, bid=None, name=None):
    if platform == "hydrogen_graphql":
        return fetch_graphql_store(COUGAR_API_BASE_URL, session, pacer, slug, COUGAR_STOREFRONT_TOKEN, MAX_RETRIES)
    if platform == "sfcc":
        return fetch_sfcc_store(slug, base_url, session, pacer, slug, MAX_RETRIES, stored_raw(bid))
    if platform == "shopify_ucp":
        return fetch_ucp_store(base_url, session, pacer, slug, previous_raw(bid), name, MAX_RETRIES)
    return fetch_rest_store(base_url, session, pacer, slug, MAX_RETRIES)


def stored_raw(bid):
    """Last raw record per product (native id -> raw_source), for fetchers that
    only need a product page when the product is new (Khaadi)."""
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT native_product_id, raw_source FROM products WHERE brand_id=%s", (bid,))
    out = {pid: raw if isinstance(raw, dict) else json.loads(raw) for pid, raw in cur.fetchall()}
    cur.close(); conn.close()
    return out


def previous_raw(bid):
    """Last raw record per product (id -> product type, vendor) for stores
    fetched through the Shopify Catalog, which doesn't return those fields."""
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT native_product_id, raw_source->>'product_type', raw_source->>'vendor' "
                "FROM products WHERE brand_id=%s", (bid,))
    out = {pid: {"product_type": pt, "vendor": vendor} for pid, pt, vendor in cur.fetchall()}
    cur.close(); conn.close()
    return out


def last_known_count(cur, bid):
    cur.execute(
        "SELECT product_count FROM scrape_runs WHERE brand_id=%s AND tier='daily' AND status='completed' "
        "ORDER BY id DESC LIMIT 1",
        (bid,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def run_store_daily(slug, name, base_url, platform, bid, category_id, leaf_lookup, dry_run):
    is_graphql = platform == "hydrogen_graphql"
    pacer = Pacer(PER_STORE_DELAY_SECONDS)
    started_at = datetime.now(timezone.utc)
    holder = None if dry_run else ConnHolder()
    check_conn = psycopg2.connect(DSN)  # read-only lookups (existence checks in dry-run, canary baseline)
    check_cur = check_conn.cursor()
    prior_count = last_known_count(check_cur, bid)
    tracker = RunTracker(bid, "daily", started_at, prior_count, dry_run)
    run_id = tracker.run_id

    counts = {"fetched": 0, "excluded": 0, "new": 0, "updated": 0, "unchanged": 0,
              "variants": 0, "snapshots": 0, "errors": 0}
    error_message = None
    removed = held = 0
    try:
        try:
            for p in fetch_iterator(slug, base_url, platform, pacer, tracker.session(), bid, name):
                counts["fetched"] += 1
                tracker.fetched_one()
                title = p.get("title") or ""
                nf = normalize_product_fields(p, is_graphql)
                description = strip_html(nf["description_html"]) or ""
                cls = classify(slug, p, title, nf["product_type"], ",".join(nf["tags"]), nf["vendor"], description)
                if cls is None:
                    counts["excluded"] += 1
                    continue
                cat_id = resolve_category_id(cls, category_id, leaf_lookup)

                if dry_run:
                    check_cur.execute(
                        "SELECT 1 FROM products WHERE brand_id=%s AND native_product_id=%s", (bid, nf["native_id"])
                    )
                    counts["new" if check_cur.fetchone() is None else "updated"] += 1
                    continue

                result = with_reconnect_retry(
                    holder,
                    lambda conn, cur: upsert_product_full(
                        conn, cur, bid, nf["native_id"], p, title, description, cat_id, cls,
                        nf["tags"], nf["images"], is_graphql, nf["raw_variants"], color_id_cache, run_id,
                    ),
                    slug,
                    MAX_RETRIES,
                )
                if result is None:
                    counts["errors"] += 1
                    continue
                counts[result["outcome"]] += 1
                counts["variants"] += result["variant_count"]
                counts["snapshots"] += result["snapshot_count"]
        except StoreFetchError as e:
            error_message = str(e)
            write_alert(f"{slug}: fetch failed — {e}")

        dropped = bool(prior_count and counts["fetched"] > 0
                       and counts["fetched"] < prior_count * (1 - CANARY_DROP_THRESHOLD))
        if not dry_run and error_message is None:
            tracker.set_phase("removing")
            stale, active = count_stale(check_cur, bid, started_at)
            if dropped or (stale >= HOLD_REMOVALS_MIN and stale > active * HOLD_REMOVALS_SHARE):
                held = stale
                write_alert(f"{slug}: {stale} of {active} products not seen this run — removals held for review "
                            f"(fetched {counts['fetched']}, last run {prior_count})")
            else:
                removed = with_reconnect_retry(
                    holder, lambda conn, cur: mark_stale_inactive(conn, cur, bid, started_at, run_id),
                    slug, MAX_RETRIES) or 0
        elif dropped:
            write_alert(f"{slug}: fetched count dropped {100*(1-counts['fetched']/prior_count):.0f}% vs last daily run "
                        f"({prior_count} -> {counts['fetched']})")
    except Exception as e:
        tracker.finish("failed", counts, error_message=f"crashed: {e}")
        raise

    status = "failed" if error_message else "completed"
    tracker.finish(status, counts, removed, held, error_message)

    check_cur.close(); check_conn.close()
    if holder:
        holder.cur.close(); holder.conn.close()
    return {"slug": slug, "name": name, "tier": "daily", "status": status, "removed": removed,
            "removals_held": held, "run_id": run_id, **counts}


def run_store_hourly(slug, name, base_url, platform, bid, dry_run):
    is_graphql = platform == "hydrogen_graphql"
    pacer = Pacer(PER_STORE_DELAY_SECONDS)
    started_at = datetime.now(timezone.utc)
    holder = None if dry_run else ConnHolder()
    check_conn = psycopg2.connect(DSN)
    check_cur = check_conn.cursor()
    tracker = RunTracker(bid, "hourly", started_at, last_known_count(check_cur, bid), dry_run)
    check_cur.close(); check_conn.close()
    run_id = tracker.run_id

    counts = {"fetched": 0, "found": 0, "not_found": 0, "updated": 0, "snapshots": 0, "errors": 0}
    error_message = None
    try:
        for p in fetch_iterator(slug, base_url, platform, pacer, tracker.session(), bid, name):
            counts["fetched"] += 1
            tracker.fetched_one()
            nf = normalize_product_fields(p, is_graphql)
            if dry_run:
                continue
            result = with_reconnect_retry(
                holder,
                lambda conn, cur: upsert_variant_availability_only(
                    conn, cur, bid, nf["native_id"], is_graphql, nf["raw_variants"], nf["tags"], run_id
                ),
                slug,
                MAX_RETRIES,
            )
            if result is None:
                counts["errors"] += 1
                continue
            counts["found" if result["found"] else "not_found"] += 1
            counts["updated"] += result["updated"]
            counts["snapshots"] += result["snapshot_count"]
    except StoreFetchError as e:
        error_message = str(e)
        write_alert(f"{slug}: fetch failed — {e}")
    except Exception as e:
        tracker.finish("failed", counts, error_message=f"crashed: {e}")
        raise

    status = "failed" if error_message else "completed"
    tracker.finish(status, counts, error_message=error_message)
    if holder:
        holder.cur.close(); holder.conn.close()

    return {"slug": slug, "name": name, "tier": "hourly", "status": status, "run_id": run_id, **counts}


color_id_cache = {}


def select_stores(args):
    if args.store:
        matches = [b for b in BRANDS_ALL if b[0] == args.store]
        if not matches:
            print(f"Unknown store slug: {args.store}", file=sys.stderr)
            sys.exit(1)
        return matches
    return BRANDS_ALL


def cmd_status():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT ON (b.slug, sr.tier) b.slug, sr.tier, sr.started_at, sr.finished_at,
                  sr.status, sr.product_count, sr.products_new, sr.products_updated,
                  sr.products_removed, sr.error_message
           FROM scrape_runs sr JOIN brands b ON b.id = sr.brand_id
           ORDER BY b.slug, sr.tier, sr.id DESC"""
    )
    rows = cur.fetchall()
    if not rows:
        print("No scrape_runs recorded yet.")
        return
    for slug, tier, started, finished, status, count, new, updated, removed, err in rows:
        line = f"{slug:20} {tier:7} {status:10} started={started} count={count} new={new} updated={updated} removed={removed}"
        print(line + (f" ERROR={err}" if err else ""))
    cur.close(); conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="run every store (full sweep)")
    ap.add_argument("--store", help="run a single store by slug")
    ap.add_argument("--tier", choices=["daily", "hourly"], help="run all 15 stores at this tier")
    ap.add_argument("--dry-run", action="store_true", help="fetch + classify, print stats, write nothing")
    ap.add_argument("--status", action="store_true", help="print the last scrape_runs row per brand/tier")
    ap.add_argument("--concurrency", type=int, default=STORE_CONCURRENCY)
    args = ap.parse_args()

    if args.status:
        cmd_status()
        return

    if not (args.all or args.store or args.tier):
        ap.error("one of --all, --store, --tier, or --status is required")

    tier = args.tier or "daily"
    stores = select_stores(args)

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT slug, id FROM brands")
    brand_id_map = dict(cur.fetchall())
    category_id = leaf_lookup = None
    if tier == "daily":
        category_id, leaf_lookup = build_category_lookup(cur)
    cur.close(); conn.close()

    run_fn = run_store_daily if tier == "daily" else run_store_hourly

    print(f"Running tier={tier} across {len(stores)} store(s), concurrency={args.concurrency}, dry_run={args.dry_run}")
    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {}
        for slug, name, base_url, platform in stores:
            bid = brand_id_map.get(slug)
            if bid is None:
                print(f"  [{slug}] not seeded in brands table yet — run load_data.py once first, skipping")
                continue
            if tier == "daily":
                fut = pool.submit(run_fn, slug, name, base_url, platform, bid, category_id, leaf_lookup, args.dry_run)
            else:
                fut = pool.submit(run_fn, slug, name, base_url, platform, bid, args.dry_run)
            futures[fut] = slug

        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                r = fut.result()
                results.append(r)
                print(f"  [{slug}] {json.dumps(r)}")
            except Exception as e:
                write_alert(f"{slug}: unhandled exception in worker — {e}")
                print(f"  [{slug}] CRASHED: {e}", file=sys.stderr)

    elapsed = time.time() - t0
    ok = sum(1 for r in results if r["status"] == "completed")
    print(f"\nDone in {elapsed:.1f}s — {ok}/{len(results)} stores completed, tier={tier}")


if __name__ == "__main__":
    main()
