# Natural-language search — `POST /api/search`

Originally built 2026-08-29 on Node/Express; migrated to Python/FastAPI
2026-08-29/30 (see `MIGRATION_REPORT.md` at the repo root for the migration
itself — this file is the pipeline design reference, same role as
`db/scraper/COMMANDS.md`). The architecture and every hard-won fix below
carried over unchanged; only the language/framework did.

## What it does

```
POST /api/search
{"query": "cozy warm sweaters for women under 5000", "gender": "Women"}
```

One request does, **concurrently** (`asyncio.gather`, was `Promise.all`),
not sequentially:
1. An OpenAI tool-call (`gpt-5.6-luna`, forced `search_filters` function,
   `strict: true`, `reasoning_effort: "none"` — required on gpt-5.x reasoning
   models for function-tool calls) extracts objective filters
   (gender/category/price/brand/sale/sizes/colors) plus a semantic residual,
   a confirmation sentence, and 2-4 next-query refinement suggestions — one
   call, and the model's job ends there. It never sees the actual product
   results.
2. The raw query text gets embedded (`text-embedding-3-large`, truncated to
   1536 dims via OpenAI's `dimensions` param — **must** match
   `db/embed_products.py`'s dimensions or the vector distance is
   meaningless).

The DB step: the extracted filters (gender, category — expanded through the
taxonomy tree, price, brand, size, color) become a hard SQL `WHERE`,
narrowing the candidate set; TWO retrieval legs then run concurrently within
that narrowed set (see "Hybrid retrieval" below), fused with RRF.

Response:
```json
{
  "response_text": "Here are cozy warm sweaters for women under Rs. 5,000.",
  "filters": {
    "gender": "Women", "categories": ["Sweater"], "maxPrice": 5000,
    "semantic_query": "cozy warm", "suggested_refinements": ["Crew neck", "Turtleneck", "Cardigan"],
    "..." : "..."
  },
  "total": 85,
  "products": [ /* same shape as GET /api/products, id as a STRING (see below) */ ]
}
```

`total` is every product matching the HARD filters — it does NOT mean "this
many are semantically relevant," since ranking only reorders the candidate
pool (capped at 50), it never narrows the SQL row count.

## Setup

- `server/.env` needs `OPENAI_API_KEY` (loaded via `python-dotenv`, same
  persistence lesson as `db/scraper/.env` — a key set only in a shell
  session is gone next time the process starts).
- `pip install -r server/requirements.txt` (fastapi, uvicorn, asyncpg,
  pydantic, openai, python-dotenv).
- Requires `db/embed_products.py` to have run — same as before, an
  incomplete embedding pass just means a smaller, still-correct candidate
  pool.
- pgvector extension: same as before, installed into the live
  `libas-postgres` container.
- `docker compose up -d` in `db/` also brings up Grafana now (see
  "Monitoring" below) — reuses the same Postgres instance, no separate DB.

## Running it

```powershell
cd server
python -m uvicorn main:app --port 4000 --reload
```

```powershell
curl -X POST http://localhost:4000/api/search -H "Content-Type: application/json" -d '{"query":"formal kurta for a wedding, men, under 8000"}'
```

CLI introspection tool (every stage visible — extracted filters, both legs'
independent rankings, final RRF fusion), same as before, now interactive
about gender rather than never passing one:
```powershell
python cli.py "furor jeans" --gender=1
```

## A real driver gotcha found during the migration

`products.id` is `bigint`. Node's `pg` driver serializes bigint columns as a
**string** by default (avoiding silent precision loss past 2^53); Python's
`asyncpg` returns a native `int` (no precision issue in Python, but a
different wire shape). Every place a product id is returned is now cast
`str(...)` explicitly to match the old contract exactly — a strict `===`
against a URL param (always a string) would otherwise have silently broken.
Verified via a byte-for-byte diff against the live Node server before
cutover (see `MIGRATION_REPORT.md`).

## Measured numbers (post-migration)

- **DB query alone**: ~35-50ms, unchanged (same SQL, same HNSW index).
- **Full `/api/search` request, steady state**: ~2.2s average (101-query
  parity run), vs. ~1.5-2.7s measured on the Node version — comparable, not
  a regression. Still essentially all OpenAI extraction-call latency; still
  the one lever if this needs to get faster.

**The pgvector `hnsw.ef_search` gotcha** (HNSW under a selective `WHERE`
filter silently returns fewer rows than `LIMIT` unless `ef_search` is raised
— default 40 returned 7/50 real matches on a real filtered query, `400`
returns 50/50 at ~50ms) carried over unchanged: `SET hnsw.ef_search = 400`
runs via `asyncpg`'s `pool.acquire()` (a dedicated connection), same
reasoning as the old `pool.connect()` — `SET` only affects the session that
issued it.

## Hybrid retrieval (vector + textual, fused with RRF) — unchanged

Both legs (vector similarity, Postgres full-text via `search_vector`/
`ts_rank`) run concurrently, 60 candidates each, fused with RRF
(`score = Σ weight/(60 + rank)`, weighted 0.7 vector / 0.3 textual) down to
50. The textual leg matches on `semantic_query` only (not the raw query) and
is skipped entirely when that residual is empty — re-matching an
already-hard-filtered category/price/brand word was diluting the one
genuinely distinctive term to 1-of-N signal. `plainto_tsquery`'s `&` is
converted to `|` (safe because it only reranks within the already-filtered
set) since requiring every lexeme present in one product's text simultaneously
matched almost nothing for real multi-word queries.

**The "furor jeans -> keychain ranked above real jeans" issue mentioned in
earlier drafts of this doc is fixed** — `categories` is now a hard
structured filter (not left to semantic ranking alone), resolved through the
full taxonomy tree including grouping nodes (`"Upperwear"`, `"Western"`,
...) expanded to their leaf descendants. A related bug found via 100-query
testing and fixed: when the model names both a leaf AND its own ancestor
grouping node together (e.g. `["3-Piece","Unstitched"]`), the ancestor's
much larger descendant set used to swallow the leaf's precision entirely —
`categoryIdsForSearch`/`category_ids_for_search` now prunes ancestors when a
descendant is also present in the same request.

## Monitoring (new)

Every search is logged asynchronously (FastAPI `BackgroundTasks`, fires
after the response is already sent — logging must never add latency to a
request) to a `search_logs` table in the same Postgres database: query text,
resolved filters, total matches, per-OpenAI-call token counts/latency/cost.
Grafana (`http://localhost:3001`, admin/admin) is provisioned automatically
via `docker compose up -d` in `db/` — dashboard "Libas Search Quality":
recent searches, zero-result-rate (our proxy for search quality — this
pipeline doesn't generate a text answer for an LLM judge to score, unlike a
FAQ-style RAG app), gender/model breakdown, response-time/cost/token-usage
over time.

**OpenTelemetry is deliberately not built yet** — planned for when this
goes to production, not part of this pass. One hook-point comment marks
where it goes in `main.py`'s `lifespan`.

## Known limitations (still open, not part of this migration)

- **No conversational/session state.** Each request is stateless. The
  "suggested_refinements" next-query chips work around this by folding the
  refinement into the query TEXT (a fresh, complete search), not by the
  backend remembering anything — see the AI Search page's chat-session UI.
- **Color filtering under-recalls.** `colors` matches an EXACT lowercase
  `canonical_name` — the `colors` table has ~1,784 raw, unnormalized store
  spellings ("Blue", "Sky Blue", "Royal Blue", "Navy Blue" all separate
  rows), so a "blue" filter misses everything not spelled exactly "blue"
  (~40% average recall loss measured across 12 real colors). Known,
  documented, not touched by this migration — needs a real alias/
  normalization scheme, scoped separately.
- **"Kids" has no single gender value.** A query like "kids shoes" can't be
  expressed as Boys ∪ Girls in the extraction schema's single-value
  `gender` field — the AI Search page's Kids-mode toggle works around this
  by requiring an explicit Boys/Girls pick, but a bare-text "kids" query
  with no UI override still resolves too narrowly. Two of the 101 parity
  test queries fail for exactly this reason (documented, not a regression).
