"""
One-time fix-up for the full load already sitting in Postgres: recomputes
each product's category using the corrected classify()/guess_gender() (see
load_data.py — the original guess_gender() matched "men" as a plain
substring of "women", so every women's product silently landed in the men's
bucket, and Unisex-defaulted Western/Eastern products had nowhere to go in
CATEGORY_TREE and were left with category_id = NULL).

Only touches products.category_id — variants/images/prices are untouched,
so this is much cheaper than re-running the full load.
"""
import json
import os
import re
import psycopg2
import psycopg2.extras

from load_data import CATEGORY_TREE, classify, strip_html

# Same env-var convention as server/db.py, so this can run against
# production (real host/password from SSM) without editing the file —
# falls back to the local dev defaults when unset.
DSN = (
    f"host={os.environ.get('PGHOST', 'localhost')} "
    f"port={os.environ.get('PGPORT', '5433')} "
    f"dbname={os.environ.get('PGDATABASE', 'libas')} "
    f"user={os.environ.get('PGUSER', 'libas')} "
    f"password={os.environ.get('PGPASSWORD', 'libas_dev_password')}"
)


def main():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    # A named (server-side) cursor's portal lives inside one transaction;
    # committing on ANY cursor sharing that connection ends the transaction
    # and invalidates it mid-scan. Reads and writes need separate
    # connections so the write-side commits don't kill the read scan.
    read_conn = psycopg2.connect(DSN)

    # Rebuild the same category_id / leaf_lookup maps load_data.py produced,
    # by reading back what's already in the categories table (no re-insert).
    cur.execute("SELECT id, parent_id, name, slug FROM categories")
    rows = cur.fetchall()
    by_id = {r[0]: {"parent_id": r[1], "name": r[2], "slug": r[3]} for r in rows}
    children = {}
    for cid, node in by_id.items():
        children.setdefault(node["parent_id"], []).append(cid)

    def child_by_slug(parent_id, slug):
        for cid in children.get(parent_id, []):
            if by_id[cid]["slug"] == slug:
                return cid
        return None

    category_id = {}  # (parent_id, slug) -> id
    for cid, node in by_id.items():
        category_id[(node["parent_id"], node["slug"])] = cid

    leaf_lookup = {}  # (gender, branch, sub, leaf_name) -> id
    for gender, branches in CATEGORY_TREE.items():
        g_id = child_by_slug(None, gender.lower())
        for branch, content in branches.items():
            b_slug = re.sub(r"[^a-z]+", "-", branch.lower())
            b_id = child_by_slug(g_id, b_slug) if g_id is not None else None
            if isinstance(content, dict):
                for sub, leaves in content.items():
                    s_slug = re.sub(r"[^a-z]+", "-", sub.lower())
                    s_id = child_by_slug(b_id, s_slug) if b_id is not None else None
                    for name, slug in leaves:
                        l_id = child_by_slug(s_id, slug) if s_id is not None else None
                        if l_id is not None:
                            leaf_lookup[(gender, branch, sub, name)] = l_id
            else:
                for name, slug in content:
                    l_id = child_by_slug(b_id, slug) if b_id is not None else None
                    if l_id is not None:
                        leaf_lookup[(gender, branch, None, name)] = l_id

    cur.execute("SELECT slug FROM brands WHERE id = 15")  # sanity: cougar is graphql
    cur.execute("SELECT id, slug FROM brands")
    brand_slug = {bid: slug for bid, slug in cur.fetchall()}

    changed = 0
    deleted = 0
    scanned = 0
    read_cur = read_conn.cursor(name="backfill_scan")  # server-side cursor: 96k JSONB rows won't fit comfortably client-side
    read_cur.itersize = 2000
    read_cur.execute("SELECT id, brand_id, title, category_id, raw_source FROM products")

    write_batch = []
    delete_batch = []

    def flush():
        nonlocal write_batch, delete_batch
        if write_batch:
            psycopg2.extras.execute_batch(
                cur, "UPDATE products SET category_id = %s WHERE id = %s", write_batch
            )
            write_batch = []
        if delete_batch:
            # A product classify() now excludes (e.g. a QA "(TEST)" listing
            # or a checkout packaging bag added to ACCESSORY_RE's exclusion
            # list after this row was already loaded) needs to actually
            # disappear, not just keep its stale category_id — the original
            # loader never inserts an excluded product at all, so a re-scan
            # here has to delete it to match. ON DELETE CASCADE on
            # variants/images/product_pieces handles the rest.
            psycopg2.extras.execute_batch(
                cur, "DELETE FROM products WHERE id = %s", [(pid,) for pid in delete_batch]
            )
            delete_batch = []
        conn.commit()

    for pid, brand_id, title, old_cat_id, raw in read_cur:
        scanned += 1
        slug = brand_slug.get(brand_id)
        is_graphql = slug == "cougar"
        p = raw
        if is_graphql:
            product_type = p.get("productType") or ""
            tags_raw = p.get("tags") or []
            tags = tags_raw if isinstance(tags_raw, list) else []
            vendor = p.get("vendor") or ""
            description = strip_html(p.get("descriptionHtml"))
        else:
            product_type = p.get("product_type") or ""
            tags_raw = p.get("tags", "")
            tags = tags_raw if isinstance(tags_raw, list) else [t.strip() for t in tags_raw.split(",") if t.strip()]
            vendor = p.get("vendor") or ""
            description = strip_html(p.get("body_html"))

        cls = classify(slug, p, title or "", product_type, ",".join(tags), vendor, description or "")
        if cls is None:
            delete_batch.append(pid)
            deleted += 1
            if len(delete_batch) >= 2000:
                flush()
            continue

        cat_id = leaf_lookup.get((cls["gender"], cls["branch"], cls.get("sub"), cls["leaf"]))
        gender_root_id = category_id.get((None, cls["gender"].lower()))
        if cat_id is None:
            branch_slug = re.sub(r"[^a-z]+", "-", cls["branch"].lower())
            cat_id = category_id.get((gender_root_id, branch_slug))
        if cat_id is None:
            cat_id = gender_root_id

        if cat_id != old_cat_id:
            write_batch.append((cat_id, pid))
            changed += 1
            if len(write_batch) >= 2000:
                flush()

        if scanned % 10000 == 0:
            print(f"  scanned {scanned}, changed so far {changed}")

    flush()
    read_cur.close()
    read_conn.close()
    cur.close()
    conn.close()
    print(f"DONE: scanned {scanned} products, updated category_id on {changed}, deleted {deleted} newly-excluded")


if __name__ == "__main__":
    main()
