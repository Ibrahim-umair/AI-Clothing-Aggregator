"""GET /api/products, GET /api/products/{id} — port of the same routes in
server/index.js. Logic unchanged; see that file's comments for the "why"
behind each filter (price on the cheapest variant, size means "available
in this size", out-of-stock excluded by default, etc.).
"""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from db import get_pool
from query_helpers import (
    canonical_size,
    category_ids_from_query,
    expand_size_aliases_for_query,
    parse_page,
    resolve_brand_id,
    to_money,
)
from taxonomy_tree import get_tree

router = APIRouter()

SORTS = {
    "price_asc": "v.price ASC NULLS LAST",
    "price_desc": "v.price DESC NULLS LAST",
    "newest": "p.first_seen_at DESC, p.id DESC",
    "default": "p.id",
}

# Home's own "Featured For You" — real bug, not hypothetical: sorting by
# plain "newest" means a single brand's bulk-load day can dominate every
# "newest" slot outright, on a homepage whose own copy says "15 real
# brands...not a marketplace listing". A first attempt just diversified a
# flat top-300-newest pool by brand (same shape as rag.py's diversify()
# for AI search) — verified WRONG against real data before shipping: two
# brands got bulk-reloaded the same day this was built (Lama's domain
# fix, Bandana's onboarding), 2,706 + 937 = 3,643 products newer than
# almost everything else in the whole catalog, so the top-300 pool was
# *itself* 100% those two brands with nothing else to round-robin against
# — diversifying a homogeneous pool just returns the homogeneous pool.
# Real fix: cap how many of any ONE brand's newest products are even
# eligible (via ROW_NUMBER() PARTITION BY brand, in the SQL below) BEFORE
# diversifying, so no bulk-load day can flood the set regardless of its
# size — a brand with 3 recent products and a brand with 3,000 both
# contribute at most FEATURED_PER_BRAND_CAP.
FEATURED_PER_BRAND_CAP = 10


def _diversify_by_brand(rows: list) -> list:
    from collections import OrderedDict, deque

    by_brand: "OrderedDict[str, deque]" = OrderedDict()
    for r in rows:
        by_brand.setdefault(r["store"], deque()).append(r)
    brand_queue = deque(by_brand.keys())
    out = []
    while brand_queue:
        brand = brand_queue.popleft()
        bucket = by_brand[brand]
        out.append(bucket.popleft())
        if bucket:
            brand_queue.append(brand)
    return out


def _row_to_product(r) -> dict:
    return {
        # products.id is bigint — node-postgres (the Node version's driver)
        # serializes bigint as a STRING by default to avoid silent
        # precision loss past 2^53, and the frontend/URLs/favourites
        # already expect that shape. asyncpg returns a native Python int
        # (no precision issue in Python), so this must be cast explicitly
        # to match, or a strict `===` against a URL param (always a
        # string) would silently break.
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


@router.get("/api/products")
async def list_products(request: Request):
    q = request.query_params
    page, page_size, offset = parse_page(q.get("page"), q.get("pageSize"))
    category_ids, not_found = await category_ids_from_query(
        gender=q.get("gender"), branch=q.get("branch"), sub=q.get("sub"), category=q.get("category")
    )
    if not_found:
        return {"total": 0, "page": page, "pageSize": page_size, "products": []}

    brand_id = await resolve_brand_id(q.get("brand"))
    if q.get("brand") and brand_id is None:
        return {"total": 0, "page": page, "pageSize": page_size, "products": []}

    where = ["p.is_active = true AND p.is_browsable = true"]
    params: list = []
    if category_ids:
        params.append(category_ids)
        where.append(f"p.category_id = ANY(${len(params)}::int[])")
    if brand_id is not None:
        params.append(brand_id)
        where.append(f"p.brand_id = ${len(params)}")
    if q.get("q"):
        params.append(f"%{q['q']}%")
        where.append(f"p.title ILIKE ${len(params)}")
    if q.get("onSale") == "true":
        where.append(
            "EXISTS (SELECT 1 FROM variants vo WHERE vo.product_id = p.id AND vo.current_compare_at IS NOT NULL AND vo.current_compare_at > vo.current_price)"
        )
    colors = [c.strip() for c in (q.get("color") or "").split(",") if c.strip()]
    if colors:
        params.append(colors)
        where.append(
            f"EXISTS (SELECT 1 FROM variants vc JOIN colors c ON c.id = vc.color_id WHERE vc.product_id = p.id AND c.canonical_name = ANY(${len(params)}::text[]))"
        )
    # Out-of-stock products are excluded from listings by default.
    if q.get("includeOutOfStock") != "true":
        where.append("EXISTS (SELECT 1 FROM variants va WHERE va.product_id = p.id AND va.current_available = true)")
    # Price range filters on the product's cheapest variant price (the same
    # one shown on the card and used for price_asc/price_desc sorting).
    if q.get("minPrice"):
        try:
            params.append(float(q["minPrice"]))
            where.append(f"(SELECT MIN(vp.current_price) FROM variants vp WHERE vp.product_id = p.id) >= ${len(params)}")
        except ValueError:
            pass
    if q.get("maxPrice"):
        try:
            params.append(float(q["maxPrice"]))
            where.append(f"(SELECT MIN(vp.current_price) FROM variants vp WHERE vp.product_id = p.id) <= ${len(params)}")
        except ValueError:
            pass
    sizes = [s.strip() for s in (q.get("size") or "").split(",") if s.strip()]
    if sizes:
        params.append(expand_size_aliases_for_query(sizes))
        where.append(
            f"EXISTS (SELECT 1 FROM variants vs WHERE vs.product_id = p.id AND lower(vs.size_label) = ANY(${len(params)}::text[]) AND vs.current_available = true)"
        )
    where_sql = " AND ".join(where)
    featured = q.get("sort") == "featured"
    order_by_sql = SORTS["newest"] if featured else SORTS.get(q.get("sort"), SORTS["default"])

    pool = await get_pool()
    total = await pool.fetchval(f"SELECT COUNT(*) FROM products p WHERE {where_sql}", *params)

    # Same "show the matched color's actual photo" fix as rag.py's search
    # results — picks the image of whichever variant matched the `color`
    # filter above (empty list when no color filter is active, in which
    # case the subquery finds nothing and COALESCE falls through unchanged).
    params.append([c.lower() for c in colors])
    color_image_idx = len(params)
    limit_idx = len(params) + 1
    offset_idx = len(params) + 2
    list_sql = f"""
      SELECT
        p.id, p.title, p.handle, p.first_seen_at,
        b.name AS store_display, b.slug AS store,
        COALESCE(
          (SELECT vi.image_url FROM variants vi JOIN colors ci ON ci.id = vi.color_id
           WHERE vi.product_id = p.id AND lower(ci.canonical_name) = ANY(${color_image_idx}::text[])
             AND vi.image_url IS NOT NULL LIMIT 1),
          (SELECT pi.url FROM product_images pi WHERE pi.product_id = p.id ORDER BY pi.position LIMIT 1)
        ) AS image_url,
        v.price, v.compare_at_price, v.available, v.variant_count
      FROM products p
      JOIN brands b ON b.id = p.brand_id
      JOIN LATERAL (
        SELECT vv.current_price AS price, vv.current_compare_at AS compare_at_price,
               (SELECT BOOL_OR(v2.current_available) FROM variants v2 WHERE v2.product_id = p.id) AS available,
               (SELECT COUNT(*) FROM variants v3 WHERE v3.product_id = p.id) AS variant_count
        FROM variants vv WHERE vv.product_id = p.id
        ORDER BY vv.current_price ASC NULLS LAST LIMIT 1
      ) v ON true
      WHERE {where_sql}
      ORDER BY {order_by_sql}
      LIMIT ${limit_idx} OFFSET ${offset_idx}
    """
    if featured:
        # Wraps the same base query, capping each brand to its
        # FEATURED_PER_BRAND_CAP newest products via ROW_NUMBER() BEFORE
        # anything gets diversified — see FEATURED_PER_BRAND_CAP's own
        # comment for why a flat pool alone doesn't fix this. The capped
        # set (at most 15 brands x 10 = 150 rows, cheap) is then
        # diversified by brand in Python and the requested page sliced
        # out of that order. Deterministic given stable underlying data,
        # so independent page requests (Home paginates via separate
        # fetches, no shared session state) still line up into one
        # continuous, non-repeating sequence.
        capped_sql = f"""
          SELECT * FROM (
            SELECT c.*, ROW_NUMBER() OVER (PARTITION BY c.store ORDER BY c.first_seen_at DESC, c.id DESC) AS rn
            FROM ({list_sql.replace(f"LIMIT ${limit_idx} OFFSET ${offset_idx}", "")}) c
          ) ranked
          WHERE rn <= ${limit_idx}
          ORDER BY first_seen_at DESC, id DESC
        """
        pool_rows = await pool.fetch(capped_sql, *params, FEATURED_PER_BRAND_CAP)
        diversified = _diversify_by_brand(list(pool_rows))
        page_rows = diversified[offset : offset + page_size]
        products = [_row_to_product(r) for r in page_rows]
    else:
        rows = await pool.fetch(list_sql, *params, page_size, offset)
        products = [_row_to_product(r) for r in rows]
    return {"total": total, "page": page, "pageSize": page_size, "products": products}


@router.get("/api/products/{product_id}")
async def get_product(product_id: int):
    pool = await get_pool()
    product = await pool.fetchrow(
        """SELECT p.id, p.title, p.handle, p.description, p.category_id,
                  b.name AS store_display, b.slug AS store, b.base_url
           FROM products p JOIN brands b ON b.id = p.brand_id
           WHERE p.id = $1 AND p.is_active = true AND p.is_browsable = true""",
        product_id,
    )
    if not product:
        raise HTTPException(status_code=404, detail={"error": "not_found"})

    images_rows, variants_rows = await asyncio.gather(
        pool.fetch("SELECT url FROM product_images WHERE product_id = $1 ORDER BY position", product_id),
        pool.fetch(
            """SELECT v.size_label, v.current_price, v.current_compare_at, v.current_available,
                      v.image_url, c.canonical_name AS color
               FROM variants v LEFT JOIN colors c ON c.id = v.color_id
               WHERE v.product_id = $1 ORDER BY v.id""",
            product_id,
        ),
    )

    images = [r["url"] for r in images_rows]
    variants = variants_rows

    # Real fix for two related bugs: (1) a color swatch used to be a bare
    # name with no photo of its own — the frontend now gets each color's
    # ACTUAL variant image (falls back to null when the store's own feed
    # doesn't link one, e.g. Cambridge/Edenrobe/Cougar — see
    # backfill_variant_images.py for real per-store coverage) so it can
    # swap the gallery to a real photo instead of just labeling a color;
    # (2) a color used to always render as in-stock even when every size
    # in it was sold out — `available` here is real, per color.
    color_info: dict[str, dict] = {}
    for v in variants:
        c = v["color"]
        if not c:
            continue
        entry = color_info.setdefault(c, {"name": c, "available": False, "image_url": None})
        if v["current_available"]:
            entry["available"] = True
        if v["image_url"] and not entry["image_url"]:
            entry["image_url"] = v["image_url"]
    colors = list(color_info.values())

    # Sizes computed PER COLOR now, not unioned across every color — a size
    # only being in stock in a DIFFERENT color than the one picked was
    # exactly the "sizes lie" bug reported. `sizes` (the union, unchanged
    # from before) stays as the sensible default before any color is
    # picked; `sizes_by_color` is what the frontend switches to once one is.
    size_availability: dict[str, bool] = {}
    sizes_by_color_acc: dict[str, dict[str, bool]] = {}
    for v in variants:
        if not v["size_label"]:
            continue
        canon = canonical_size(v["size_label"])
        avail = bool(v["current_available"])
        size_availability[canon] = size_availability.get(canon, False) or avail
        if v["color"]:
            bucket = sizes_by_color_acc.setdefault(v["color"], {})
            bucket[canon] = bucket.get(canon, False) or avail
    sizes = [{"label": label, "available": avail} for label, avail in size_availability.items()]
    sizes_by_color = {
        color: [{"label": label, "available": avail} for label, avail in bucket.items()]
        for color, bucket in sizes_by_color_acc.items()
    }

    prices = [float(v["current_price"]) for v in variants if v["current_price"] is not None]
    price = min(prices) if prices else None
    cheapest = next((v for v in variants if v["current_price"] is not None and float(v["current_price"]) == price), None)
    compare_at = float(cheapest["current_compare_at"]) if cheapest and cheapest["current_compare_at"] is not None else None
    available = any(v["current_available"] for v in variants)

    category_path: list[str] = []
    if product["category_id"] is not None:
        tree = await get_tree()
        cur = tree.by_id.get(product["category_id"])
        path = []
        while cur:
            path.insert(0, cur.name)
            cur = tree.by_id.get(cur.parent_id) if cur.parent_id is not None else None
        category_path = path

    return {
        "id": str(product["id"]),  # bigint — see _row_to_product's comment above
        "title": product["title"],
        "handle": product["handle"],
        "description": product["description"],
        "store": product["store"],
        "store_display": product["store_display"],
        "vendor": product["store_display"],
        "images": images,
        "image_url": images[0] if images else None,
        "price": to_money(price),
        "compare_at_price": to_money(compare_at) if compare_at is not None and price is not None and compare_at > price else None,
        "currency": "PKR",
        "available": available,
        "colors": colors,
        "sizes": sizes,
        "sizes_by_color": sizes_by_color,
        "variant_count": len(variants),
        "category_path": category_path,
        "product_url": f"{product['base_url']}/products/{product['handle']}" if product["handle"] else product["base_url"],
    }
