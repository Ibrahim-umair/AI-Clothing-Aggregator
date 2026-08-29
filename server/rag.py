"""Core natural-language search pipeline — port of server/search.js
(runSearch + extractSearchFilters + embedText). Behavior must match
exactly, not just approximately: this is the highest-risk file in the
whole migration, since every hard-won fix from this project's testing
lives in the WHERE-clause/RRF details below.

See server/SEARCH.md for the full design writeup and measured numbers
(pre-migration; update after re-measuring on this service).
"""
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

from db import get_pool
from metrics import LLMCallRecord, Timer
from query_helpers import category_ids_for_search, expand_size_aliases_for_query, resolve_brand_id, to_money
from search_tool import SEARCH_TOOL, SYSTEM_PROMPT

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

openai = AsyncOpenAI() if os.environ.get("OPENAI_API_KEY") else None

# Overridable without a code change (SEARCH_MODEL in server_py/.env) so the
# extraction model can be swapped/rolled back without a deploy.
SEARCH_MODEL = os.environ.get("SEARCH_MODEL", "gpt-5.6-luna")

VALID_GENDER_OVERRIDES = {"Women", "Men", "Boys", "Girls", "Unisex"}

LEG_POOL = 60  # per-leg candidates fed into fusion
FINAL_POOL = 50  # final fused results returned
RRF_K = 60
LEG_WEIGHTS = {"vector": 0.7, "textual": 0.3}

ROW_COLUMNS = """
  p.id, p.title, p.handle,
  b.name AS store_display, b.slug AS store,
  (SELECT pi.url FROM product_images pi WHERE pi.product_id = p.id ORDER BY pi.position LIMIT 1) AS image_url,
  v.price, v.compare_at_price, v.available, v.variant_count
"""
ROW_JOIN = """
  FROM products p
  JOIN brands b ON b.id = p.brand_id
  JOIN LATERAL (
    SELECT vv.current_price AS price, vv.current_compare_at AS compare_at_price,
           (SELECT BOOL_OR(v2.current_available) FROM variants v2 WHERE v2.product_id = p.id) AS available,
           (SELECT COUNT(*) FROM variants v3 WHERE v3.product_id = p.id) AS variant_count
    FROM variants vv WHERE vv.product_id = p.id
    ORDER BY vv.current_price ASC NULLS LAST LIMIT 1
  ) v ON true
"""


async def extract_search_filters(query: str) -> tuple[dict, LLMCallRecord]:
    with Timer() as t:
        completion = await openai.chat.completions.create(
            model=SEARCH_MODEL,
            # Required on the gpt-5.x reasoning models: /v1/chat/completions
            # rejects function tools outright unless reasoning is off. Sent
            # conditionally so SEARCH_MODEL can still be rolled back to a
            # pre-5.x model (gpt-4o-mini), which rejects the parameter.
            **({"reasoning_effort": "none"} if re.match(r"^gpt-5", SEARCH_MODEL) else {}),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            tools=[SEARCH_TOOL],
            tool_choice={"type": "function", "function": {"name": "search_filters"}},
        )
    call = completion.choices[0].message.tool_calls
    if not call:
        raise RuntimeError("model did not call search_filters")
    filters = json.loads(call[0].function.arguments)
    usage = completion.usage
    record = LLMCallRecord(
        model=SEARCH_MODEL,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        latency_ms=t.elapsed_ms,
    )
    return filters, record


async def embed_text(text: str) -> tuple[str, LLMCallRecord]:
    with Timer() as t:
        resp = await openai.embeddings.create(
            model="text-embedding-3-large",
            input=text,
            dimensions=1536,
        )
    vector_literal = "[" + ",".join(str(x) for x in resp.data[0].embedding) + "]"
    record = LLMCallRecord(
        model="text-embedding-3-large",
        input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
        output_tokens=0,
        latency_ms=t.elapsed_ms,
    )
    return vector_literal, record


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


async def run_search(query: str, debug: bool = False, gender_override: str | None = None) -> dict:
    """genderOverride comes from an explicit UI control (the AI Search
    page's Men/Women/Boys/Girls toggle) — when set, it REPLACES whatever
    the LLM extracted from the text, rather than just being a hint the
    model can second-guess. A person who taps "Men" and types "red kurta"
    means Men's kurtas, full stop, even though nothing in that text says
    so — the toggle is a more reliable signal than inference from a query
    that was never asked to mention gender in the first place.
    """
    if openai is None:
        raise RuntimeError("OPENAI_API_KEY not configured")
    query = (query or "").strip()
    if not query:
        raise ValueError("empty query")

    t0 = time.perf_counter()
    import asyncio

    (filters, extract_metrics), (query_vector, embed_metrics) = await asyncio.gather(
        extract_search_filters(query), embed_text(query)
    )
    if gender_override and gender_override in VALID_GENDER_OVERRIDES:
        filters["gender"] = gender_override

    category_ids, category_not_found = await category_ids_for_search(filters.get("gender"), filters.get("categories"))
    if category_not_found:
        result = {
            "response_text": f"{filters['response_text']} No matches found.",
            "filters": filters,
            "total": 0,
            "products": [],
        }
        if debug:
            result["debug"] = {"categoryIds": [], "categoryNotFound": True, "vectorLeg": [], "textualLeg": [], "fused": []}
        return result

    brand_id = await resolve_brand_id(filters.get("brand")) if filters.get("brand") else None

    where = [
        "p.is_active = true AND p.is_browsable = true",
        "EXISTS (SELECT 1 FROM variants va WHERE va.product_id = p.id AND va.current_available = true)",
    ]
    params: list = []

    if category_ids:
        params.append(category_ids)
        where.append(f"p.category_id = ANY(${len(params)}::int[])")
    if brand_id is not None:
        params.append(brand_id)
        where.append(f"p.brand_id = ${len(params)}")
    if _is_number(filters.get("minPrice")):
        params.append(filters["minPrice"])
        where.append(f"(SELECT MIN(vp.current_price) FROM variants vp WHERE vp.product_id = p.id) >= ${len(params)}")
    if _is_number(filters.get("maxPrice")):
        params.append(filters["maxPrice"])
        where.append(f"(SELECT MIN(vp.current_price) FROM variants vp WHERE vp.product_id = p.id) <= ${len(params)}")
    if filters.get("onSale") is True:
        where.append(
            "EXISTS (SELECT 1 FROM variants vo WHERE vo.product_id = p.id AND vo.current_compare_at IS NOT NULL AND vo.current_compare_at > vo.current_price)"
        )
    colors = filters.get("colors") or []
    if colors:
        params.append([str(c).lower() for c in colors])
        where.append(
            f"EXISTS (SELECT 1 FROM variants vc JOIN colors c ON c.id = vc.color_id WHERE vc.product_id = p.id AND lower(c.canonical_name) = ANY(${len(params)}::text[]))"
        )
    sizes = filters.get("sizes") or []
    if sizes:
        params.append(expand_size_aliases_for_query(sizes))
        where.append(
            f"EXISTS (SELECT 1 FROM variants vs WHERE vs.product_id = p.id AND lower(vs.size_label) = ANY(${len(params)}::text[]) AND vs.current_available = true)"
        )
    where.append("p.embedding IS NOT NULL")
    where_sql = " AND ".join(where)

    pool = await get_pool()
    count_sql = f"SELECT COUNT(*) FROM products p WHERE {where_sql}"
    total = await pool.fetchval(count_sql, *params)

    row_select_sql = f"SELECT {ROW_COLUMNS} {ROW_JOIN} WHERE {where_sql}"

    vector_params = [*params, query_vector, LEG_POOL]
    vector_sql = f"{row_select_sql} ORDER BY p.embedding <=> ${len(params) + 1}::vector LIMIT ${len(params) + 2}"

    # plainto_tsquery ANDs every lexeme by default — for a real multi-word
    # query that requires every lexeme present in one product's title +
    # description simultaneously, true for approximately nothing. Convert
    # `&` to `|` on plainto_tsquery's OWN safe tokenization (not hand-
    # parsing raw input) — safe specifically because this only ever reranks
    # WITHIN the already objective-filtered candidate set above, it can
    # never leak the wrong category/gender/price in.
    # Runs on the extracted semantic residual, not the raw query — an empty
    # residual means the query was fully captured by structured filters, so
    # the leg is skipped entirely rather than falling back to raw text
    # (which would reintroduce the "distinctive term diluted to 1-of-N"
    # bug this fix addresses).
    textual_text = (filters.get("semantic_query") or "").strip()
    textual_params = [*params, textual_text, LEG_POOL]
    textual_query_expr = f"to_tsquery('english', replace(plainto_tsquery('english', ${len(params) + 1})::text, ' & ', ' | '))"
    textual_sql = f"""
      {row_select_sql} AND p.search_vector @@ {textual_query_expr}
      ORDER BY ts_rank(p.search_vector, {textual_query_expr}) DESC
      LIMIT ${len(params) + 2}
    """

    import asyncio as _asyncio

    async def _vector_leg():
        # pgvector's HNSW index under a selective WHERE filter can silently
        # return FEWER rows than LIMIT even when more exist. SET must run
        # on the SAME checked-out connection as the query that follows it.
        async with pool.acquire() as conn:
            await conn.execute("SET hnsw.ef_search = 400")
            return await conn.fetch(vector_sql, *vector_params)

    async def _textual_leg():
        if not textual_text:
            return []
        return await pool.fetch(textual_sql, *textual_params)

    vector_rows, textual_rows = await _asyncio.gather(_vector_leg(), _textual_leg())

    # Reciprocal Rank Fusion — weighted 0.7 vector / 0.3 textual. The
    # vector leg's generally-more-reliable semantic judgment is the
    # tiebreaker by default; the real fix for the "furor jeans -> keychain
    # outranked real jeans" case was the category hard-filter above, not
    # this weighting.
    scored: dict[int, dict] = {}
    for leg_name, leg_rows in (("vector", vector_rows), ("textual", textual_rows)):
        for i, row in enumerate(leg_rows):
            rank = i + 1
            contribution = LEG_WEIGHTS[leg_name] / (RRF_K + rank)
            existing = scored.get(row["id"])
            if existing:
                existing["score"] += contribution
                existing["legs"][leg_name] = rank
            else:
                legs = {"vector": None, "textual": None}
                legs[leg_name] = rank
                scored[row["id"]] = {"row": row, "score": contribution, "legs": legs}

    fused = sorted(scored.values(), key=lambda e: e["score"], reverse=True)[:FINAL_POOL]
    rows = [e["row"] for e in fused]

    products = [
        {
            # products.id is bigint — node-postgres serializes it as a
            # string by default; asyncpg returns a native int. Cast to
            # match, same reasoning as routes/products.py.
            "id": str(r["id"]),
            "title": r["title"],
            "store": r["store"],
            "store_display": r["store_display"],
            "image_url": r["image_url"],
            "price": to_money(r["price"]),
            "compare_at_price": to_money(r["compare_at_price"]),
            "currency": "PKR",
            "available": bool(r["available"]),
            "variant_count": int(r["variant_count"] or 0),
        }
        for r in rows
    ]

    # Just the model's confirmation sentence — no appended counts (a
    # "Showing N best matches (M match the filters)" suffix was tried and
    # dropped: M is the raw hard-filter count, mostly noise for a semantic
    # query). `total` is still returned for anything that needs it.
    result = {
        "response_text": filters["response_text"],
        "filters": filters,
        "total": total,
        "products": products,
        # Consumed by main.py's BackgroundTask to log this search — not
        # part of the Node response shape, stripped before the HTTP
        # response is built. See db_conversations.py.
        "_metrics": {
            "extract": extract_metrics,
            "embed": embed_metrics,
            "total_latency_ms": (time.perf_counter() - t0) * 1000,
            "total_matches": total,
            "results_returned": len(products),
        },
    }
    if debug:
        result["debug"] = {
            "categoryIds": category_ids,
            "vectorLeg": [{"id": r["id"], "title": r["title"]} for r in vector_rows],
            "textualLeg": [{"id": r["id"], "title": r["title"]} for r in textual_rows],
            "fused": [{"id": e["row"]["id"], "title": e["row"]["title"], "score": e["score"], "legs": e["legs"]} for e in fused],
        }
    return result
