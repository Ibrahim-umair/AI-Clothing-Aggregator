"""Pydantic request/response schemas — a FastAPI convention with no Flask/
Express equivalent to port from (index.js just read req.body/req.query
directly). Kept minimal: only the POST /api/search body needs validation
beyond what FastAPI's own query-param typing already gives the GET routes.
"""
from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    gender: str | None = None
    # "v1" or "v2"; None = the server default (SEARCH_ENGINE env var).
    engine: str | None = None
    # Earlier turns of THIS chat thread, sent by the browser (the server
    # keeps no session): [{"query": ..., "plan": {...how it was read...}}],
    # oldest first. Lets "now in blue" refine the previous search. Only
    # search v2 uses it; capped server-side.
    history: list[dict] | None = None
