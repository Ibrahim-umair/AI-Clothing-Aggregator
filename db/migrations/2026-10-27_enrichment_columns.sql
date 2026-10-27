-- Search revamp (backend-revamp branch): new columns only. Nothing existing
-- is changed, so the current search keeps working untouched and rolling
-- back is just "stop reading these columns".
--
-- Plain nullable columns (no defaults, no generated columns) so ADD COLUMN
-- is instant even on the full products table. Safe to re-run.

-- Filled by db/enrich_products.py: a vision LLM's color-free description of
-- the product (cut, fit, prints, details) and open shopper-word tags.
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_description text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_tags text[];
-- What the LLM thinks the garment is, and whether that agrees with the
-- stored category. Review signal only: nothing filters on it.
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_looks_like text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_category_ok boolean;
-- Model, photos sent, token counts, timestamp.
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_meta jsonb;

-- Filled by db/embed_products_v2.py from the store text plus the AI text.
ALTER TABLE products ADD COLUMN IF NOT EXISTS embedding_v2 vector(1536);
-- Keyword leg for search v2: title (A), AI tags + AI description (B),
-- store description (C). Filled by the same script, not GENERATED, because
-- array_to_string isn't immutable.
ALTER TABLE products ADD COLUMN IF NOT EXISTS search_vector_v2 tsvector;

-- Filled by db/map_color_families.py: plain color families for each store
-- color name, e.g. 'Dark Olive' -> {olive, green}, 'OLIVE&WHITE' ->
-- {olive, green, white}. Empty array = couldn't tell (e.g. 'SOUL').
ALTER TABLE colors ADD COLUMN IF NOT EXISTS families text[];

CREATE INDEX IF NOT EXISTS idx_products_search_vector_v2 ON products USING gin (search_vector_v2);
CREATE INDEX IF NOT EXISTS idx_colors_families ON colors USING gin (families);
-- The HNSW index on embedding_v2 is created by embed_products_v2.py after
-- the vectors are written (building it on an empty column is pointless).
