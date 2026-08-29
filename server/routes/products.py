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
    order_by_sql = SORTS.get(q.get("sort"), SORTS["default"])

    pool = await get_pool()
    total = await pool.fetchval(f"SELECT COUNT(*) FROM products p WHERE {where_sql}", *params)

    limit_idx = len(params) + 1
    offset_idx = len(params) + 2
    list_sql = f"""
      SELECT
        p.id, p.title, p.handle,
        b.name AS store_display, b.slug AS store,
        (SELECT pi.url FROM product_images pi WHERE pi.product_id = p.id ORDER BY pi.position LIMIT 1) AS image_url,
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
            """SELECT v.size_label, v.current_price, v.current_compare_at, v.current_available, c.canonical_name AS color
               FROM variants v LEFT JOIN colors c ON c.id = v.color_id
               WHERE v.product_id = $1 ORDER BY v.id""",
            product_id,
        ),
    )

    images = [r["url"] for r in images_rows]
    variants = variants_rows
    colors = list({v["color"] for v in variants if v["color"]})

    # One size label can appear across several color variants — a size
    # only reads as available if AT LEAST ONE color still has stock in it.
    size_availability: dict[str, bool] = {}
    for v in variants:
        if not v["size_label"]:
            continue
        canon = canonical_size(v["size_label"])
        size_availability[canon] = size_availability.get(canon, False) or bool(v["current_available"])
    sizes = [{"label": label, "available": avail} for label, avail in size_availability.items()]

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
        "variant_count": len(variants),
        "category_path": category_path,
        "product_url": f"{product['base_url']}/products/{product['handle']}" if product["handle"] else product["base_url"],
    }
