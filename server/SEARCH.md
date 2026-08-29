# Natural-language search — `POST /api/search`

Built overnight 2026-08-29, following the RAG architecture discussed and agreed
on beforehand — not a unilateral design, this is that plan implemented. See
the conversation for the full reasoning; this file is the "how to run/verify
it" reference, same role as `db/scraper/COMMANDS.md`.

## What it does

```
POST /api/search
{"query": "cozy warm sweaters for women under 5000"}
```

One request does, **concurrently**, not sequentially:
1. An OpenAI tool-call (`gpt-4o-mini`, forced `search_filters` function,
   `strict: true`) extracts objective filters (gender/price/brand/sale/
   sizes/colors) plus a semantic residual and a confirmation sentence — one
   call, and the model's job ends there. It never sees the actual product
   results, so there's no second round-trip to narrate anything.
2. The raw query text gets embedded (`text-embedding-3-large`, truncated to
   1536 dims via OpenAI's `dimensions` param — **must** match
   `db/embed_products.py`'s dimensions or the vector distance is
   meaningless).

Those two calls were originally sequential (~2.5s combined) — made
concurrent since they don't depend on each other, cutting to whichever one is
slower (~1.5-2s as measured, see below). The DB step is one query: the
extracted filters become a SQL `WHERE`, narrowing the candidate set; the
embedding drives `ORDER BY p.embedding <=> $vector` within that already-
narrowed set — filter-then-rank, not two searches merged afterward.

Response:
```json
{
  "response_text": "Here are cozy warm sweaters for women under Rs. 5,000. Showing 50 best matches (3054 match the filters).",
  "filters": { "gender": "Women", "maxPrice": 5000, "semantic_query": "cozy warm sweaters", ... },
  "total": 3054,
  "products": [ /* same shape as GET /api/products */ ]
}
```

`total` is every product matching the HARD filters (gender/price/brand/etc)
— it does NOT mean "this many are semantically relevant," since vector
ranking only reorders the candidate pool (capped at 50), it never narrows
the SQL row count. `response_text` is phrased to reflect what's actually
shown, not the raw filter-match count, for exactly this reason — see the
comment above the response in `server/index.js` if that phrasing needs
revisiting.

## Setup

- `server/.env` needs `OPENAI_API_KEY` (loaded automatically at startup via
  Node's built-in `process.loadEnvFile()` — no `dotenv` dependency). Same
  persistence lesson as `db/scraper/.env`/`COUGAR_STOREFRONT_TOKEN`: a key
  set only in a shell session is gone next time the process starts.
- Requires `db/embed_products.py` to have run — `/api/search` silently
  excludes any product with `embedding IS NULL` (the `WHERE ... AND
  p.embedding IS NOT NULL` clause), so an incomplete embedding pass just
  means a smaller, still-correct candidate pool, not broken results.
- pgvector extension: installed into the live `libas-postgres` container via
  `apt-get install postgresql-16-pgvector` (see the comment at the top of
  `db/init/01_schema.sql` — the base `postgres:16` image doesn't have it,
  a fresh setup needs the same package or a `pgvector/pgvector:pg16` image).

## Running it

```powershell
cd server
node index.js          # picks up .env automatically
```

```powershell
curl -X POST http://localhost:4000/api/search -H "Content-Type: application/json" -d '{"query":"formal kurta for a wedding, men, under 8000"}'
```

## Measured, finished-state numbers

Embedding pass completed (113,322/113,322), HNSW index built
(`idx_products_embedding_hnsw`, cosine ops), server restarted clean:

- **DB query alone**: ~35-50ms (was ~650ms brute-force before the index —
  see the `hnsw.ef_search` note below for why it's 50ms and not the ~3ms a
  plain unfiltered HNSW lookup would be).
- **Full `/api/search` request, steady state**: ~1.4-1.6s. Essentially all
  of this is the OpenAI extraction call (`gpt-4o-mini` tool-call, measured
  standalone at ~1.6s) — the embedding call runs concurrently with it (see
  the code comment above the handler) and the DB step is now negligible.
  **The extraction call is the one remaining latency lever** if this needs
  to get faster — a smaller/faster model, or the regex/lookup fast-path
  for common query shapes discussed earlier (skip the LLM call entirely
  when a query is simple enough), are the next places to look, not the
  retrieval side.

**A real pgvector gotcha found and fixed while measuring this:** HNSW under
a selective `WHERE` filter can silently return FEWER rows than `LIMIT` even
when more exist — it stops exploring the index graph after
`hnsw.ef_search` candidates (default 40), regardless of how many passed the
filter. Measured directly on the "Women + under Rs. 5,000" filter above:
7 of 50 real matching rows at the default `ef_search`, 50/50 at
`ef_search = 400` (~50ms, still negligible). The fix required checking out
a dedicated client via `pool.connect()` rather than two separate
`pool.query()` calls — `SET` only affects the session that runs it, and the
pool doesn't guarantee two `pool.query()` calls land on the same
connection. See the code comment directly above where `client = await
pool.connect()` is used.

## Hybrid retrieval (vector + textual, fused with RRF)

Added after the initial build: `/api/search` now runs the objective-filtered
candidate set through TWO independent legs — vector similarity (as before)
and Postgres full-text search (`search_vector`, a generated+`STORED`
`tsvector` column with a GIN index — this stack's BM25-equivalent; pgvector
has no native BM25, and `ts_rank` over a GIN index is the standard
in-Postgres analog, no new infra) — then fuses them with Reciprocal Rank
Fusion (`score = Σ weight/(60 + rank)` per leg an id appears in). Both legs
run concurrently (`Promise.all`), each pulling 60 candidates; fused down to
50 for the response.

Weighted 0.7 vector / 0.3 textual rather than an even split — **found and
verified a real ranking failure while testing this build**: searching
"furor jeans" ranked "Furor Jeans Club Keychain" (a rubber keychain,
`product_type: "Key Chains"`, whose title happens to literally contain the
word "Jeans" as Furor's own product-line naming) above actual jeans.
Weighting toward vector didn't fully fix this one — traced it further and
found the vector leg *itself* ranks the keychain #1 for this query (cosine
0.6255 vs. 0.6239 for the top real jeans match, measured directly), because
general-purpose text embeddings are still meaningfully influenced by a
literal shared word ("Jeans") between the query and the product's own
embedded text, not purely conceptual similarity. **This is not an RRF bug —
it's the direct, now-confirmed consequence of the `gender`-only filter
limitation already flagged below**: there's no category/product-type hard
filter to rule out "Keychain" when someone is clearly asking for the
Bottomwear "Jeans" leaf. Left unfixed rather than patched further tonight —
fixing it properly means deciding whether to extend extraction with a
category signal, which is a real scope question, not a 3am judgment call to
make alone. The 0.7/0.3 weighting is kept because it's still a reasonable
general default (vector genuinely is more reliable on average, this
specific case just also has a literal-word collision no weighting alone
resolves) — see the code comment above the RRF fusion block.

## Known limitations (v1, not yet addressed)

- **No conversational/session state.** Each request is stateless — no
  memory of a prior search's filters for follow-ups ("cheaper", "the second
  one"). That was explicitly designed as a *later* layer, not part of this
  build — see the conversation.
- **`gender` is the only taxonomy filter the extraction model can set** —
  branch/sub/category (e.g. specifically "Upperwear > T-Shirt", or ruling
  out "Accessories" entirely for a bottomwear query) are deliberately left
  to semantic ranking rather than making the model navigate the full
  category tree, which would need the whole tree fed into every extraction
  call. See the "Furor Jeans Club Keychain" case directly above — this is
  now a confirmed real gap, not just a theoretical one, and the next
  concrete thing worth deciding on.
- **Not touched:** the existing `GET /api/products` endpoint. This is a
  fully separate route reusing its small helper functions
  (`categoryIdsFromQuery`, `resolveBrandId`, `expandSizeAliasesForQuery`) —
  zero risk to the existing, working product-listing/filter UI.
