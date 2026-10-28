-- Manual (and later LLM) category decisions that the keyword rules must not
-- undo. The daily scrape, load_data.py and backfill_categories.py all
-- rewrite products.category_id from the keyword rules; the trigger below
-- puts the override back on every insert/update, whichever script wrote it.
--
-- Undo one product: DELETE FROM category_overrides WHERE product_id = X,
-- then UPDATE products SET category_id = <old_category_id>, is_browsable = true.
-- db/apply_category_overrides.py --undo <source> does this for a whole source.

CREATE TABLE IF NOT EXISTS category_overrides (
    product_id         INT PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    category_id        INT REFERENCES categories(id),   -- NULL = keep the rules' category
    hide               BOOLEAN NOT NULL DEFAULT false,  -- not apparel: keep out of the site
    old_category_id    INT,
    old_ai_category_ok BOOLEAN,
    source             TEXT NOT NULL,                   -- e.g. review-round1, newcat-scan
    note               TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_category_overrides_source ON category_overrides(source);

CREATE OR REPLACE FUNCTION apply_category_override() RETURNS trigger AS $$
DECLARE
    o RECORD;
BEGIN
    SELECT category_id, hide INTO o FROM category_overrides WHERE product_id = NEW.id;
    IF FOUND THEN
        IF o.category_id IS NOT NULL THEN
            NEW.category_id := o.category_id;
        END IF;
        IF o.hide THEN
            NEW.is_browsable := false;
        END IF;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_category_override ON products;
CREATE TRIGGER trg_category_override
    BEFORE INSERT OR UPDATE OF category_id, is_browsable ON products
    FOR EACH ROW EXECUTE FUNCTION apply_category_override();
