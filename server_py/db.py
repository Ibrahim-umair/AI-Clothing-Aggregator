"""Shared asyncpg connection pool — port of server/db.js.

Async (not psycopg2/sync, unlike Alexey Grigorev's fitness-assistant) on
purpose: the Node pipeline's biggest latency win is running the extraction
call and the embedding call concurrently (Promise.all), then the vector and
textual retrieval legs concurrently again. asyncio.gather + asyncpg is the
direct equivalent of that — a sync driver would silently serialize what was
concurrent in the original and quietly regress latency.
"""
import os

import asyncpg

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=os.environ.get("PGHOST", "localhost"),
            port=int(os.environ.get("PGPORT", "5433")),
            database=os.environ.get("PGDATABASE", "libas"),
            user=os.environ.get("PGUSER", "libas"),
            password=os.environ.get("PGPASSWORD", "libas_dev_password"),
            min_size=1,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
