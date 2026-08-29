"""Pydantic request/response schemas — a FastAPI convention with no Flask/
Express equivalent to port from (index.js just read req.body/req.query
directly). Kept minimal: only the POST /api/search body needs validation
beyond what FastAPI's own query-param typing already gives the GET routes.
"""
from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    gender: str | None = None
