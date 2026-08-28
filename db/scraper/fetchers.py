"""
Live HTTP fetchers for the 15 stores. This is the one piece of the pipeline
that has no prior working implementation to reuse — the original one-time
scrape's fetch code ran in a throwaway scratchpad and no longer exists;
only its JSONL output and progress.log survived. Rebuilt here from the
confirmed request pattern in scraped_data/progress.log (14 REST stores)
and the confirmed output shape in scraped_data/cougar.jsonl (the 1 GraphQL
store), not from the original source.
"""
import time

import requests

PAGE_SIZE = 250
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "Mozilla/5.0 (compatible; LibasAggregatorBot/1.0)"


class StoreFetchError(Exception):
    """Raised when a store's fetch fails after exhausting all retries. The
    orchestrator catches this per-store — one broken store never aborts a
    run across the other 14."""


def _request_with_retry(fn, store_label, max_retries, backoff_base_seconds):
    """Calls fn() (a zero-arg callable performing one HTTP request),
    retrying on 429/5xx/timeout/connection errors with exponential backoff.
    Honors a 429's Retry-After header when present. Raises StoreFetchError
    after max_retries, wrapping the last underlying exception."""
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = fn()
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else backoff_base_seconds * (2 ** (attempt - 1))
                time.sleep(min(delay, 300))
                continue
            if resp.status_code >= 500:
                last_exc = requests.HTTPError(f"{resp.status_code} from {store_label}")
                time.sleep(backoff_base_seconds * (2 ** (attempt - 1)))
                continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(backoff_base_seconds * (2 ** (attempt - 1)))
    raise StoreFetchError(f"[{store_label}] failed after {max_retries} attempts: {last_exc}")


def fetch_rest_store(base_url, session, pacer, store_label, max_retries=5, backoff_base_seconds=2):
    """Yields raw product dicts from a Shopify Liquid/REST store's public
    /products.json endpoint, paginating with limit=250 until an empty page
    — the exact pattern confirmed for all 14 non-Cougar stores in
    scraped_data/progress.log."""
    page = 1
    while True:
        pacer.wait()
        url = f"{base_url}/products.json"

        def do_request(u=url, pg=page):
            return session.get(
                u, params={"limit": PAGE_SIZE, "page": pg},
                headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS,
            )

        resp = _request_with_retry(do_request, store_label, max_retries, backoff_base_seconds)
        products = (resp.json() or {}).get("products") or []
        if not products:
            return
        for p in products:
            yield p
        if len(products) < PAGE_SIZE:
            return
        page += 1


# Shopify Storefront GraphQL query, reconstructed from the field set present
# in scraped_data/cougar.jsonl (id, title, handle, productType, vendor,
# tags, descriptionHtml, priceRange, images/variants as edges-of-node,
# selectedOptions) — this is a best-effort reconstruction, not a copy of
# whatever the original scrape actually sent, since that source is gone.
_COUGAR_PRODUCTS_QUERY = """
query Products($first: Int!, $after: String) {
  products(first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        handle
        productType
        vendor
        tags
        descriptionHtml
        priceRange { minVariantPrice { amount currencyCode } }
        images(first: 20) { edges { node { url altText } } }
        variants(first: 100) {
          edges {
            node {
              id
              title
              sku
              availableForSale
              price { amount }
              selectedOptions { name value }
            }
          }
        }
      }
    }
  }
}
"""


def fetch_graphql_store(base_url, session, pacer, store_label, storefront_token,
                         max_retries=5, backoff_base_seconds=2, api_version="2024-01"):
    """Yields raw product dicts (already unwrapped from the GraphQL edge/
    node envelope down to the same 'node' shape load_data.py's is_graphql
    branch expects) from a Shopify Hydrogen storefront's GraphQL API.

    Requires a Storefront API access token (public-data token, not an
    Admin API secret) — Hydrogen storefronts embed one in their own
    frontend bundle for exactly this kind of public product query. This
    could not be recovered from the original scrape (its source no longer
    exists), so it must be supplied via storefront_token — see
    run_scrape.py for where that's read from (COUGAR_STOREFRONT_TOKEN env
    var). Raises StoreFetchError immediately, no retries, if no token is
    configured — that's a config problem, not a transient failure.
    """
    if not storefront_token:
        raise StoreFetchError(
            f"[{store_label}] no Storefront API token configured — set COUGAR_STOREFRONT_TOKEN "
            "(find it in the site's own frontend network requests: a header named "
            "X-Shopify-Storefront-Access-Token on a request to /api/*/graphql.json)"
        )

    endpoint = f"{base_url}/api/{api_version}/graphql.json"
    after = None
    while True:
        pacer.wait()

        def do_request(a=after):
            return session.post(
                endpoint,
                json={"query": _COUGAR_PRODUCTS_QUERY, "variables": {"first": PAGE_SIZE, "after": a}},
                headers={
                    "User-Agent": USER_AGENT,
                    "X-Shopify-Storefront-Access-Token": storefront_token,
                    "Content-Type": "application/json",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        resp = _request_with_retry(do_request, store_label, max_retries, backoff_base_seconds)
        payload = resp.json()
        if "errors" in payload:
            raise StoreFetchError(f"[{store_label}] GraphQL errors: {payload['errors']}")
        data = (payload.get("data") or {}).get("products") or {}
        edges = data.get("edges") or []
        for e in edges:
            yield e["node"]
        page_info = data.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return
        after = page_info.get("endCursor")
