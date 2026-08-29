"""GET /api/brands — port of the same route in server/index.js."""
from fastapi import APIRouter

from db import get_pool

router = APIRouter()


@router.get("/api/brands")
async def list_brands():
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT b.id, b.slug, b.name, COUNT(p.id)::int AS count
           FROM brands b LEFT JOIN products p ON p.brand_id = b.id AND p.is_active = true AND p.is_browsable = true
           GROUP BY b.id, b.slug, b.name
           ORDER BY b.name"""
    )
    return [dict(r) for r in rows]
