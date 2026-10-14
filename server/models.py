"""Pydantic request/response schemas — a FastAPI convention with no Flask/
Express equivalent to port from (index.js just read req.body/req.query
directly). Kept minimal: only the POST /api/search body needs validation
beyond what FastAPI's own query-param typing already gives the GET routes.
"""
import re

from pydantic import BaseModel, Field, field_validator

# Must match MAX_QUERY_LENGTH in frontend/src/lib/api.js. Generous for a
# real shopping request ("a smart look for my cousin's mehndi, nothing too
# shiny, under Rs 12,000" is ~80 chars), small enough that nobody can paste
# a novel into a prompt we pay per token for.
MAX_QUERY_LENGTH = 300

# Same set rag.py's VALID_GENDER_OVERRIDES accepts.
VALID_GENDERS = {"Women", "Men", "Boys", "Girls", "Unisex"}

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    gender: str | None = None

    @field_validator("query", mode="before")
    @classmethod
    def clean_query(cls, v):
        # Control characters (newlines from the Home textarea, NULs from a
        # script) become single spaces; this runs before the length check,
        # so "   " still fails min_length as an empty query.
        if not isinstance(v, str):
            raise ValueError("query must be a string")
        return " ".join(_CONTROL_CHARS.sub(" ", v).split())

    @field_validator("gender", mode="before")
    @classmethod
    def clean_gender(cls, v):
        # Unknown values (a hand-edited ?gender= URL) degrade to "no
        # override" instead of a 422 — the search still works, the model
        # just infers gender from the text as it would without the toggle.
        return v if v in VALID_GENDERS else None
