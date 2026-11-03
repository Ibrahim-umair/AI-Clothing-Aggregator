"""
Shared helpers for the embedding and category scripts: build_category_paths
(category_id -> full path text) and embed_batch (OpenAI text-embedding-3-large
at 1536 dims, with retries). Search vectors are filled by
embed_products_v2.py.

This file used to fill products.embedding for the original search (v1). That
search and its columns were removed on 2026-11-03
(db/migrations/2026-11-03_drop_search_v1.sql); the name stays because many
scripts import these helpers from here.
"""
import time

from openai import OpenAI

EMBED_MODEL = "text-embedding-3-large"
EMBED_DIMENSIONS = 1536
BATCH_SIZE = 100  # products per OpenAI API call
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

