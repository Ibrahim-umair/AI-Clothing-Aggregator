"""Placeholder for phase 4 (Postgres logging + Grafana). Wired into
routes/search.py now so that phase's code is already in its final shape;
log_search is a no-op until phase 4 replaces this file.
"""


async def log_search(*, query: str, gender_override: str | None, result: dict, metrics: dict) -> None:
    pass
