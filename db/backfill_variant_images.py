"""One-time fix-up for the full load already sitting in Postgres: populates
variants.image_url from each product's raw_source, using the same
extraction logic load_data.py/writer.py now apply on every load going
forward (see product_normalize.py's normalize_variant_fields + the
images[].variant_ids reverse-map built here).

Real coverage is NOT universal — verified directly against the live data
before writing this: Outfitters ~95%, Zellbury ~84%, Cambridge/Furor
~15%, Edenrobe/Charcoal/Meme near 0%, Cougar (GraphQL) 0% (no per-variant
image field in its Storefront API shape at all). This is a genuine
per-store data gap in what each store's own feed provides, not a bug in
this script — callers must fall back to the product's default image
wherever image_url is NULL.

Only touches variants.image_url; nothing else about the row changes.
"""
import psycopg2
import psycopg2.extras

DSN = "host=localhost port=5433 dbname=libas user=libas password=libas_dev_password"


def image_url_for_variant(p, v, is_graphql):
    if is_graphql:
        return None
    for img in (p.get("images") or []):
        if str(v.get("id")) in {str(vid) for vid in (img.get("variant_ids") or [])}:
            return img.get("src")
    return (v.get("featured_image") or {}).get("src")


def main():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    read_conn = psycopg2.connect(DSN)  # separate connection — see backfill_categories.py's own note on this

    cur.execute("SELECT id, slug FROM brands")
    brand_slug = {bid: slug for bid, slug in cur.fetchall()}

    scanned = 0
    changed = 0
    read_cur = read_conn.cursor(name="backfill_images_scan")
    read_cur.itersize = 2000
    read_cur.execute("SELECT id, brand_id, raw_source FROM products")

    write_batch = []

    def flush():
        nonlocal write_batch
        if write_batch:
            psycopg2.extras.execute_batch(
                cur, "UPDATE variants SET image_url = %s WHERE product_id = %s AND native_variant_id = %s",
                write_batch,
            )
            write_batch = []
        conn.commit()

    for pid, brand_id, raw in read_cur:
        scanned += 1
        slug = brand_slug.get(brand_id)
        is_graphql = slug == "cougar"
        p = raw
        raw_variants = (
            [e["node"] for e in (p.get("variants") or {}).get("edges", [])]
            if is_graphql
            else (p.get("variants") or [])
        )
        for v in raw_variants:
            native_vid = str(v.get("id"))
            url = image_url_for_variant(p, v, is_graphql)
            if url:
                write_batch.append((url, pid, native_vid))
                changed += 1
                if len(write_batch) >= 2000:
                    flush()

        if scanned % 10000 == 0:
            print(f"  scanned {scanned} products, {changed} variant image_urls so far")

    flush()
    read_cur.close()
    read_conn.close()

    cur.execute("SELECT count(*) FROM variants WHERE image_url IS NOT NULL")
    total_with_image = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM variants")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    print(f"DONE: scanned {scanned} products, wrote image_url on {changed} variants")
    print(f"Overall: {total_with_image}/{total} variants now have a real image_url ({total_with_image/total*100:.1f}%)")


if __name__ == "__main__":
    main()
