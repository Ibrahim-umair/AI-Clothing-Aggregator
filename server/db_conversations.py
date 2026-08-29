"""Search-quality logging — NEW capability, the Node version never
recorded any of this. Modeled on alexeygrigorev/fitness-assistant's
db.py (init_db/save_conversation split), adapted to OUR domain: we don't
generate a text answer for an LLM judge to score (this is structured
extraction + retrieval, not FAQ Q&A), so there's no relevance-judgment
column here — the closest useful proxy is total_matches (did the hard
filters even find anything) and results_returned.

Logged via FastAPI BackgroundTasks (see routes/search.py), i.e. AFTER the
response is already sent to the user — both Alexey Grigorev's lesson 14
and the observability article flag synchronous logging as a real
production gap, and it's essentially free to fix now.
"""
from db import get_pool


async def init_db() -> None:
    pool = await get_pool()
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS search_logs (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            query TEXT NOT NULL,
            gender_override TEXT,
            resolved_gender TEXT,
            categories TEXT[],
            min_price NUMERIC,
            max_price NUMERIC,
            brand TEXT,
            colors TEXT[],
            semantic_query TEXT,
            total_matches INT,
            results_returned INT,
            extract_model TEXT,
            extract_input_tokens INT,
            extract_output_tokens INT,
            extract_latency_ms NUMERIC,
            embed_model TEXT,
            embed_input_tokens INT,
            embed_latency_ms NUMERIC,
            total_latency_ms NUMERIC,
            cost_usd NUMERIC
        )
        """
    )
    # Recent-queries panel and the response-time timeseries both filter/
    # sort by this column on every load.
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_search_logs_created_at ON search_logs (created_at DESC)")


async def log_search(*, query: str, gender_override: str | None, result: dict, metrics: dict) -> None:
    filters = result.get("filters", {})
    extract = metrics["extract"]
    embed = metrics["embed"]
    cost_usd = (extract.cost_usd or 0) + (embed.cost_usd or 0)
    # Both models unpriced (see metrics.py) means "genuinely unknown", not
    # "free" — NULL is the honest value, not 0.
    if extract.cost_usd is None and embed.cost_usd is None:
        cost_usd = None

    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO search_logs (
            query, gender_override, resolved_gender, categories, min_price, max_price,
            brand, colors, semantic_query, total_matches, results_returned,
            extract_model, extract_input_tokens, extract_output_tokens, extract_latency_ms,
            embed_model, embed_input_tokens, embed_latency_ms, total_latency_ms, cost_usd
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
        """,
        query,
        gender_override,
        filters.get("gender"),
        filters.get("categories") or [],
        filters.get("minPrice"),
        filters.get("maxPrice"),
        filters.get("brand"),
        filters.get("colors") or [],
        filters.get("semantic_query"),
        metrics["total_matches"],
        metrics["results_returned"],
        extract.model,
        extract.input_tokens,
        extract.output_tokens,
        extract.latency_ms,
        embed.model,
        embed.input_tokens,
        embed.latency_ms,
        metrics["total_latency_ms"],
        cost_usd,
    )
