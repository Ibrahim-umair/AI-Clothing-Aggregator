"""GET /api/taxonomy, GET /api/categories/featured — port of the same
routes in server/index.js. Powers TaxonomyNav: gender tab counts (honoring
an active brand filter), per-gender mega-menu columns (always computed
over the whole catalog), and brand/size/color/price facets (honoring the
active gender/branch/sub/category + brand filter).
"""
import asyncio

from fastapi import APIRouter, Request

from db import get_pool
from query_helpers import canonical_size, category_ids_from_query, resolve_brand_id
from taxonomy_tree import build_menus, find_descendant_by_name, get_tree, resolve_node_id

router = APIRouter()


@router.get("/api/taxonomy")
async def taxonomy(request: Request):
    q = request.query_params
    pool = await get_pool()
    tree = await get_tree()

    cat_ids_for_refine, cat_refine_not_found = await category_ids_from_query(
        gender=q.get("gender"), branch=q.get("branch"), sub=q.get("sub"), category=q.get("category")
    )
    brand_id_for_refine = await resolve_brand_id(q.get("brand"))
    refine_where = ["p.is_active = true AND p.is_browsable = true"]
    refine_params: list = []
    if cat_ids_for_refine:
        refine_params.append(cat_ids_for_refine)
        refine_where.append(f"p.category_id = ANY(${len(refine_params)}::int[])")
    if brand_id_for_refine is not None:
        refine_params.append(brand_id_for_refine)
        refine_where.append(f"p.brand_id = ${len(refine_params)}")
    refine_where_sql = " AND ".join(refine_where)

    async def gender_counts():
        brand = q.get("brand")
        join = "JOIN brands b ON b.id = p.brand_id" if brand else ""
        brand_filter = "AND (lower(b.slug) = lower($1) OR lower(b.name) = lower($1))" if brand else ""
        sql = f"""SELECT p.category_id, COUNT(*)::int AS count
                  FROM products p {join}
                  WHERE p.is_active = true AND p.is_browsable = true {brand_filter}
                  GROUP BY p.category_id"""
        return await pool.fetch(sql, *([brand] if brand else []))

    async def brand_counts():
        cat_ids, not_found = await category_ids_from_query(
            gender=q.get("gender"), branch=q.get("branch"), sub=q.get("sub"), category=q.get("category")
        )
        if not_found:
            return []
        where = ["p.is_active = true AND p.is_browsable = true"]
        params: list = []
        if cat_ids:
            params.append(cat_ids)
            where.append(f"p.category_id = ANY(${len(params)}::int[])")
        return await pool.fetch(
            f"""SELECT b.name AS value, COUNT(*)::int AS count
                FROM products p JOIN brands b ON b.id = p.brand_id
                WHERE {' AND '.join(where)}
                GROUP BY b.name ORDER BY count DESC""",
            *params,
        )

    async def brand_total():
        return await pool.fetchval("SELECT COUNT(*)::int FROM products WHERE is_active = true AND is_browsable = true")

    async def size_facets():
        if cat_refine_not_found:
            return []
        return await pool.fetch(
            f"""SELECT v.size_label AS value, COUNT(DISTINCT p.id)::int AS count
                FROM products p JOIN variants v ON v.product_id = p.id
                WHERE {refine_where_sql} AND v.size_label IS NOT NULL AND v.current_available = true
                GROUP BY v.size_label ORDER BY count DESC""",
            *refine_params,
        )

    async def price_bounds():
        if cat_refine_not_found:
            return {"min": None, "max": None}
        row = await pool.fetchrow(
            f"""SELECT MIN(v.current_price)::float AS min, MAX(v.current_price)::float AS max
                FROM products p JOIN variants v ON v.product_id = p.id
                WHERE {refine_where_sql} AND v.current_available = true""",
            *refine_params,
        )
        return dict(row) if row else {"min": None, "max": None}

    async def color_facets():
        if cat_refine_not_found:
            return []
        return await pool.fetch(
            f"""SELECT c.canonical_name AS value, COUNT(DISTINCT p.id)::int AS count
                FROM products p JOIN variants v ON v.product_id = p.id JOIN colors c ON c.id = v.color_id
                WHERE {refine_where_sql} AND v.current_available = true
                GROUP BY c.canonical_name ORDER BY count DESC LIMIT 12""",
            *refine_params,
        )

    gender_counts_rows, brand_counts_rows, total, size_facets_rows, price_bounds_row, color_facets_rows = await asyncio.gather(
        gender_counts(), brand_counts(), brand_total(), size_facets(), price_bounds(), color_facets()
    )

    counts_by_category_id = {r["category_id"]: r["count"] for r in gender_counts_rows}
    menus_result = build_menus(tree, counts_by_category_id)

    # Merge size labels that are really the same size spelled differently
    # by different stores ("M"/"Medium", "XXL"/"2XL") into one facet.
    size_facets_merged: dict[str, int] = {}
    for row in size_facets_rows:
        canon = canonical_size(row["value"])
        size_facets_merged[canon] = size_facets_merged.get(canon, 0) + row["count"]
    size_facets_list = sorted(
        ({"value": v, "count": c} for v, c in size_facets_merged.items()), key=lambda x: x["count"], reverse=True
    )[:16]

    return {
        "total": total,
        "genderFacets": menus_result["genderFacets"],
        "menus": menus_result["menus"],
        "brandFacets": [dict(r) for r in brand_counts_rows],
        "sizeFacets": size_facets_list,
        "colorFacets": [dict(r) for r in color_facets_rows],
        "priceBounds": price_bounds_row,
    }


@router.get("/api/categories/featured")
async def categories_featured(request: Request):
    items_param = request.query_params.get("items", "")
    items = []
    for part in items_param.split(","):
        if not part:
            continue
        gender, *rest = part.split(":")
        items.append({"gender": gender, "name": ":".join(rest)})
    if not items:
        return []

    pool = await get_pool()
    tree = await get_tree()
    out = []
    for item in items:
        gender_id, not_found = resolve_node_id(tree, gender=item["gender"])
        if not_found or gender_id is None:
            continue
        leaf_id = find_descendant_by_name(tree, gender_id, item["name"])
        if leaf_id is None:
            continue
        row = await pool.fetchrow(
            """SELECT COUNT(*)::int AS count,
                      (SELECT pi.url FROM products p2
                         JOIN product_images pi ON pi.product_id = p2.id
                        WHERE p2.category_id = $1 AND p2.is_active = true AND p2.is_browsable = true
                        ORDER BY p2.id, pi.position LIMIT 1) AS image_url
               FROM products p2 WHERE p2.category_id = $1 AND p2.is_active = true AND p2.is_browsable = true""",
            leaf_id,
        )
        if not row or row["count"] == 0:
            continue
        out.append({"gender": item["gender"], "category": item["name"], "count": row["count"], "image_url": row["image_url"]})
    return out
