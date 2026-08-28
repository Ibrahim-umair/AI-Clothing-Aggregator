-- Libas apparel aggregator — finalized schema
-- Matches the design reviewed in "The Ledger" artifact.

-- pgvector — required for products.embedding (semantic search). Installed
-- into the live container via `apt-get install postgresql-16-pgvector`
-- (not in the base postgres:16 image); a fresh setup needs the same
-- package installed before this file runs, or swap the image for
-- pgvector/pgvector:pg16 in docker-compose.yml.
CREATE EXTENSION IF NOT EXISTS vector;

-- ============ ENUMS ============
CREATE TYPE platform_type_enum       AS ENUM ('liquid_rest', 'hydrogen_graphql');
CREATE TYPE style_family_enum        AS ENUM ('western', 'eastern', 'unisex_basic', 'unknown', 'not_applicable');
CREATE TYPE construction_status_enum AS ENUM ('ready_to_wear', 'unstitched_fabric', 'semi_stitched', 'not_applicable');
CREATE TYPE age_group_enum           AS ENUM ('adult', 'teen', 'junior', 'toddler', 'infant');
CREATE TYPE size_system_enum         AS ENUM ('alpha', 'waist_inches', 'kids_age_years', 'volume_ml', 'one_size', 'none');

-- ============ REFERENCE / LOOKUP TABLES ============
CREATE TABLE brands (
    id            SERIAL PRIMARY KEY,
    slug          TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    base_url      TEXT NOT NULL,
    platform_type platform_type_enum NOT NULL
);

CREATE TABLE categories (
    id         SERIAL PRIMARY KEY,
    parent_id  INT REFERENCES categories(id),
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL,
    sort_order SMALLINT NOT NULL DEFAULT 0,
    UNIQUE (parent_id, slug)
);

CREATE TABLE fabrics (
    id   SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE colors (
    id             SERIAL PRIMARY KEY,
    canonical_name TEXT UNIQUE NOT NULL,
    hex_approx     CHAR(7)
);

-- ============ SCRAPE AUDIT (created before products/variants since they reference it) ============
CREATE TABLE scrape_runs (
    id                 BIGSERIAL PRIMARY KEY,
    brand_id           INT NOT NULL REFERENCES brands(id),
    tier               TEXT NOT NULL DEFAULT 'daily', -- 'daily' (full sweep) or 'hourly' (availability-only)
    started_at         TIMESTAMPTZ NOT NULL,
    finished_at        TIMESTAMPTZ,
    product_count      INT,
    status             TEXT NOT NULL DEFAULT 'running',
    products_new       INT DEFAULT 0,
    products_updated   INT DEFAULT 0,
    products_removed   INT DEFAULT 0,
    products_unchanged INT DEFAULT 0,
    error_message      TEXT
);

-- ============ CORE ENTITIES ============
CREATE TABLE products (
    id                  BIGSERIAL PRIMARY KEY,
    brand_id            INT NOT NULL REFERENCES brands(id),
    native_product_id   TEXT NOT NULL,
    handle              TEXT,
    title               TEXT NOT NULL,
    description         TEXT,
    category_id         INT REFERENCES categories(id),
    style_family        style_family_enum NOT NULL DEFAULT 'unknown',
    construction_status construction_status_enum NOT NULL DEFAULT 'not_applicable',
    age_group           age_group_enum,
    piece_count         SMALLINT,
    pack_quantity       SMALLINT,
    is_browsable        BOOLEAN NOT NULL DEFAULT TRUE,
    tags                TEXT[],
    tags_cleaned        TEXT[],
    field_confidence    JSONB,
    raw_source          JSONB NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- text-embedding-3-large, truncated to 1536 dims (OpenAI's supported
    -- `dimensions` param) — pgvector's indexable limit for the plain
    -- `vector` type is 2000, so the full 3072-dim output doesn't fit.
    -- Embedded text = title + full category path + brand + description;
    -- price/numeric fields deliberately excluded (that's the structured
    -- filter path's job, not semantic search's). NULL until
    -- db/embed_products.py has run for a given product.
    embedding           vector(1536),
    UNIQUE (brand_id, native_product_id)
);

CREATE TABLE product_pieces (
    id            BIGSERIAL PRIMARY KEY,
    product_id    BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    piece_name    TEXT,
    fabric_id     INT REFERENCES fabrics(id),
    length_meters NUMERIC(4,1),
    sort_order    SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE product_images (
    id         BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    url        TEXT NOT NULL,
    position   SMALLINT NOT NULL DEFAULT 0,
    alt_text   TEXT
);

CREATE TABLE variants (
    id                  BIGSERIAL PRIMARY KEY,
    product_id          BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    native_variant_id   TEXT NOT NULL,
    color_id            INT REFERENCES colors(id),
    size_label          TEXT,
    size_system         size_system_enum NOT NULL DEFAULT 'none',
    sku                 TEXT,
    current_price       NUMERIC(10,2),
    current_compare_at  NUMERIC(10,2),
    current_available   BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (product_id, native_variant_id)
);

CREATE TABLE variant_snapshots (
    id               BIGSERIAL PRIMARY KEY,
    variant_id       BIGINT NOT NULL REFERENCES variants(id) ON DELETE CASCADE,
    scrape_run_id    BIGINT REFERENCES scrape_runs(id),
    observed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    price            NUMERIC(10,2),
    compare_at_price NUMERIC(10,2),
    available        BOOLEAN NOT NULL
);

-- ============ INDEXES ============
CREATE INDEX idx_products_brand      ON products(brand_id);
CREATE INDEX idx_products_category   ON products(category_id);
CREATE INDEX idx_products_style      ON products(style_family, construction_status);
CREATE INDEX idx_variants_product    ON variants(product_id);
CREATE INDEX idx_snapshots_variant   ON variant_snapshots(variant_id, observed_at DESC);
CREATE INDEX idx_categories_parent   ON categories(parent_id);
CREATE INDEX idx_pieces_product      ON product_pieces(product_id);
CREATE INDEX idx_images_product      ON product_images(product_id);
