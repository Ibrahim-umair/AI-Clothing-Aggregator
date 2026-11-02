-- Equator went headless (Shopify Hydrogen): no /products.json any more. It is
-- now fetched through the Shopify Storefront Catalog, see
-- docs/SCRAPING_HEADLESS_STORES.md and scraper/fetch_ucp.py. Safe to re-run.
ALTER TYPE platform_type_enum ADD VALUE IF NOT EXISTS 'shopify_ucp';
UPDATE brands SET platform_type = 'shopify_ucp' WHERE slug = 'equator';
