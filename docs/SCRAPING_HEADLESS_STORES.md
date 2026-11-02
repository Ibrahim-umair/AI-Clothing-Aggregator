# Scraping headless (Hydrogen) Shopify stores

Findings from 2026-11-02, when Equator's scrape crashed. Read this before adding
a store, or when a store's `/products.json` starts returning 404.

## The problem

Some Shopify stores now run a headless storefront (Shopify Hydrogen on Oxygen
hosting) instead of a normal Liquid theme. You can tell from the homepage's
response header `powered-by: Shopify, Oxygen, Hydrogen`.

On a headless store, the bulk feeds our scraper uses (`/products.json` and
`/collections/*/products.json`) usually return 404. The data is fetched on the
store's own server, so the page also has no public Storefront API token to
borrow. Cougar did have one, but that was luck.

**Status on 2026-11-02:**

| Store | Platform | `/products.json` |
|---|---|---|
| Equator | Hydrogen | 404, scrape crashes |
| Breakout | Hydrogen | still works (can stop at any time) |
| Cougar | Hydrogen | 404; scraped via its public GraphQL token |
| The other 15 | Liquid | works |

## Options tested on Equator

### A. Shopify Storefront Catalog (`/api/ucp/mcp`): works, recommended

This is Shopify's official endpoint for AI shopping agents (UCP, the Universal
Commerce Protocol). Every Shopify store has it, headless or not. It worked on
both Equator (headless) and Outfitters (Liquid), and needs no token.

```
POST https://{store domain}/api/ucp/mcp      (JSON-RPC 2.0)
{"jsonrpc":"2.0","method":"tools/call","id":1,"params":{"name":"search_catalog",
 "arguments":{"meta":{"ucp-agent":{"profile":"<our agent profile URL>"}},
  "catalog":{"filters":{"price":{"min":0,"max":249999}},
             "context":{"address_country":"PK","currency":"PKR"},
             "pagination":{"limit":100,"cursor":"<from previous page>"}}}}}
```

**Gotchas:**
- `context` with `address_country: PK` is required. Without it the endpoint
  returns `-32603 Internal error`.
- A query or a filter is required. A filter on its own, with no search words,
  lists the catalogue.
- At most `limit: 100` per page. 250 errors.
- About 1,000 results per query, then `has_next_page` turns false. Get past
  this by slicing the catalogue on price (amounts are in paisa, the minor
  unit). For Equator, 4 slices (<2,500, 2,500-4,000, 4,000-6,000, 6,000+) gave
  1,633 unique products in 18 requests. Keep every slice under ~900 products;
  if one hits the cap, split it.
- Only in-stock products are listed (`filters.available` defaults to true). A
  product missing from the listing but still in the sitemap is sold out or
  unlisted.
- The `meta.ucp-agent.profile` must be a URL describing the agent. The test
  used Shopify's example profile. For production, host our own (libasai.com)
  that honestly describes Libas, and read Shopify's agentic-commerce terms
  first.
- About 17 KB per product, against ~4.5 KB with `/products.json`. That is fine
  from the server, but too heavy to run daily through the free Webshare
  proxies.

**Data per product:**
- id (`gid://shopify/Product/<n>`), handle, title, url
- description (html)
- tags and collections
- Shopify taxonomy category
- options
- every variant, including sold-out sizes: sku, size option, price and
  compare-at (`list_price`, in paisa), and `availability.available` per size

**Missing:** only one image per product. Full galleries have to come from
somewhere else (see C).

**IDs:** the number in `gid://shopify/Product/9014146826484` is the same ID the
REST feed gave (`9014146826484`), and variant IDs match the same way. Strip
the prefix and existing products, their reviewed category overrides and their
history carry over with no duplicates.

### B. Shopify Global Catalog (`catalog.shopify.com/api/ucp/mcp`): works, too thin

This searches across all Shopify merchants, and `filters.shops` can limit it to
one store (`gid://shopify/Shop/<shop id>`). It returns only one variant per
product and at most 50 per page, so there are no sizes or per-size stock. It is
not enough for our catalogue.

### C. Hydrogen loader data (`/collections/all.data?page=N`): works, photos only

- **Format:** React Router "turbo-stream", a flat JSON array where keys like
  `"_49"` point to other entries in the array. Decode it by resolving every
  index.
- **Page size:** 24 products, fixed; `limit` and `first` are ignored. The
  response includes `pagination.total` (2,118 for Equator) and `pageCount`.
- **Fields:** id, handle, title, product-level `available`, price,
  compare-at, and **all images**.
- **Missing:** variants, sizes, tags, description.
- **Caveat:** undocumented, and each store's Hydrogen app can shape it
  differently.

### D. Product loader data (`/products/<handle>.data`): works, one per product

This has everything: variants with stock, tags, type, vendor, description and
images. But it takes one request per product, which is too slow and too heavy
for a full pass. Use it only for a handful of products, such as new ones with
missing data.

### E. Product sitemap with lastmod: works, change detection

`/sitemap.xml` links to `/sitemap/products/1.xml`. One request returned all
2,118 Equator product URLs, each with a `<lastmod>` and an image. Hydrogen's
`lastmod` is the product's `updatedAt`. Use it to fetch only products changed
since the last run, and to count the catalogue.

### F to H: did not work for Equator

- **F. `/__shopify/api/<version>/graphql.json`** (the Hydrogen proxy): 403
  Forbidden without a token, on 2024-10 and 2025-07.
- **G. A public Storefront token in the page:** none. The five 32-character
  strings in Equator's HTML are homepage video IDs.
- **H. Third-party search services** (Algolia, Searchanise, Boost, Klevu and
  others), which often expose bulk product data with a public key: Equator
  uses none. Check for them first if a store ever leaves Shopify.

## Recommended approach for Shopify stores

1. **Products, sizes, stock, prices, tags, description:** Storefront Catalog
   (A), sliced by price. About 20 requests per 2,000 products.
2. **Photos:** the store's `/products.json` while it still works; otherwise
   Hydrogen collection data (C). Photos only need fetching for new products or
   when the sitemap shows a change.
3. **Daily runs:** the sitemap (E) decides what changed; re-fetch only that.
4. **Fallback:** `/products.json` stays the default for stores that still serve
   it.

## If a store leaves Shopify

- **WooCommerce:** public Store API, `/wp-json/wc/store/v1/products?per_page=100`.
- **Magento 2:** public GraphQL `products` query.
- **Other platforms:** look for the site's search provider (H) and its public
  key.
- **Sturdiest long term:** a product feed agreed directly with the brand.

## Sources

- https://shopify.dev/docs/agents/catalog/storefront-catalog
- https://shopify.dev/docs/agents/catalog/global-catalog
- https://shopify.dev/docs/agents/catalog
- https://hydrogen.shopify.dev/update/april-2026-release
- https://github.com/Shopify/hydrogen/pull/1922/files (sitemap lastmod = updatedAt)
