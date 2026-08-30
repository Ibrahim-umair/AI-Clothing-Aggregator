"""
One-time fix-up for products already sitting in Postgres whose store-side
tags say they aren't really purchasable (see product_normalize.py's
FORCE_UNAVAILABLE_TAGS / tags_force_unavailable) even though one or more
variants were loaded with current_available = true. Confirmed against the
real live sites (Cambridge, Outfitters) before this was written — see the
comment on FORCE_UNAVAILABLE_TAGS for what was checked.

Only touches variants.current_available (false where it was true) and
writes a variant_snapshots row for each real flip, matching how
db/scraper/writer.py records an availability change on a normal scrape.
Products stay fully browsable — this never touches is_active or anything
about visibility.

    python backfill_unavailable_tags.py
"""
import psycopg2
import psycopg2.extras

from product_normalize import tags_force_unavailable

DSN = "host=localhost port=5433 dbname=libas user=libas password=libas_dev_password"


def main():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()

    cur.execute("SELECT id, raw_source->'tags' FROM products WHERE raw_source ? 'tags'")
    rows = cur.fetchall()

    affected_product_ids = []
    for pid, tags in rows:
        if tags_force_unavailable(tags or []):
            affected_product_ids.append(pid)

    print(f"Scanned {len(rows)} products with tags, {len(affected_product_ids)} carry a force-unavailable tag")

    flipped = 0
    snapshots = 0
    for pid in affected_product_ids:
        cur.execute(
            "SELECT id, current_price, current_compare_at, current_available FROM variants "
            "WHERE product_id = %s AND current_available = true",
            (pid,),
        )
        to_flip = cur.fetchall()
        for vid, price, compare_at, _old_avail in to_flip:
            cur.execute("UPDATE variants SET current_available = false WHERE id = %s", (vid,))
            cur.execute(
                "INSERT INTO variant_snapshots (variant_id, price, compare_at_price, available) "
                "VALUES (%s, %s, %s, false)",
                (vid, price, compare_at),
            )
            flipped += 1
            snapshots += 1
        conn.commit()

    print(f"DONE: {flipped} variants flipped true->false across {len(affected_product_ids)} products, {snapshots} snapshot rows written")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
