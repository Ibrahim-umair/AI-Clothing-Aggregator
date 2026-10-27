"""
Search v2 vectors: fills products.embedding_v2 and products.search_vector_v2
for every enriched product (ai_description set by enrich_products.py) that
doesn't have them yet. The original embedding/search_vector columns are
never touched, so search v1 keeps working unchanged.

Embedded text = title + category path + brand + the AI description + AI
tags + the store's own description (shortened). The AI text goes before the
store text because it carries what the store text usually lacks (fit, cut,
print placement) and the store text is often marketing or a size chart.

Keyword text, weighted: title (A), AI tags + AI description (B), store
description (C), so a match in the title or the AI's plain description
counts for more than one buried in marketing copy.

    python embed_products_v2.py            # everything enriched but not embedded
    python embed_products_v2.py --limit 50 # smoke test
"""
import argparse
import os
import sys
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "server" / ".env")

from embed_products import BATCH_SIZE, build_category_paths, embed_batch  # noqa: E402
from load_data import DSN  # noqa: E402

STORE_DESCRIPTION_CHARS = 600
# text-embedding-3-large, USD per 1M tokens (for the cost print).
PRICE_PER_1M = 0.13


def build_text(title, category_path, brand, ai_description, ai_tags, description):
    parts = [
        title or "",
        f"Category: {category_path}" if category_path else "",
        f"Brand: {brand}" if brand else "",
        ai_description or "",
        f"Tags: {', '.join(ai_tags)}" if ai_tags else "",
        (description or "")[:STORE_DESCRIPTION_CHARS],
    ]
    return ". ".join(p for p in parts if p)[:8000]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set (expected in server/.env)")

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    category_paths = build_category_paths(cur)

    # Keyword column first: pure SQL, no API cost.
    cur.execute("""
        UPDATE products SET search_vector_v2 =
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(array_to_string(ai_tags, ' '), '') || ' ' ||
                                             coalesce(ai_description, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'C')
        WHERE ai_description IS NOT NULL AND search_vector_v2 IS NULL
    """)
    print(f"keyword text built for {cur.rowcount} products")
    conn.commit()

    query = """
        SELECT p.id, p.title, p.category_id, b.name, p.ai_description, p.ai_tags, p.description
        FROM products p JOIN brands b ON b.id = p.brand_id
        WHERE p.ai_description IS NOT NULL AND p.embedding_v2 IS NULL
          -- fully sold out: search never shows it, so don't pay to embed it
          AND EXISTS (SELECT 1 FROM variants v WHERE v.product_id = p.id AND v.current_available)
        ORDER BY p.id
    """
    if args.limit:
        query += f" LIMIT {int(args.limit)}"
    cur.execute(query)
    rows = cur.fetchall()
    print(f"{len(rows)} products to embed")

    t0 = time.time()
    chars = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        texts = [build_text(r[1], category_paths.get(r[2]), r[3], r[4], r[5], r[6]) for r in batch]
        chars += sum(len(t) for t in texts)
        vectors = embed_batch(texts)
        psycopg2.extras.execute_batch(
            cur, "UPDATE products SET embedding_v2 = %s::vector WHERE id = %s",
            [("[" + ",".join(str(x) for x in vec) + "]", r[0]) for vec, r in zip(vectors, batch)],
        )
        conn.commit()
        done = start + len(batch)
        if done % 2000 < BATCH_SIZE or done == len(rows):
            print(f"  embedded {done}/{len(rows)}  ({done / (time.time() - t0):.0f}/s)", flush=True)

    # ~4 characters per token is close enough for a cost estimate.
    print(f"embedded {len(rows)} products, ~{chars // 4:,} tokens, ~${chars / 4 / 1e6 * PRICE_PER_1M:.2f}")

    cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = 'idx_products_embedding_v2_hnsw'")
    if not cur.fetchone():
        print("building HNSW index on embedding_v2 ...", flush=True)
        cur.execute("CREATE INDEX idx_products_embedding_v2_hnsw ON products USING hnsw (embedding_v2 vector_cosine_ops)")
        conn.commit()
        print("index built")


if __name__ == "__main__":
    main()
