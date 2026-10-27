"""Side-by-side review of search v1 vs v2 on a fixed query set, limited to
the brands enriched so far. Writes data.js for the review page in
review-exports/search-v1-vs-v2/ (open index.html there).

For queries with a color, every result is checked against the live stock
data: is the requested color actually in stock for that product? That's
the "olive is sold out but black isn't" case.

    python compare_search.py
    python compare_search.py --brands charcoal zellbury outfitters --out ../review-exports/search-v1-vs-v2
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from db import close_pool, get_pool  # noqa: E402
from rag import run_search  # noqa: E402
from search_v2 import run_search_v2  # noqa: E402

QUERIES = [
    # fit, said different ways
    ("loose t-shirt for men", "Fit: loose. No slim fits should appear."),
    ("baggy tee that isn't tight", "Fit, slangy wording. Rewriting should turn it into 'loose'."),
    ("slim fit jeans for women", "Fit the other way: no wide or relaxed jeans."),
    ("wide leg pants", "Fit for bottoms."),
    ("pants", "Broad type: should show every kind of trouser/jeans/chino, all fits."),
    # color and stock
    ("olive polo", "Color by family (Dark Olive, Army Green...) and only polos whose olive is in stock."),
    ("navy blue hoodie for men", "Color + type + gender."),
    # occasions and situations (multi-search)
    ("what should I wear to a mehndi in december", "Occasion + season: expect several groups."),
    ("outfit for a summer beach trip", "Outfit: expect several groups."),
    ("something to wear to a job interview", "Formal, situational."),
    ("cozy clothes for a winter road trip to murree", "Place + season."),
    ("comfortable clothes for a long flight", "Situational comfort."),
    ("jummah kurta shalwar", "Cultural wording."),
    # details only visible in photos
    ("graphic tee with a print on the back", "Print placement, usually only visible in photos."),
    ("hoodie with a zip", "Detail: zip-up hoodies only."),
    ("summer lawn suit unstitched", "Women's eastern unstitched."),
    ("shirt that hides my belly", "Subtle: word lists may not catch this."),
]
SHOW = 12  # products per column/group on the page


async def color_stock(pool, product_ids, families):
    """product id -> True if any in-stock variant is in one of the families."""
    if not families or not product_ids:
        return {}
    rows = await pool.fetch(
        """SELECT v.product_id, bool_or(v.current_available AND c.families && $2::text[]) AS ok
           FROM variants v JOIN colors c ON c.id = v.color_id
           WHERE v.product_id = ANY($1::bigint[]) GROUP BY v.product_id""",
        [int(i) for i in product_ids], families,
    )
    return {str(r["product_id"]): bool(r["ok"]) for r in rows}


async def extra_info(pool, product_ids):
    """category name + AI description for the cards (v1 doesn't return them)."""
    rows = await pool.fetch(
        """SELECT p.id, cat.name AS category, p.ai_description, p.handle, b.base_url
           FROM products p JOIN categories cat ON cat.id = p.category_id JOIN brands b ON b.id = p.brand_id
           WHERE p.id = ANY($1::bigint[])""",
        [int(i) for i in product_ids],
    )
    return {str(r["id"]): {"category": r["category"], "ai": r["ai_description"],
                           "url": f"{r['base_url']}/products/{r['handle']}"} for r in rows}


def card(p, info, stock):
    i = info.get(p["id"], {})
    return {"id": p["id"], "title": p["title"], "store": p["store_display"], "image": p["image_url"],
            "price": p["price"], "category": i.get("category"), "ai": i.get("ai"), "url": i.get("url"),
            "alternative": p.get("alternative", False),
            "color_in_stock": stock.get(p["id"]) if stock else None}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brands", nargs="*", default=["charcoal", "zellbury", "outfitters"])
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "review-exports" / "search-v1-vs-v2"))
    args = ap.parse_args()
    pool = await get_pool()
    out = []
    cost = 0.0
    for q, why in QUERIES:
        t = time.perf_counter()
        v1 = await run_search(q, debug=True, brand_scope=args.brands)
        t1 = time.perf_counter() - t
        t = time.perf_counter()
        v2 = await run_search_v2(q, debug=True, brand_scope=args.brands)
        t2 = time.perf_counter() - t
        for r in (v1, v2):
            m = r.get("_metrics") or {}
            cost += sum((m[k].cost_usd or 0) for k in ("extract", "embed") if k in m)

        v1_products = v1["products"][:SHOW]
        v2_groups = v2["groups"]
        ids = {p["id"] for p in v1_products} | {p["id"] for g in v2_groups for p in g["products"][:SHOW]}
        info = await extra_info(pool, ids)
        v1_colors = v1["filters"].get("colors") or []
        v2_colors = v2["filters"].get("colors") or []
        # Check both columns against the same families, so they're comparable.
        fams = v2_colors or [c.lower() for c in v1_colors]
        stock = await color_stock(pool, list(ids), fams)

        out.append({
            "query": q,
            "why": why,
            "v1": {
                "seconds": round(t1, 2),
                "filters": {k: v1["filters"].get(k) for k in ("gender", "categories", "colors", "sizes",
                                                              "maxPrice", "semantic_query")},
                "total": v1["total"],
                "products": [card(p, info, stock) for p in v1_products],
            },
            "v2": {
                "seconds": round(t2, 2),
                "filters": {k: v2["filters"].get(k) for k in ("gender", "colors", "sizes", "maxPrice")},
                "groups": [{
                    "label": g["label"], "query": g["query"], "categories": g["categories"],
                    "must_have": g["must_have"], "must_not": g["must_not"], "notes": g["notes"],
                    "removed_count": g.get("_debug", {}).get("removed_count", 0),
                    "removed": g.get("_debug", {}).get("removed_by_must_not", [])[:8],
                    "products": [card(p, info, stock) for p in g["products"][:SHOW]],
                } for g in v2_groups],
            },
        })
        print(f"{q!r}: v1 {len(v1_products)} in {t1:.1f}s | v2 {len(v2_groups)} group(s) in {t2:.1f}s", flush=True)

    # Searchable = enriched and in stock. Cost = every enrichment call saved
    # for these brands (gpt-6-luna standard rates), sold-out ones included.
    row = await pool.fetchrow(
        """SELECT count(*) FILTER (WHERE EXISTS (SELECT 1 FROM variants v
                                  WHERE v.product_id = p.id AND v.current_available)) AS searchable,
                  count(*) AS rows,
                  coalesce(sum((p.ai_meta->'tokens'->>'in')::numeric), 0) / 1e6 * 0.10
                + coalesce(sum((p.ai_meta->'tokens'->>'out')::numeric), 0) / 1e6 * 0.50 AS cost
           FROM products p JOIN brands b ON b.id = p.brand_id
           WHERE b.slug = ANY($1::text[]) AND p.ai_description IS NOT NULL""", args.brands)
    await close_pool()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"brands": args.brands, "generated": time.strftime("%Y-%m-%d %H:%M"), "query_cost_usd": round(cost, 4),
            "enrichment": {"products": row["searchable"], "cost_usd": float(row["cost"]),
                           "per_1k": float(row["cost"]) / row["rows"] * 1000 if row["rows"] else None}}
    (out_dir / "data.js").write_text(
        "window.REVIEW = " + json.dumps({"meta": meta, "queries": out}, ensure_ascii=False, default=str) + ";\n",
        encoding="utf-8")
    print(f"wrote {out_dir / 'data.js'}  (searches cost ${cost:.4f})")


if __name__ == "__main__":
    asyncio.run(main())
