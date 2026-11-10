"""
Upsert layer for the live scraper. Two modes:

- upsert_product_full(): daily mode. Refreshes the whole product row
  (title/description/category/raw_source), refreshes images if they
  changed, upserts every variant, and writes a variant_snapshots row only
  where price/compare-at/availability actually changed vs. what was
  already stored. Reuses the exact color/size normalization
  load_data.py's _load_one_product uses (via product_normalize.py).

- upsert_variant_availability_only(): hourly mode. Looks the product up by
  its existing (brand_id, native_product_id) key and, for each of its
  already-known variants, does one targeted UPDATE + conditional snapshot
  on a flip. Never touches products/product_images/category — that's what
  keeps this mode cheap enough to run across all 15 stores every hour. A
  variant or product this mode can't find is simply skipped (new products
  are the daily sweep's job, not this one's).

Both reuse the exact connection-recycle + per-call-commit + reconnect-and-
retry pattern load_data.py built for this sandbox's Docker connection
drops (see with_reconnect_retry below).
"""
import json
import re
import time
from decimal import Decimal, InvalidOperation

import psycopg2

from load_data import DSN, RECONNECT_SECONDS, connect
from product_normalize import normalize_variant_fields, classify_size_system, tags_force_unavailable


def _to_decimal(v):
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _state(cur, pid):
    """What a shopper sees at product level: in stock at all, lowest price, on sale."""
    cur.execute(
        "SELECT bool_or(current_available), min(current_price), "
        "bool_or(current_compare_at IS NOT NULL AND current_compare_at > current_price) "
        "FROM variants WHERE product_id=%s",
        (pid,),
    )
    in_stock, price, on_sale = cur.fetchone()
    return {"in_stock": bool(in_stock), "price": float(price) if price is not None else None,
            "on_sale": bool(on_sale)}


def _event(cur, run_id, pid, kind, before=None, after=None):
    """One row in product_events (the admin page's change log). No-op without a run."""
    if run_id is None:
        return
    cur.execute(
        "INSERT INTO product_events (scrape_run_id, product_id, kind, before, after) VALUES (%s,%s,%s,%s,%s)",
        (run_id, pid, kind, json.dumps(before) if before is not None else None,
         json.dumps(after) if after is not None else None),
    )


def _state_events(cur, run_id, pid, old, new):
    """Product-level events from a before/after _state(): stock, price, sale."""
    if old["in_stock"] != new["in_stock"]:
        _event(cur, run_id, pid, "back_in_stock" if new["in_stock"] else "out_of_stock")
    if old["price"] is not None and new["price"] is not None and old["price"] != new["price"]:
        _event(cur, run_id, pid, "price", {"price": old["price"]}, {"price": new["price"]})
    if old["on_sale"] != new["on_sale"]:
        _event(cur, run_id, pid, "sale_on" if new["on_sale"] else "sale_off",
               {"price": old["price"]}, {"price": new["price"]})


class ConnHolder:
    """Mutable holder for (conn, cur, opened_at) so with_reconnect_retry can
    swap in a fresh connection and have the caller see the new one too."""

    def __init__(self):
        conn, cur = connect()
        self.conn = conn
        self.cur = cur
        self.opened_at = time.time()

    def recycle(self):
        try:
            self.cur.close()
            self.conn.close()
        except Exception:
            pass
        self.conn, self.cur = connect()
        self.opened_at = time.time()


def with_reconnect_retry(holder, fn, label, max_attempts=5):
    """Runs fn(conn, cur) -> result inside a commit/rollback + reconnect-
    and-retry loop, matching load_data.py:750-841. Recycles the connection
    proactively every RECONNECT_SECONDS regardless of errors. Returns fn's
    result, or None if every attempt failed (caller treats as a skip)."""
    for attempt in range(1, max_attempts + 1):
        if time.time() - holder.opened_at > RECONNECT_SECONDS:
            holder.recycle()
        try:
            result = fn(holder.conn, holder.cur)
            holder.conn.commit()
            return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            try:
                holder.conn.rollback()
            except Exception:
                pass
            holder.recycle()
            if attempt >= max_attempts:
                print(f"  [{label}] giving up after {attempt} attempts: {e}")
                return None
            time.sleep(1)
        except Exception as e:
            try:
                holder.conn.rollback()
            except Exception:
                pass
            print(f"  [{label}] error: {e}")
            return None


def _resolve_color_id(conn, cur, color_id_cache, color_name):
    if not color_name:
        return None
    key = color_name.strip().lower()
    cid = color_id_cache.get(key)
    if cid is not None:
        return cid
    cur.execute(
        "INSERT INTO colors (canonical_name) VALUES (%s) "
        "ON CONFLICT (canonical_name) DO UPDATE SET canonical_name=EXCLUDED.canonical_name RETURNING id",
        (color_name.strip(),),
    )
    cid = cur.fetchone()[0]
    color_id_cache[key] = cid
    # Committed immediately, independent of this product's own transaction
    # — same reasoning as load_data.py:607-612: if this product's upsert
    # later rolls back, the color id already cached here must still exist
    # in the DB, or a later product sharing this color would hit a
    # dangling FK reference.
    conn.commit()
    return cid


def upsert_product_full(conn, cur, bid, native_id, p, title, description, cat_id, cls,
                         tags, images, is_graphql, raw_variants, color_id_cache, run_id=None):
    """Full daily-mode upsert. Returns a dict: outcome ('new'|'updated'|
    'unchanged'), variant_count, snapshot_count. 'updated' fires on EITHER
    a content change (title/description/category) OR a real variant-level
    change (price/compare-at/availability flip, or a brand-new variant) —
    a size going out of stock or a price change is a real change to the
    product, not something hidden behind an "unchanged" content check."""
    cur.execute(
        "SELECT title, description, category_id, raw_source, id, is_active FROM products "
        "WHERE brand_id=%s AND native_product_id=%s",
        (bid, native_id),
    )
    existing = cur.fetchone()
    state_before = _state(cur, existing[4]) if existing is not None else None

    cur.execute(
        """INSERT INTO products (brand_id, native_product_id, handle, title, description,
            category_id, style_family, construction_status, age_group, piece_count,
            tags, raw_source, last_seen_at, is_active, is_browsable)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), true, %s)
           ON CONFLICT (brand_id, native_product_id) DO UPDATE SET
             handle=EXCLUDED.handle, title=EXCLUDED.title, description=EXCLUDED.description,
             category_id=EXCLUDED.category_id, style_family=EXCLUDED.style_family,
             construction_status=EXCLUDED.construction_status, piece_count=EXCLUDED.piece_count,
             tags=EXCLUDED.tags, raw_source=EXCLUDED.raw_source, last_seen_at=now(), is_active=true,
             is_browsable=products.is_browsable AND EXCLUDED.is_browsable
           RETURNING id""",
        (bid, native_id, p.get("handle"), title[:500], description, cat_id,
         cls["style"], cls["construction"], "adult", cls.get("piece_count"),
         tags, json.dumps(p), cls.get("browsable", True)),
    )
    pid = cur.fetchone()[0]

    # Deliberately NOT comparing raw_source as a whole: Shopify bumps
    # updated_at (embedded in raw_source) on nearly every fetch regardless
    # of whether anything a shopper would notice actually changed — a real
    # run against Royal Tag showed 0/999 "unchanged" with that comparison,
    # which made the reporting meaningless. raw_source is still
    # unconditionally overwritten above (keeps it fresh for future
    # reclassification); this only asks "did the browsable content
    # change". The final outcome below also folds in variant-level price/
    # stock/new-size changes — a size going out of stock or a price change
    # is absolutely a real change to the product, not something a
    # content-only check should hide as "unchanged".
    content_changed = False
    if existing is not None:
        old_title, old_description, old_cat_id, _old_raw, _old_id, was_active = existing
        content_changed = old_title != title[:500] or old_description != description or old_cat_id != cat_id

    # Images: only rewrite if the url list actually differs — avoids
    # needless delete+insert churn on every run for unchanged products.
    cur.execute("SELECT url FROM product_images WHERE product_id=%s ORDER BY position", (pid,))
    existing_images = [r[0] for r in cur.fetchall()]
    new_images = images[:12]
    if existing_images != new_images:
        # Only the main photo counts as a change worth showing; reordered or
        # added gallery shots would flood the change log.
        if existing is not None and existing_images[:1] != new_images[:1]:
            _event(cur, run_id, pid, "photos", {"url": (existing_images or [None])[0]},
                   {"url": (new_images or [None])[0]})
        cur.execute("DELETE FROM product_images WHERE product_id=%s", (pid,))
        for pos, url_ in enumerate(new_images):
            cur.execute(
                "INSERT INTO product_images (product_id, url, position) VALUES (%s,%s,%s)",
                (pid, url_, pos),
            )

    # Shopify's more complete per-variant image link: an image in the
    # product's OWN images[] array carries the variant ids it belongs to,
    # populated in real data even when a variant's own "featured_image"
    # (normalize_variant_fields' fallback) is null. REST only — Cougar
    # (GraphQL) has no equivalent, see that function's comment.
    image_by_variant_id = {}
    if not is_graphql:
        for img in (p.get("images") or []):
            for vid in (img.get("variant_ids") or []):
                image_by_variant_id[str(vid)] = img.get("src")

    variant_count = 0
    new_variant_count = 0
    snapshot_count = 0
    option_defs = p.get("options") or [] if not is_graphql else []
    for v in raw_variants:
        vf = normalize_variant_fields(v, option_defs, is_graphql)
        # Store-side override: some products (Cambridge, confirmed) carry a
        # theme tag disabling the buy button independent of raw inventory —
        # see tags_force_unavailable's docstring. The product stays
        # browsable; only the purchasability flag changes.
        if tags_force_unavailable(tags):
            vf["available"] = False
        image_url = image_by_variant_id.get(vf["native_vid"]) or vf.get("image_url")

        cur.execute(
            "SELECT current_price, current_compare_at, current_available FROM variants "
            "WHERE product_id=%s AND native_variant_id=%s",
            (pid, vf["native_vid"]),
        )
        existing_variant = cur.fetchone()

        cid_color = _resolve_color_id(conn, cur, color_id_cache, vf["color_name"])
        size_system = classify_size_system(vf["size_val"])
        new_price = _to_decimal(vf["price"])
        new_compare = _to_decimal(vf["compare_at"])

        cur.execute(
            """INSERT INTO variants (product_id, native_variant_id, color_id, size_label,
                size_system, sku, current_price, current_compare_at, current_available, image_url)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (product_id, native_variant_id) DO UPDATE SET
                 color_id=EXCLUDED.color_id, size_label=EXCLUDED.size_label,
                 size_system=EXCLUDED.size_system, sku=EXCLUDED.sku,
                 current_price=EXCLUDED.current_price, current_compare_at=EXCLUDED.current_compare_at,
                 current_available=EXCLUDED.current_available, image_url=EXCLUDED.image_url
               RETURNING id""",
            (pid, vf["native_vid"], cid_color, vf["size_val"], size_system, vf["sku"],
             new_price, new_compare, vf["available"], image_url),
        )
        vid = cur.fetchone()[0]
        variant_count += 1

        if existing_variant is None:
            # A brand-new variant (e.g. a size just added) has no prior
            # state to diff against for a snapshot, but it's absolutely a
            # real change to the product — a new size becoming orderable
            # is exactly the kind of thing "unchanged" must not hide.
            new_variant_count += 1
        else:
            old_price, old_compare, old_avail = existing_variant
            if old_price != new_price or old_compare != new_compare or old_avail != vf["available"]:
                cur.execute(
                    "INSERT INTO variant_snapshots (variant_id, scrape_run_id, price, compare_at_price, available) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (vid, run_id, new_price, new_compare, vf["available"]),
                )
                snapshot_count += 1

    if existing is None:
        outcome = "new"
    elif content_changed or snapshot_count > 0 or new_variant_count > 0:
        outcome = "updated"
    else:
        outcome = "unchanged"

    # Change log. Description edits are left out on purpose: stores re-save
    # whitespace and boilerplate constantly, which would bury real changes.
    if existing is None:
        _event(cur, run_id, pid, "new", None, {"title": title[:200], **_state(cur, pid)})
    else:
        if not was_active:
            _event(cur, run_id, pid, "returned", None, {"title": title[:200]})
        if old_title != title[:500]:
            _event(cur, run_id, pid, "title", {"title": old_title[:200]}, {"title": title[:200]})
        if old_cat_id != cat_id:
            _event(cur, run_id, pid, "category", {"category_id": old_cat_id}, {"category_id": cat_id})
        if snapshot_count > 0 or new_variant_count > 0:
            _state_events(cur, run_id, pid, state_before, _state(cur, pid))

    piece_count = 0
    if existing is None and description and cls["construction"] == "unstitched_fabric":
        # Fabric-piece breakdown is extracted once at creation time only —
        # this text essentially never changes for an existing listing, so
        # re-parsing it on every refresh isn't worth the churn. If it ever
        # needs correcting after the fact, that's backfill_categories.py-
        # style territory (a targeted one-off pass), not this pipeline.
        for m in re.finditer(
            r"(Shirt|Trouser|Dupatta|Shawl)\s+(?:Fit Type:[^F]*)?Fabric:\s*([A-Za-z]+)(?:\s*\|\s*([\d.]+)\s*Meters?)?",
            description,
        ):
            piece, fab, length = m.group(1), m.group(2), m.group(3)
            cur.execute(
                "INSERT INTO product_pieces (product_id, piece_name, fabric_id, length_meters, sort_order) "
                "VALUES (%s,%s,(SELECT id FROM fabrics WHERE lower(name)=lower(%s)),%s,%s)",
                (pid, piece, fab, float(length) if length else None, piece_count),
            )
            piece_count += 1

    return {"pid": pid, "outcome": outcome, "variant_count": variant_count,
            "snapshot_count": snapshot_count, "piece_count": piece_count}


def upsert_variant_availability_only(conn, cur, bid, native_id, is_graphql, raw_variants, tags=None, run_id=None):
    """Hourly-mode write. Returns a dict: found (bool), updated count,
    snapshot_count. Does not touch products, product_images, or
    classification at all. `tags` is only used for the Cambridge
    buy-button-disabled override (see tags_force_unavailable) — optional
    since older/other call shapes have no tags to give it."""
    cur.execute("SELECT id FROM products WHERE brand_id=%s AND native_product_id=%s", (bid, native_id))
    row = cur.fetchone()
    if row is None:
        return {"found": False, "updated": 0, "snapshot_count": 0}
    pid = row[0]
    state_before = _state(cur, pid)

    updated = 0
    snapshot_count = 0
    option_defs = []  # availability-only pass doesn't need color/size, only price/available
    force_unavailable = tags_force_unavailable(tags)
    for v in raw_variants:
        vf = normalize_variant_fields(v, option_defs, is_graphql)
        if force_unavailable:
            vf["available"] = False
        cur.execute(
            "SELECT current_price, current_compare_at, current_available FROM variants "
            "WHERE product_id=%s AND native_variant_id=%s",
            (pid, vf["native_vid"]),
        )
        existing = cur.fetchone()
        if existing is None:
            continue  # brand-new variant since the last daily sweep — that sweep's job, not this one's
        old_price, old_compare, old_avail = existing
        new_price = _to_decimal(vf["price"])
        new_compare = _to_decimal(vf["compare_at"])
        if old_price == new_price and old_compare == new_compare and old_avail == vf["available"]:
            continue
        cur.execute(
            "UPDATE variants SET current_price=%s, current_compare_at=%s, current_available=%s "
            "WHERE product_id=%s AND native_variant_id=%s RETURNING id",
            (new_price, new_compare, vf["available"], pid, vf["native_vid"]),
        )
        vid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO variant_snapshots (variant_id, scrape_run_id, price, compare_at_price, available) "
            "VALUES (%s,%s,%s,%s,%s)",
            (vid, run_id, new_price, new_compare, vf["available"]),
        )
        updated += 1
        snapshot_count += 1

    if updated:
        _state_events(cur, run_id, pid, state_before, _state(cur, pid))
    return {"found": True, "updated": updated, "snapshot_count": snapshot_count}


def count_stale(cur, bid, run_started_at):
    """(active products this run did not see, all active products) for one store."""
    cur.execute(
        "SELECT count(*) FILTER (WHERE last_seen_at < %s), count(*) FROM products "
        "WHERE brand_id=%s AND is_active=true",
        (run_started_at, bid),
    )
    return cur.fetchone()


def mark_stale_inactive(conn, cur, bid, run_started_at, run_id=None):
    """Full daily-mode only, called once after a store's entire fetch
    completes successfully. Anything not touched (last_seen_at refreshed)
    by the run that just finished wasn't in the store's current feed —
    soft-delist it, one 'removed' event each. Precise, self-correcting, no
    arbitrary "N days" guess. Also how held removals get applied later:
    the same run_started_at picks out the same products."""
    cur.execute(
        """WITH gone AS (
               UPDATE products SET is_active=false
               WHERE brand_id=%s AND is_active=true AND last_seen_at < %s
               RETURNING id, title)
           INSERT INTO product_events (scrape_run_id, product_id, kind, before)
           SELECT %s, id, 'removed', jsonb_build_object('title', left(title, 200)) FROM gone""",
        (bid, run_started_at, run_id),
    )
    removed = cur.rowcount
    conn.commit()
    return removed
