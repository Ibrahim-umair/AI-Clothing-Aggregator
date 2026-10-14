"""FastAPI app + router registration — port of server/index.js. Thin on
purpose: all real logic lives in rag.py/query_helpers.py/taxonomy_tree.py/
the routes/ modules, same separation as the Node version's index.js
(routing only) vs search.js/queryHelpers.js/taxonomyTree.js (logic).
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

from db import close_pool, get_pool  # noqa: E402  (after dotenv load, same as Node's search.js)
from db_conversations import init_db, purge_old_search_logs  # noqa: E402
from routes import brands, health, products, search, seo, taxonomy  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()  # pre-warm the pool instead of paying for it on the first request
    await init_db()  # idempotent CREATE TABLE IF NOT EXISTS — see db_conversations.py
    purge_task = asyncio.create_task(_purge_search_logs_daily())
    # Future OpenTelemetry hook point: FastAPI/asyncpg/OpenAI auto-
    # instrumentation would be wired up here (see MIGRATION_REPORT.md —
    # deliberately not built yet, Postgres+Grafana only for now).
    yield
    purge_task.cancel()
    await close_pool()


async def _purge_search_logs_daily() -> None:
    while True:
        try:
            deleted = await purge_old_search_logs()
            if deleted:
                logging.getLogger("libas").info("purged %d search_logs rows past retention", deleted)
        except Exception:  # a failed purge must never take the API down
            logging.getLogger("libas").exception("search_logs retention purge failed")
        await asyncio.sleep(86400)


app = FastAPI(title="Libas API", lifespan=lifespan)

# Only the real frontend may call the API from a browser — "*" let any site
# embed our (paid-per-call) search in its own page. Overridable via
# ALLOWED_ORIGINS (comma-separated) for a custom domain or a preview URL.
_DEFAULT_ORIGINS = (
    "https://ai-clothing-aggregator.ibrahimumair900.workers.dev,"
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
)
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["Retry-After"],
)

# FastAPI's interactive docs load their JS/CSS from a CDN, so they get the
# standard headers but not the lock-everything-down CSP the JSON routes do.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    # HTTP->HTTPS redirection itself is Caddy's job in production (it does
    # it automatically for any site with a certificate); HSTS makes browsers
    # skip the plain-HTTP hop entirely on every later visit.
    h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("X-Frame-Options", "DENY")
    # Belt and braces with /robots.txt: even if a crawler finds an API URL
    # through a link, the JSON itself is never indexed.
    h.setdefault("X-Robots-Tag", "noindex, nofollow")
    if not request.url.path.startswith(_DOCS_PATHS):
        h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    return response

app.include_router(products.router)
app.include_router(search.router)
app.include_router(brands.router)
app.include_router(taxonomy.router)
app.include_router(health.router)
app.include_router(seo.router)

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "4000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
