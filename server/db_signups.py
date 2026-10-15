"""Coming-soon page email capture. Separate table from search_logs (not
reusing it) since these are unrelated concerns — a launch-notification
list, not search telemetry. UNIQUE on email + ON CONFLICT DO NOTHING so a
visitor submitting twice (double-click, retry after a flaky network) is a
silent no-op instead of a duplicate row or a constraint-violation error
bubbling up as a 500.
"""
from db import get_pool


async def init_db() -> None:
    pool = await get_pool()
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS email_signups (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            email TEXT NOT NULL UNIQUE
        )
        """
    )


async def save_signup(email: str) -> None:
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO email_signups (email) VALUES ($1) ON CONFLICT (email) DO NOTHING",
        email,
    )
