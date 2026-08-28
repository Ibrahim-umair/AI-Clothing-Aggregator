"""
One-time (plus incremental) embedding pass: fills products.embedding for every
product missing one, using OpenAI text-embedding-3-large truncated to 1536
dims (see the comment on the column in db/init/01_schema.sql for why).

Embedded text = title + full category path + brand + description. Price and
other numeric fields are deliberately excluded — those are the structured
filter path's job (see the RAG architecture discussion), not semantic
search's; embedding a number doesn't create meaningful similarity the way a
sentence does.

Safe to re-run: only embeds rows where embedding IS NULL, so it can resume
after an interruption or pick up newly-scraped products without re-paying for
ones already embedded.

    python embed_products.py            # embed every product missing one
    python embed_products.py --limit 50 # smoke-test on a small batch first
"""
import argparse
import os
import sys
import time

import psycopg2
import psycopg2.extras
from openai import OpenAI

from load_data import DSN

EMBED_MODEL = "text-embedding-3-large"
EMBED_DIMENSIONS = 1536
BATCH_SIZE = 100  # products per OpenAI API call
DB_COMMIT_EVERY = 500  # products per DB commit
MAX_RETRIES = 5

client = OpenAI()


def build_category_paths(cur):
    """category_id -> "Gender > Branch > Sub > Leaf" (3 or 4 segments —
    Accessories/Fragrance & Beauty have no Sub level, Western/Eastern do —
    so this walks parent_id per row rather than assuming a fixed depth."""
    cur.execute("SELECT id, parent_id, name FROM categories")
    by_id = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    paths = {}
    for cid in by_id:
        chain = []
        node = cid
        while node is not None:
            parent_id, name = by_id[node]
            chain.append(name)
            node = parent_id
        paths[cid] = " > ".join(reversed(chain))
    return paths


def build_text(title, description, category_path, brand_name):
    parts = [title or "", f"Category: {category_path}" if category_path else "",
             f"Brand: {brand_name}" if brand_name else "", description or ""]
    return ". ".join(p for p in parts if p)[:8000]  # stay well under the 8191-token input cap


def embed_batch(texts):
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=texts, dimensions=EMBED_DIMENSIONS)
            return [d.embedding for d in resp.data]
        except Exception as e:
            wait = 2 ** attempt
            print(f"  embed_batch error (attempt {attempt+1}/{MAX_RETRIES}): {e} — retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError("embed_batch: exhausted retries")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only embed this many products (smoke test)")
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set — aborting.")
        sys.exit(1)

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    category_paths = build_category_paths(cur)

    read_conn = psycopg2.connect(DSN)
    read_cur = read_conn.cursor(name="embed_scan")
    read_cur.itersize = BATCH_SIZE

    query = """
        SELECT p.id, p.title, p.description, p.category_id, b.name AS brand_name
        FROM products p
        JOIN brands b ON b.id = p.brand_id
        WHERE p.embedding IS NULL
        ORDER BY p.id
    """
    if args.limit:
        query += f" LIMIT {int(args.limit)}"
    read_cur.execute(query)

    total_done = 0
    t0 = time.time()
    batch_rows = []

    def flush(rows):
        nonlocal total_done
        if not rows:
            return
        texts = [build_text(r[1], r[2], category_paths.get(r[3]), r[4]) for r in rows]
        vectors = embed_batch(texts)
        # pgvector has no native psycopg2 adapter registered here (avoiding
        # the extra `pgvector` pip dependency for one column) — its text
        # input format is a plain bracketed float list, so pass that as a
        # string and cast explicitly.
        updates = [("[" + ",".join(str(x) for x in vec) + "]", r[0]) for vec, r in zip(vectors, rows)]
        psycopg2.extras.execute_batch(
            cur, "UPDATE products SET embedding = %s::vector WHERE id = %s", updates
        )
        conn.commit()
        total_done += len(rows)
        elapsed = time.time() - t0
        rate = total_done / elapsed if elapsed > 0 else 0
        print(f"  embedded {total_done} so far ({rate:.1f}/s)")

    for row in read_cur:
        batch_rows.append(row)
        if len(batch_rows) >= BATCH_SIZE:
            flush(batch_rows)
            batch_rows = []

    flush(batch_rows)

    read_cur.close()
    read_conn.close()
    cur.close()
    conn.close()
    print(f"DONE: embedded {total_done} products in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
