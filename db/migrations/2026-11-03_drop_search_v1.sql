-- Remove the original search (v1): its vector and keyword columns and their
-- indexes. Search v2 (server/search_v2.py) uses embedding_v2 and
-- search_vector_v2 only. Also drops the beta test's leftover tables (already
-- gone on prod). Safe to re-run.
--
-- PRODUCTION: run only together with the backend-revamp deploy. The API on
-- master still runs v1 and needs these columns.
--
-- DROP COLUMN only marks the space free. VACUUM FULL gives it back to the
-- disk and shrinks the indexes that remain, but it rewrites the table and
-- locks it while it runs (a few minutes for ~56K products, so search is down
-- meanwhile), and needs free disk about the size of the new table. Run it as
-- its own step, outside a transaction:
--     VACUUM (FULL, ANALYZE) products;

DROP INDEX IF EXISTS idx_products_embedding_hnsw;
DROP INDEX IF EXISTS idx_products_search_vector;
ALTER TABLE products DROP COLUMN IF EXISTS embedding;
ALTER TABLE products DROP COLUMN IF EXISTS search_vector;
DROP TABLE IF EXISTS beta_enrich;
DROP TABLE IF EXISTS beta_colors;
