# Node → Python/FastAPI migration — overnight report

Done while you slept, on an isolated git worktree/branch — nothing in your
main working directory was touched. This is a review-and-merge situation,
not something already live.

**Branch:** `worktree-agent-af4226b296b8fda97` (6 commits, one per phase,
each independently revertable — `git log --oneline` on this branch shows
them in order).

**Bottom line: 97.2% parity, exact match to the pre-migration Node
baseline, zero errors, same two known (unrelated, pre-existing) failures.**
Full details below.

## What changed

`server/` is now Python/FastAPI instead of Node/Express. Same file-per-
purpose structure Alexey Grigorev uses in his LLM Zoomcamp work (blending
his `fitness-assistant` repo's — the only one of his with a *working*
Docker+Grafana setup — approach with the cleaner file split from the
current official `05-monitoring` course module):

```
server/
  main.py              - FastAPI app + router registration
  models.py            - pydantic request/response schemas
  routes/
    search.py, products.py, taxonomy.py, brands.py, health.py
  rag.py                - the search orchestrator (was search.js's runSearch)
  search_tool.py         - OpenAI tool schema + system prompt (copied verbatim)
  metrics.py             - token/cost/latency capture (NEW)
  db.py                  - asyncpg pool
  db_conversations.py    - search_logs table + logging (NEW)
  query_helpers.py       - category/brand/size resolution
  taxonomy_tree.py        - category tree cache + resolution
  cli.py                  - port of debug_search.js
  requirements.txt
tests/
  test_parity.js          - the 101-query harness, now HTTP-based
db/
  docker-compose.yml (extended) + monitoring/grafana/...  - NEW
```

`db/` (scraper, `classify()`, loaders) was never touched — already Python.

## Verification — how I know this is safe

Every phase was checked against the real, running Node server before
moving to the next one (both ran side by side, Node on :4000, this on
:8000, for direct diffing):

1. **DB/taxonomy layer** — category tree loads (243 rows), the
   ancestor-pruning fix holds, brand resolution matches.
2. **The search pipeline** — same extraction schema, same RRF weights
   (0.7/0.3, k=60), same `hnsw.ef_search=400` trick, same textual-leg
   `&`→`|` conversion, same empty-`semantic_query` skip. Spot-checked
   against real queries via the ported CLI.
3. **All 7 routes** — diffed real responses byte-for-byte against the live
   Node server: `/api/products`, `/api/products/:id`, `/api/taxonomy`,
   `/api/categories/featured`, `/api/search` all identical. **Caught one
   real bug this way**: `products.id` is `bigint`, and Node's `pg` driver
   serializes that as a string while Python's `asyncpg` returns a native
   int — fixed with an explicit `str()` cast everywhere an id is returned,
   or a strict `===` against a URL param would have silently broken
   favourites/routing.
4. **Monitoring** — ran real searches through the live service, confirmed
   `search_logs` rows land correctly, then hit Grafana's own query API
   with each dashboard panel's exact SQL and confirmed all 5 query shapes
   (table/gauge/2×timeseries/barchart) return data with zero errors.
5. **Full parity run** — the exact same 101 hand-written queries and
   ground-truth-from-Postgres checks used to validate the Node version,
   now hitting the Python service over HTTP:

   **97.2% precision (1396/1436), 0 errors** — same number as the Node
   baseline. The only two failures are the same two already-documented
   "kids" gender-schema-gap queries (not a regression — see
   `server/SEARCH.md`'s "Known limitations").
6. **Cutover** — only performed after #5 passed. Old Node files deleted,
   `server_py/` renamed to `server/`. Re-ran a smoke test on the final,
   renamed path to make sure nothing broke in the move — it didn't.

## How to run it

```powershell
# 1. Postgres + Grafana (Grafana is new; Postgres is the same one you already have)
cd db
docker compose up -d

# 2. API
cd ../server
pip install -r requirements.txt
python -m uvicorn main:app --port 4000 --reload
# (or: cd frontend && npm run dev:api — same thing, already updated)

# 3. Frontend — unchanged
cd ../frontend
npm run dev        # or npm run dev:all to run both
```

Grafana: `http://localhost:3001`, login `admin`/`admin` (change it if this
ever leaves your machine). Dashboard "Libas Search Quality" is already
there — datasource and dashboard are both provisioned automatically via
YAML, nothing to click through manually. It'll be empty until real searches
happen (I cleared my own test rows before finishing).

CLI debug tool, same as before, now asks interactively:
```powershell
cd server
python cli.py "furor jeans" --gender=1
```

## What's deliberately NOT done

- **OpenTelemetry.** You said this is for when it goes to prod, not
  tonight — Postgres+Grafana only. One comment in `main.py`'s `lifespan`
  marks where it would hook in. When you're ready: the article you found
  (aishippingblog) and Alexey's lesson 14 both point at the same standard
  shape (OTel Collector → Prometheus/Tempo/Loki → this same Grafana), and
  he names Logfire/Langfuse/Phoenix as the higher-level tools people
  actually build on top of raw OTel for LLM apps specifically.
- **Color filtering's ~40% recall gap** (found during earlier testing,
  unrelated to this migration) — carried over unchanged, still open,
  still needs a real alias/normalization decision, not touched here.
- **The "kids" gender gap** — also carried over unchanged; the frontend's
  Kids-mode toggle already works around it for UI-driven searches, but a
  bare-text "kids" query with no explicit gender still resolves too
  narrowly. Both of these were pre-existing and out of scope for a
  language migration.

## Merging this

This is a real content swap on `server/`, not a simple rename, so review
it like you would any other PR — but every commit is a checkpoint if you
want to look at the migration one phase at a time rather than all at once.
Once you're happy: merge the branch (or cherry-pick/rebase, your call) into
`master`, then remove the worktree (`git worktree remove` from the main
directory) when you're done with it.
