"""Crawler-facing endpoints.

GET /api/sitemap-data — everything frontend/scripts/generate-sitemap.mjs
needs to write the public sitemap at build time, in ONE request (paging
through /api/products for ~100k ids would be over a thousand calls per
deploy). Same visibility rule as GET /api/products/{id}: if the product
page would render, it's listed; if it would 404, it isn't.

GET /robots.txt — the API host itself should never appear in search
results (it's JSON, and /api/search costs money per hit). The frontend
has its own, separate robots.txt.
"""
import asyncio

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from db import get_pool

router = APIRouter()


@router.get("/api/sitemap-data")
async def sitemap_data():
    pool = await get_pool()
    product_rows, brand_rows = await asyncio.gather(
        pool.fetch("SELECT id FROM products WHERE is_active = true AND is_browsable = true ORDER BY id"),
        pool.fetch(
            """SELECT b.name FROM brands b
               WHERE EXISTS (SELECT 1 FROM products p WHERE p.brand_id = b.id AND p.is_active = true AND p.is_browsable = true)
               ORDER BY b.name"""
        ),
    )
    return {
        # Strings, matching how the rest of the API serializes bigint ids.
        "productIds": [str(r["id"]) for r in product_rows],
        # Brand *names*, because that's what Shop's ?brand= carries
        # (taxonomy brandFacets) and the sitemap must list canonical URLs.
        "brands": [r["name"] for r in brand_rows],
    }


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots():
    return "User-agent: *\nDisallow: /\n"
