-- Salesforce Commerce Cloud stores (Khaadi, Sapphire): no product feed, the
-- scraper reads product pages (db/scraper/fetch_sfcc.py).
ALTER TYPE platform_type_enum ADD VALUE IF NOT EXISTS 'sfcc';
