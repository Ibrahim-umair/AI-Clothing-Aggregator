"""GET /api/health — port of the same route in server/index.js."""
from fastapi import APIRouter, Response

from db import get_pool

router = APIRouter()


@router.get("/api/health")
async def health(response: Response):
    try:
        pool = await get_pool()
        await pool.fetchval("SELECT 1")
        return {"ok": True}
    except Exception:
        response.status_code = 500
        return {"ok": False}
