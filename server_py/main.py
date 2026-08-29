"""FastAPI app + router registration — port of server/index.js. Thin on
purpose: all real logic lives in rag.py/query_helpers.py/taxonomy_tree.py/
the routes/ modules, same separation as the Node version's index.js
(routing only) vs search.js/queryHelpers.js/taxonomyTree.js (logic).
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

from db import close_pool, get_pool  # noqa: E402  (after dotenv load, same as Node's search.js)
from db_conversations import init_db  # noqa: E402
from routes import brands, health, products, search, taxonomy  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()  # pre-warm the pool instead of paying for it on the first request
    await init_db()  # idempotent CREATE TABLE IF NOT EXISTS — see db_conversations.py
    # Future OpenTelemetry hook point: FastAPI/asyncpg/OpenAI auto-
    # instrumentation would be wired up here (see MIGRATION_REPORT.md —
    # deliberately not built yet, Postgres+Grafana only for now).
    yield
    await close_pool()


app = FastAPI(title="Libas API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router)
app.include_router(search.router)
app.include_router(brands.router)
app.include_router(taxonomy.router)
app.include_router(health.router)

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "4000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
