"""Search v2 (backend-revamp): one LLM call plans the search, then plain
database retrieval does the rest. Runs beside search v1 (rag.py), which is
untouched; routes/search.py picks one per request (SEARCH_ENGINE env var,
or the request's `engine` field).

What's different from v1, and why (agreed 2026-10-27):

1. Query rewriting. v1 shrank the query to a few leftover keywords, which
   threw away what vague queries mean. v2 rewrites it into a descriptive
   product query ("baggy tee" -> "loose relaxed oversized t-shirt";
   "mehndi in December" -> festive, warm options).
2. Multi-search. An outfit or occasion query becomes up to 4 searches, one
   per product type, returned as separate groups.
3. Fit and other attributes without new categories. The plan carries
   must-have phrases (rank higher) and must-not phrases (removed). They're
   matched against the AI-written product text (products.ai_description /
   ai_tags, see db/enrich_products.py), which states fit plainly in
   consistent words, never against brand marketing text.
4. Category stays a hard filter, but only at the level the shopper named,
   and never ends in zero results: if the category isn't found or results
   are thin, the same search runs without it and fills in as alternatives.
5. Color by family and in stock. "olive" matches Dark Olive / Army Green /
   DK.OLIVE (colors.families, db/map_color_families.py) and only counts a
   color that is actually in stock.

Hard filters are only for facts we know for certain: gender, size (in
stock), price, sale, color (in stock), brand, product type. Everything
vague stays soft.
"""
import asyncio
import json
import os
import re
import time

from db import get_pool
from metrics import LLMCallRecord, Timer
from query_helpers import category_ids_for_search, expand_size_aliases_for_query, resolve_brand_id, to_money
from rag import RRF_K, LEG_WEIGHTS, SEARCH_MODEL, VALID_GENDER_OVERRIDES, diversify, openai
from search_tool import KNOWN_CATEGORIES
from taxonomy_tree import get_tree

LEG_POOL = 80            # candidates per leg, per sub-search
GROUP_SIZE = 40          # results returned per group
MIN_RESULTS = 12         # fewer than this with a category filter -> add alternatives
MAX_SEARCHES = 4
MAX_PER_BRAND_IN_LEG = 12
# A must-have hit is worth about as much as moving from rank ~20 to rank 1
# in the vector leg, so a matching product jumps ahead of near-equal ones
# without overriding relevance outright.
MUST_HAVE_BONUS = 0.004

# Test scoping: SEARCH_V2_BRAND_SCOPE=charcoal,zellbury,outfitters limits v2
# to the brands enriched so far. Empty = all brands.
BRAND_SCOPE = [s.strip() for s in os.environ.get("SEARCH_V2_BRAND_SCOPE", "").split(",") if s.strip()]

# Same list as db/map_color_families.py (hues + shades).
COLOR_FAMILIES = ["black", "white", "grey", "blue", "green", "yellow", "orange", "red",
                  "pink", "purple", "brown", "beige", "gold", "silver", "multicolor",
                  "navy", "sky blue", "teal", "turquoise", "olive", "mint", "mustard",
                  "rust", "maroon", "peach", "lilac", "khaki", "camel", "cream",
                  "off white", "charcoal"]

PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "plan_search",
        "description": "Plan product searches for a shopper's query on a Pakistani apparel marketplace.",
        "parameters": {
            "type": "object",
            "properties": {
                "gender": {"type": ["string", "null"], "enum": ["Women", "Men", "Boys", "Girls", "Unisex", None],
                           "description": "Who it's for, if stated or clearly implied. null otherwise."},
                "minPrice": {"type": ["number", "null"]},
                "maxPrice": {"type": ["number", "null"],
                             "description": "Only a stated number ('under 5000'). 'cheap' is not a number: null."},
                "brand": {"type": ["string", "null"],
                          "description": "Only a brand the shopper names: Breakout, Cambridge, Charcoal, Cougar, "
                                         "Diners, Edenrobe, Engine Clothing, Equator, Furor, Lama, Meme, Monark, "
                                         "ONE (Be-One), Outfitters, Royal Tag, Uniworth, Zellbury. null otherwise."},
                "sizes": {"type": "array", "items": {"type": "string"}},
                "colors": {"type": "array", "items": {"type": "string", "enum": COLOR_FAMILIES},
                           "description": "Only colors the shopper explicitly asks for, as families. "
                                          "'olive green' -> ['olive']; 'any green' -> ['green']."},
                "onSale": {"type": "boolean"},
                "searches": {
                    "type": "array",
                    "description": "1 search normally; 2-4 only for outfits, occasions or several product types.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Short group title, e.g. 'Kurtas'."},
                            "query": {"type": "string", "description": "Rewritten descriptive product query."},
                            "categories": {"type": "array", "items": {"type": "string", "enum": KNOWN_CATEGORIES}},
                            "must_have": {"type": "array", "items": {"type": "string"}},
                            "must_not": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["label", "query", "categories", "must_have", "must_not"],
                        "additionalProperties": False,
                    },
                },
                "response_text": {"type": "string",
                                  "description": "One short present-tense sentence saying what's shown. No counts."},
            },
            "required": ["gender", "minPrice", "maxPrice", "brand", "sizes", "colors", "onSale",
                         "searches", "response_text"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}

PLAN_PROMPT = """You plan product searches for a Pakistani clothing marketplace. Shoppers type
vague, misspelled, Roman Urdu or situational queries. Turn each into searches
that find every relevant product and nothing irrelevant.

searches:
- Normally exactly 1. Use 2-4 only when the shopper wants several product
  types: a full outfit, an occasion or trip where different garments make
  sense, or explicitly several items ("kurta and shoes"). One product type
  per search.
- query: rewrite into plain product-description language, the way a product
  listing would describe matching items. Fix spelling, translate Roman Urdu,
  expand slang ("baggy tee" -> "loose relaxed oversized t-shirt"). For
  situations, infer what suits it (season, weather, formality, comfort) but
  stay broad: describe a range of suitable items, not one narrow guess.
  Never add colors, brands or prices the shopper didn't say.
- categories: the product type at the level the shopper named it. A specific
  garment -> its leaf ("t-shirt" -> ["T-Shirt"]). A broad word -> every
  matching leaf or the grouping ("pants" -> ["Trouser","Jeans","Cargo
  Trouser","Joggers"]; "shoes" -> ["Footwear"]). Never narrower than what
  was asked: "pants" is not "Cargo Trouser". Include every leaf a shopper
  would accept for that garment, because stores file the same garment
  under different names (a plain "tee" -> ["T-Shirt","Top"]; a "co-ord"
  -> ["Co-ord Set","Suits & Sets"]). For occasion searches you choose the
  type per search.
  Empty array when no type is implied at all.
- must_have: ONLY attributes the shopper explicitly asked for (fit, length,
  sleeves, neckline, print placement, fabric, closure...). List the
  attribute with its common synonyms as short phrases as a product
  description would word them, including stronger forms of it: "loose" ->
  ["loose", "relaxed fit", "oversized", "boxy", "baggy", "drop shoulder"];
  "slim" -> ["slim fit", "slim", "skinny"]. Empty if nothing specific was
  asked. Not for colors, gender, price or product type.
- must_not: the OTHER values of the same attribute, which a shopper asking
  for must_have would reject, as a description would word them, multi-word
  where possible. Not just the opposite: every clearly different value.
  skinny trousers -> ["wide leg", "flared", "bootcut", "relaxed fit",
  "loose fit", "baggy", "palazzo"]; oversized shirt -> ["slim fit",
  "fitted", "muscle fit"]; button-up cardigan -> ["pullover"]; sleeveless
  top -> ["long sleeves", "short sleeves", "three-quarter sleeves"].
  Never list a stronger or closer form of what was asked (skinny is a kind
  of slim; oversized is a kind of loose) or a neighbouring value the
  shopper might accept. Products whose description says these are removed.
  Empty when must_have is empty.

Other fields: only what the shopper actually said. colors are hard filters,
so only explicit color requests.

Examples:
"comfy oversize hoody" -> 1 search: query "oversized relaxed hoodie, soft
  and comfortable", categories ["Hoodie"], must_have ["oversized","relaxed
  fit","loose","boxy","drop shoulder"], must_not ["slim fit","fitted",
  "muscle fit"]
"men's sweaters" -> gender Men, 1 search: query "men's sweater",
  categories ["Sweater"], must_have [], must_not []
"what to wear to a winter wedding reception, women" -> gender Women, 3
  searches: "Formal suits": "formal embroidered stitched suit in rich
  fabric for a winter evening", ["Shalwar Kameez","Kurta Set","3-Piece"];
  "Shawls": "warm formal shawl to wear over an outfit", ["Shawl"];
  "Footwear": "dressy heels or sandals", ["Footwear"]; no must_have.
"maroon cardigan in large" -> colors ["maroon"], sizes ["L"], 1 search:
  "cardigan sweater", ["Sweater"]

Conversation: earlier messages in this chat may come first, each followed
by how you planned it. If the new message refines the last search ("in
blue", "cheaper", "under 3000", "in medium", "more relaxed", "show women's
instead", "what about shoes for it"), keep everything from that plan that
the new message doesn't change and apply the change; a follow-up like
"shoes to go with it" plans the new item for the same occasion. If the new
message is a different topic, plan it on its own and ignore the earlier
ones."""

HISTORY_TURNS = 3  # earlier turns of the same thread sent to the planner
_PLAN_KEYS = ("gender", "minPrice", "maxPrice", "brand", "sizes", "colors", "onSale")
_SEARCH_KEYS = ("label", "query", "categories", "must_have", "must_not")


def _history_messages(history: list[dict] | None) -> list[dict]:
    """Earlier turns of this chat as user/assistant message pairs. The
    browser sends them (the server keeps no session); only known fields
    are kept and everything is capped, so a client can't stuff the prompt."""
    messages = []
    for turn in (history or [])[-HISTORY_TURNS:]:
        if not isinstance(turn, dict) or not isinstance(turn.get("query"), str):
            continue
        plan = turn.get("plan") if isinstance(turn.get("plan"), dict) else {}
        compact = {k: plan.get(k) for k in _PLAN_KEYS if plan.get(k) not in (None, [], False)}
        compact["searches"] = [
            {k: s.get(k) for k in _SEARCH_KEYS if s.get(k) not in (None, [])}
            for s in (plan.get("searches") or [])[:MAX_SEARCHES] if isinstance(s, dict)
        ]
        messages.append({"role": "user", "content": turn["query"][:300]})
        messages.append({"role": "assistant", "content": "Planned: " + json.dumps(compact, ensure_ascii=False)[:1500]})
    return messages


async def plan_search(query: str, history: list[dict] | None = None) -> tuple[dict, LLMCallRecord]:
    with Timer() as t:
        completion = await openai.chat.completions.create(
            model=SEARCH_MODEL,
            **({"reasoning_effort": "none"} if re.match(r"^gpt-[56]", SEARCH_MODEL) else {}),
            messages=[{"role": "system", "content": PLAN_PROMPT}, *_history_messages(history),
                      {"role": "user", "content": query}],
            tools=[PLAN_TOOL],
            tool_choice={"type": "function", "function": {"name": "plan_search"}},
        )
    call = completion.choices[0].message.tool_calls
    if not call:
        raise RuntimeError("model did not call plan_search")
    plan = json.loads(call[0].function.arguments)
    usage = completion.usage
    return plan, LLMCallRecord(
        model=SEARCH_MODEL,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        latency_ms=t.elapsed_ms,
    )


async def embed_many(texts: list[str]) -> tuple[list[str], LLMCallRecord]:
    """One embeddings call for every sub-search query."""
    with Timer() as t:
        resp = await openai.embeddings.create(model="text-embedding-3-large", input=texts, dimensions=1536)
    vectors = ["[" + ",".join(str(x) for x in d.embedding) + "]" for d in resp.data]
    return vectors, LLMCallRecord(
        model="text-embedding-3-large",
        input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
        output_tokens=0,
        latency_ms=t.elapsed_ms,
    )


def _phrase_re(phrases: list[str]):
    """Whole-word, case-insensitive match for any of the phrases; hyphens and
    spaces interchangeable ("slim-fit" == "slim fit")."""
    cleaned = [p.strip().lower() for p in phrases if p and p.strip()]
    if not cleaned:
        return None
    parts = [r"[\s-]+".join(re.escape(w) for w in re.split(r"[\s-]+", p)) for p in cleaned]
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.IGNORECASE)


def _ai_text(row) -> str:
    return f"{row['ai_description'] or ''} {' '.join(row['ai_tags'] or [])}"


def _row_columns(colors_idx: int) -> str:
    # Photo of an in-stock variant in the requested color family when a color
    # was asked for, else the product's first photo.
    return f"""
  p.id, p.title, p.handle, p.ai_description, p.ai_tags, p.brand_id AS _brand_id,
  b.name AS store_display, b.slug AS store, cat.name AS category_name,
  COALESCE(
    (SELECT vi.image_url FROM variants vi JOIN colors ci ON ci.id = vi.color_id
     WHERE vi.product_id = p.id AND ci.families && ${colors_idx}::text[]
       AND vi.current_available AND vi.image_url IS NOT NULL LIMIT 1),
    (SELECT pi.url FROM product_images pi WHERE pi.product_id = p.id ORDER BY pi.position LIMIT 1)
  ) AS image_url,
  v.price, v.compare_at_price, v.available, v.variant_count
"""


_ROW_JOIN = """
  FROM products p
  JOIN brands b ON b.id = p.brand_id
  JOIN categories cat ON cat.id = p.category_id
  JOIN LATERAL (
    SELECT vv.current_price AS price, vv.current_compare_at AS compare_at_price,
           (SELECT BOOL_OR(v2.current_available) FROM variants v2 WHERE v2.product_id = p.id) AS available,
           (SELECT COUNT(*) FROM variants v3 WHERE v3.product_id = p.id) AS variant_count
    FROM variants vv WHERE vv.product_id = p.id
    ORDER BY vv.current_price ASC NULLS LAST LIMIT 1
  ) v ON true
"""


def _base_where(plan: dict, brand_id, scope_ids, params: list) -> list[str]:
    """Hard filters shared by every sub-search (everything except category)."""
    where = [
        "p.is_active AND p.is_browsable AND p.embedding_v2 IS NOT NULL",
        "EXISTS (SELECT 1 FROM variants va WHERE va.product_id = p.id AND va.current_available)",
    ]
    if brand_id is not None:
        params.append(brand_id)
        where.append(f"p.brand_id = ${len(params)}")
    if scope_ids:
        params.append(scope_ids)
        where.append(f"p.brand_id = ANY(${len(params)}::int[])")
    for key, op in (("minPrice", ">="), ("maxPrice", "<=")):
        val = plan.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            params.append(val)
            where.append(f"(SELECT MIN(vp.current_price) FROM variants vp WHERE vp.product_id = p.id) {op} ${len(params)}")
    if plan.get("onSale") is True:
        where.append("EXISTS (SELECT 1 FROM variants vo WHERE vo.product_id = p.id "
                     "AND vo.current_compare_at > vo.current_price)")
    colors = [c for c in (plan.get("colors") or []) if c in COLOR_FAMILIES]
    if colors:
        # In stock in that color, not just "comes in that color".
        params.append(colors)
        where.append(f"EXISTS (SELECT 1 FROM variants vc JOIN colors c ON c.id = vc.color_id "
                     f"WHERE vc.product_id = p.id AND vc.current_available AND c.families && ${len(params)}::text[])")
    sizes = plan.get("sizes") or []
    if sizes:
        params.append(expand_size_aliases_for_query(sizes))
        where.append(f"EXISTS (SELECT 1 FROM variants vs WHERE vs.product_id = p.id "
                     f"AND lower(vs.size_label) = ANY(${len(params)}::text[]) AND vs.current_available)")
    return where


async def _retrieve(pool, where: list[str], params: list, colors: list[str], vector: str, keyword_text: str):
    """Vector + keyword legs over the v2 columns, fused with weighted RRF."""
    params = list(params)
    where_sql = " AND ".join(where)
    params.append(colors)
    cols = _row_columns(len(params))

    vparams = [*params, vector, LEG_POOL]
    vi = len(params) + 1
    vector_sql = f"""
      WITH c AS (
        SELECT {cols}, (p.embedding_v2 <=> ${vi}::vector) AS _dist {_ROW_JOIN} WHERE {where_sql}
      ), r AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY _brand_id ORDER BY _dist) AS _brank FROM c)
      SELECT * FROM r WHERE _brank <= {MAX_PER_BRAND_IN_LEG} ORDER BY _dist LIMIT ${vi + 1}
    """
    tparams = [*params, keyword_text, LEG_POOL]
    ti = len(params) + 1
    tsq = f"to_tsquery('english', replace(plainto_tsquery('english', ${ti})::text, ' & ', ' | '))"
    keyword_sql = f"""
      SELECT {cols} {_ROW_JOIN} WHERE {where_sql} AND p.search_vector_v2 @@ {tsq}
      ORDER BY ts_rank(p.search_vector_v2, {tsq}) DESC LIMIT ${ti + 1}
    """

    async def vector_leg():
        async with pool.acquire() as conn:
            await conn.execute("SET hnsw.ef_search = 400")
            return await conn.fetch(vector_sql, *vparams)

    async def keyword_leg():
        return await pool.fetch(keyword_sql, *tparams) if keyword_text.strip() else []

    vrows, krows = await asyncio.gather(vector_leg(), keyword_leg())
    scored: dict[int, dict] = {}
    for leg, rows in (("vector", vrows), ("textual", krows)):
        for i, row in enumerate(rows):
            e = scored.setdefault(row["id"], {"row": row, "score": 0.0, "legs": {"vector": None, "textual": None}})
            e["score"] += LEG_WEIGHTS[leg] / (RRF_K + i + 1)
            e["legs"][leg] = i + 1
    return list(scored.values())


def _apply_attributes(entries: list[dict], must_have: list[str], must_not: list[str]):
    """Drops products whose AI text contradicts the query (must_not) and
    boosts the ones that state what was asked (must_have)."""
    has_re, not_re = _phrase_re(must_have), _phrase_re(must_not)
    kept, removed = [], []
    for e in entries:
        text = _ai_text(e["row"])
        if not_re and not_re.search(text):
            m = not_re.search(text).group(0)
            removed.append({"id": e["row"]["id"], "title": e["row"]["title"], "matched": m})
            continue
        e["must_have_hit"] = bool(has_re and has_re.search(text))
        if e["must_have_hit"]:
            e["score"] += MUST_HAVE_BONUS
        kept.append(e)
    kept.sort(key=lambda e: e["score"], reverse=True)
    return kept, removed


def _product(e: dict, alternative: bool = False, debug: bool = False) -> dict:
    r = e["row"]
    out = {
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
    if alternative:
        out["alternative"] = True
    if debug:
        out["_debug"] = {"category": r["category_name"], "score": round(e["score"], 5), "legs": e["legs"],
                         "must_have_hit": e.get("must_have_hit", False), "ai_description": r["ai_description"]}
    return out


async def _parent_names(names: list[str]) -> list[str]:
    """Names of the parent groups of these category names, under any gender."""
    tree = await get_tree()
    wanted = {n.lower() for n in names}
    parents = set()
    for node in tree.by_id.values():
        if node.name.lower() in wanted and node.parent_id in tree.by_id:
            parents.add(tree.by_id[node.parent_id].name)
    return sorted(parents)


async def _run_one(pool, plan, s, vector, base_where, base_params, colors, debug):
    """One sub-search: category filter at the asked level, never zero results."""
    keyword_text = " ".join([s["query"], *s["must_have"]])
    notes = []
    where, params = list(base_where), list(base_params)
    cat_ids, not_found = ([], False)
    if s["categories"]:
        cat_ids, not_found = await category_ids_for_search(plan.get("gender"), s["categories"])
        if not_found:
            # The type doesn't exist under this gender (e.g. "Kurta Shalwar"
            # is only a Boys leaf). Search its parent group instead of
            # everything: "Stitched" still means eastern stitched wear.
            parents = await _parent_names(s["categories"])
            if parents:
                cat_ids, not_found = await category_ids_for_search(plan.get("gender"), parents)
            notes.append(f"{s['categories']} isn't a category here; searched "
                         + (f"{parents} instead" if cat_ids and not not_found else "without a category"))
        if cat_ids and not not_found:
            params.append(cat_ids)
            where.append(f"p.category_id = ANY(${len(params)}::int[])")

    # Safety net: a phrase can't be both wanted and excluded (the planner
    # occasionally excludes "skinny" for a "slim" query).
    wanted = {w.strip().lower() for w in s["must_have"]}
    s["must_not"] = [w for w in s["must_not"] if w.strip().lower() not in wanted]

    entries = await _retrieve(pool, where, params, colors, vector, keyword_text)
    kept, removed = _apply_attributes(entries, s["must_have"], s["must_not"])
    alternatives = []
    if s["must_have"]:
        # Something specific was asked: products whose description states it
        # are the results; the rest are shown as labelled alternatives, so a
        # store with few true matches doesn't pad them with lookalikes.
        main = diversify([e for e in kept if e.get("must_have_hit")])[:GROUP_SIZE]
        alternatives = diversify([e for e in kept if not e.get("must_have_hit")])[: GROUP_SIZE - len(main)]
        if alternatives:
            notes.append(f"{len(main)} products state {s['must_have'][0]!r}; the rest are close alternatives")
    else:
        main = diversify(kept)[:GROUP_SIZE]

    if cat_ids and not not_found and len(main) + len(alternatives) < MIN_RESULTS:
        notes.append(f"only {len(main)} results in {s['categories']}; added related products")
        more = await _retrieve(pool, list(base_where), list(base_params), colors, vector, keyword_text)
        more_kept, more_removed = _apply_attributes(more, s["must_have"], s["must_not"])
        removed += more_removed
        have = {e["row"]["id"] for e in main + alternatives}
        room = GROUP_SIZE - len(main) - len(alternatives)
        alternatives += [e for e in more_kept if e["row"]["id"] not in have][:room]

    group = {
        "label": s["label"],
        "query": s["query"],
        "categories": s["categories"],
        "must_have": s["must_have"],
        "must_not": s["must_not"],
        "products": [_product(e, debug=debug) for e in main] + [_product(e, True, debug) for e in alternatives],
        "notes": notes,
    }
    if debug:
        group["_debug"] = {"removed_by_must_not": removed[:50], "removed_count": len(removed)}
    return group


async def run_search_v2(query: str, debug: bool = False, gender_override: str | None = None,
                        brand_scope: list[str] | None = None, history: list[dict] | None = None) -> dict:
    if openai is None:
        raise RuntimeError("OPENAI_API_KEY not configured")
    query = (query or "").strip()
    if not query:
        raise ValueError("empty query")
    t0 = time.perf_counter()

    plan, plan_metrics = await plan_search(query, history)
    if gender_override and gender_override in VALID_GENDER_OVERRIDES:
        plan["gender"] = gender_override
    searches = [s for s in plan.get("searches") or [] if s.get("query", "").strip()][:MAX_SEARCHES]
    if not searches:  # model returned nothing usable: plain search on the raw query
        searches = [{"label": "Results", "query": query, "categories": [], "must_have": [], "must_not": []}]
    plan["searches"] = searches

    vectors, embed_metrics = await embed_many([s["query"] for s in searches])

    pool = await get_pool()
    brand_id = await resolve_brand_id(plan.get("brand")) if plan.get("brand") else None
    scope = brand_scope if brand_scope is not None else BRAND_SCOPE
    scope_ids = []
    if scope:
        scope_ids = [r["id"] for r in await pool.fetch("SELECT id FROM brands WHERE slug = ANY($1::text[])", scope)]

    base_params: list = []
    base_where = _base_where(plan, brand_id, scope_ids, base_params)
    colors = [c for c in (plan.get("colors") or []) if c in COLOR_FAMILIES]
    # Gender scope (adult trees when no gender is given, same as v1) is part
    # of the base filter, so it survives when a sub-search drops its category
    # for alternatives: a men's query never fills up with women's items.
    gender_ids, _ = await category_ids_for_search(plan.get("gender"), None)
    if gender_ids:
        base_params.append(gender_ids)
        base_where.append(f"p.category_id = ANY(${len(base_params)}::int[])")

    groups = await asyncio.gather(*[
        _run_one(pool, plan, s, v, base_where, base_params, colors, debug) for s, v in zip(searches, vectors)
    ])
    total_returned = sum(len(g["products"]) for g in groups)

    # v1-compatible fields so the current frontend and search logging keep
    # working: `products` is the first group, `filters` carries v1's keys.
    filters = {
        **{k: plan.get(k) for k in ("gender", "minPrice", "maxPrice", "brand", "sizes", "colors", "onSale")},
        "categories": sorted({c for s in searches for c in s["categories"]}),
        "semantic_query": " | ".join(s["query"] for s in searches),
        "response_text": plan.get("response_text", ""),
        "searches": searches,
    }
    result = {
        "engine": "v2",
        "response_text": plan.get("response_text", ""),
        "filters": filters,
        "groups": list(groups),
        "products": groups[0]["products"] if groups else [],
        "total": total_returned,
        "_metrics": {
            "extract": plan_metrics,
            "embed": embed_metrics,
            "total_latency_ms": (time.perf_counter() - t0) * 1000,
            "total_matches": total_returned,
            "results_returned": total_returned,
        },
    }
    return result
