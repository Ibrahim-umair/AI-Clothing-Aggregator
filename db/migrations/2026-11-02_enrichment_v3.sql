-- Enrichment v3 (docs/NEXT_RUN_SPEC.md section 6): storage for the Luna run.
-- New tables and nullable columns only, so the current search keeps working
-- and nothing existing changes until the apply step writes. Safe to re-run.

-- The raw answer for each product, kept as returned. The apply step reads
-- from here, so it can be re-run (or changed) without paying for the LLM again.
CREATE TABLE IF NOT EXISTS ai_enrichment (
    product_id     BIGINT PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    result         JSONB NOT NULL,         -- the model's JSON, unchanged
    model          TEXT NOT NULL,
    prompt_version TEXT NOT NULL,          -- e.g. v3-r9
    batch_id       TEXT,
    photos_sent    SMALLINT[],             -- photo positions sent, in order (Photo 1 = first)
    usage          JSONB,                  -- tokens in/out/cached, cost
    valid          BOOLEAN NOT NULL,       -- schema, category path and looks_like checks
    problems       TEXT[],                 -- what failed, when not valid
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at     TIMESTAMPTZ,            -- NULL until the apply step has used it
    -- The product's AI columns before the apply step overwrote them, for undo.
    -- Category changes are undone through category_overrides instead.
    old            JSONB
);
CREATE INDEX IF NOT EXISTS idx_ai_enrichment_unapplied ON ai_enrichment(product_id) WHERE applied_at IS NULL;

-- Applied values, read by search and the site.
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_audience text;             -- Men/Women/Unisex/Boys/Girls/Kids
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_audience_confidence text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_category_id int REFERENCES categories(id);
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_category_confidence text;  -- high/medium/low
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_category_reason text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_proposed_category text;    -- set when the answer was NONE
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_not_apparel boolean;
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_descriptors jsonb;         -- the full descriptors object
-- Ladders as ordered numbers so search can say "at least office" or "not
-- sheer". NULL = n/a or not clear, and a filter never excludes NULL.
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_dress_from smallint;      -- 0 casual, 1 smart casual, 2 office, 3 party, 4 wedding
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_dress_to smallint;
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_warmth smallint;          -- 0 light, 1 medium, 2 warm
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_embellishment smallint;   -- 0 plain, 1 printed, 2 light, 3 medium, 4 heavy
ALTER TABLE products ADD COLUMN IF NOT EXISTS ai_sheerness smallint;       -- 0 opaque, 1 lined, 2 semi-sheer, 3 sheer

CREATE INDEX IF NOT EXISTS idx_products_ai_descriptors ON products USING gin (ai_descriptors jsonb_path_ops);

-- One row per colour version the photos show. Rewritten as a whole when a
-- product is enriched again.
CREATE TABLE IF NOT EXISTS product_color_versions (
    id           BIGSERIAL PRIMARY KEY,
    product_id   BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    idx          SMALLINT NOT NULL,         -- position in the model's versions list
    main_color   TEXT NOT NULL,
    secondary    JSONB NOT NULL DEFAULT '[]',  -- [{color, share: equal|part}]
    details      JSONB NOT NULL DEFAULT '[]',  -- [{color, where}]; never a colour match
    pattern      TEXT,
    photo_positions SMALLINT[],             -- product_images.position of the photos showing it
    -- For search: a full colour match (main + "equal" secondaries) and a
    -- weaker one ("part" secondaries). Filled by the apply step.
    match_colors TEXT[] NOT NULL,
    part_colors  TEXT[] NOT NULL DEFAULT '{}',
    UNIQUE (product_id, idx)
);
CREATE INDEX IF NOT EXISTS idx_color_versions_match ON product_color_versions USING gin (match_colors);
CREATE INDEX IF NOT EXISTS idx_color_versions_part ON product_color_versions USING gin (part_colors);

-- Which version each variant belongs to (from color_map), so stock is known
-- per version. NULL when the store gives no colour or the model couldn't map it.
ALTER TABLE variants ADD COLUMN IF NOT EXISTS color_version_id bigint
    REFERENCES product_color_versions(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_variants_color_version ON variants(color_version_id);
