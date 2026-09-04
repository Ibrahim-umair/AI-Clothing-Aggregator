<h1 align="center">Libas</h1>

<p align="center">One catalog for Pakistan's biggest apparel brands — real-time prices and stock, unified into a single taxonomy, searchable in plain English.</p>

**Live demo**: [ai-clothing-aggregator.ibrahimumair900.workers.dev](https://ai-clothing-aggregator.ibrahimumair900.workers.dev)

## Overview

18 Pakistani apparel retailers each run their own storefront, their own naming conventions, and their own idea of what category a product belongs in. Libas scrapes all of them on a schedule, normalizes ~114,000 real products into one consistent taxonomy, and puts a single storefront in front of the result — so "show me men's kurtas under Rs. 3,000" returns products from every brand that has one, not just whichever site you happened to open.

The interesting engineering problem here isn't the scraping — it's turning messy, inconsistent, brand-specific product data (different naming conventions, different category buckets, different sizing systems, different template quirks per storefront) into one taxonomy a shopper can actually browse and an LLM can actually search over, without either silently mis-filing products or hallucinating ones that don't exist.

## Features

- **Natural-language product search** — "cozy warm sweaters for women under 5000" resolves to structured filters (category, price, gender, color, size) via an LLM function call, not keyword matching
- **Hybrid retrieval** — vector search (pgvector) fused with a textual leg via Reciprocal Rank Fusion, so both semantic intent and exact keyword matches count
- **Result diversification** — round-robins by category-then-brand so results read as a genuine mix instead of "all Zellbury shirts, then all Furor polos" (a real reported bug, root-caused and fixed — see `rag.py`'s own `diversify()`)
- **Unified taxonomy across 18 brands** — gender → branch (Western/Eastern/Accessories/Fragrance & Beauty) → sub-category → leaf, built from per-brand raw scrape data with no manual tagging
- **Incremental scraping** — a daily full sweep plus an hourly availability-only pass per store, with per-store rate limiting, retry logic, and canary alerting if a store's fetched-product-count suddenly drops (a real signal something broke upstream)
- **Cost/latency/quality monitoring** — every search logged with tokens, latency, and estimated cost, visualized on a live Grafana dashboard

## Architecture

**Data collection** (`db/scraper/`): each brand is scraped via its own Shopify Storefront API (one brand required reverse-engineering a GraphQL-only storefront with no REST endpoint). A daily run does a full sweep — fetch, classify, diff against what's stored — while an hourly run only checks price/availability, skipping the expensive reclassification step. Soft-deletes products a store stops listing rather than deleting them outright, so history isn't lost.

**Classification** (`db/load_data.py`): the highest-maintenance, most-tested part of the codebase. Turns each store's raw title/description/tags/vendor into a `(gender, branch, sub, category)` tuple, since no store's own categorization is trustworthy or consistent enough to use directly — a "vest" from one brand is a puffer jacket, from another it's a sleeveless sweater, from a third it's a plain tank top, and the only way to tell them apart is to actually read the real product (title, description, and — when text alone is ambiguous — the real photo). 280 regression tests and a 100+ entry changelog document every one of these as a real bug against real data, not a hypothetical.

**Search** (`server/rag.py`): a user's query is embedded (OpenAI `text-embedding-3-large`) and, in parallel, sent through a function-calling extraction step that pulls out structured filters (category, price range, gender, color, size). The structured filters narrow the SQL query; the embedding drives a vector-similarity leg over the narrowed set; a textual leg runs alongside it; both are fused with Reciprocal Rank Fusion (70% vector / 30% textual) and the final list is diversified so no single brand or category dominates the page.

## Data Quality & Testing

Classification correctness is treated as a first-class, continuously-audited problem, not a one-time script run. `db/CHANGELOG.md` documents 100+ real miscategorization bugs found and fixed — each entry names the actual product, the actual brand, and the actual wrong-vs-right category, with the fix verified by re-querying the live catalog afterward (and, for genuinely ambiguous cases text alone can't resolve, by pulling the real product photo before deciding). `db/test_classify.py` — 280 checks — is the regression guard: every fix here starts as a failing test built from a real title/description that was resolving wrong, and the suite runs before any change to the classifier ships.

## Tech Stack

- **PostgreSQL + pgvector** — relational product/variant/pricing data and vector search in one database
- **FastAPI** — async Python backend (`asyncpg`, no ORM)
- **OpenAI API** — query embeddings, structured-filter extraction (function calling), natural-language answer text
- **React + Vite** — storefront frontend
- **Docker Compose** — Postgres, Grafana, and the API, all orchestrated together for local dev
- **AWS EC2** — production backend, administered exclusively via SSM Session Manager (no SSH, no open port 22)
- **Caddy** — automatic HTTPS in production via a `nip.io` wildcard hostname, avoiding a domain purchase entirely
- **Cloudflare Workers** — static frontend hosting, deployed via `wrangler` through a GitHub Actions pipeline on every push
- **Grafana** — search cost, latency, and quality monitoring

## Getting Started

Requires Python 3.13, Node, Docker, and an OpenAI API key.

```powershell
cd db
docker compose up -d              # Postgres + Grafana + the FastAPI API, all three
python load_data.py               # one-time: seed brands + load a scraped dataset
python test_classify.py           # regression suite for the classifier — 280 checks
```

Frontend:

```powershell
cd frontend
npm install
npm run dev                       # expects the backend already running via docker compose
```

A CLI is also included for debugging the search pipeline directly — prints the raw LLM tool-call output, each retrieval leg's ranked results, and the final fused list:

```powershell
cd server
python cli.py "furor jeans"
python cli.py "cozy warm sweaters for women under 5000"
```

Running the scraper against live stores:

```powershell
cd db/scraper
python run_scrape.py --all                # full sweep, every store
python run_scrape.py --tier hourly         # availability-only pass
python run_scrape.py --dry-run --store cambridge   # preview, writes nothing
```

## API

| Route | Description |
|---|---|
| `GET /api/health` | Liveness check |
| `GET /api/products` | Filterable/paginated product listing (gender, category, brand, price, color, size, sort) |
| `GET /api/products/{id}` | Single product detail, with per-color size/availability |
| `POST /api/search` | `{query, gender?}` — natural-language search, returns matched products + a generated response |
| `GET /api/brands` | All active brands |
| `GET /api/taxonomy` | Full category tree with live per-node product counts |

## Monitoring

Every `/api/search` call is logged to Postgres — resolved filters, latency, token counts, estimated OpenAI cost — and visualized on a Grafana dashboard provisioned automatically from `db/monitoring/grafana/`.

## Project Structure

```
📁server/                  FastAPI backend
  🐍rag.py                 hybrid search: extraction, embedding, RRF fusion, diversification
  🐍cli.py                 interactive search-pipeline debug tool
  📁routes/                products, search, brands, taxonomy, health
📁db/
  🐍load_data.py           per-store classification: raw scrape data -> unified taxonomy
  🐍test_classify.py       280-check regression suite for the classifier
  🐍backfill_categories.py re-classifies the existing catalog after a classifier change
  📄CHANGELOG.md           100+ real classification bugs, each with the fix and verification
  📁scraper/               per-store scraping, incremental (daily + hourly) scheduling
  📁monitoring/grafana/    dashboard + data source provisioning
📁frontend/                React + Vite storefront
🐳docker-compose.yml
```
