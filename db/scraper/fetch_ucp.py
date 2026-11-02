"""
Fetcher for headless (Hydrogen) Shopify stores that no longer serve
/products.json. See docs/SCRAPING_HEADLESS_STORES.md for what was tested.

Three sources, each used for what it is complete and reliable for:
- Product sitemap: the full list of product handles (the completeness check).
- Shopify Storefront Catalog (/api/ucp/mcp, search_catalog): every product
  with every variant, size, price and per-size stock. Sold-out products are
  included by asking for both available=true and available=false.
- Hydrogen collection loader data (/collections/all.data?page=N): the full
  photo gallery per product (the Catalog only gives one photo).

Products the bulk sources miss, and new products (the Catalog has no product
type, which the keyword rules use), come from the product's own loader data
(/products/<handle>.data), one request each.

Everything is converted to the Shopify REST /products.json shape with
numeric ids, so the rest of the pipeline (normalize, classify, writer) is
unchanged and existing products keep their ids, history and overrides. Any
listing failure raises StoreFetchError before anything is yielded, so a
partial fetch can never mark products as removed.
"""
import json
import os
import re
import xml.etree.ElementTree as ET

from fetchers import REQUEST_TIMEOUT_SECONDS, USER_AGENT, StoreFetchError, _request_with_retry

# The agent profile UCP asks every caller for. Shopify's example profile until
# Libas hosts its own (see the doc).
UCP_AGENT_PROFILE = os.environ.get(
    "UCP_AGENT_PROFILE",
    "https://shopify.dev/ucp/agent-profiles/examples/2026-08-25/valid-with-capabilities.json")
UCP_CONTEXT = {"address_country": "PK", "currency": "PKR"}  # without it: "Internal error"
UCP_PAGE = 100            # 250 errors
UCP_SLICE_MAX = 800       # a query stops at ~1,000 results; split slices bigger than this
UCP_START_SLICES = [0, 150000, 250000, 350000, 500000, 800000]  # paisa (Rs 1,500 ...)
UCP_PRICE_TOP = 10 ** 9
MIN_COVERAGE = 0.98       # share of sitemap products that must be found, or the store fails


def gid_num(gid):
    return gid.rsplit("/", 1)[-1] if gid else ""


def turbo_decode(text):
    """React Router "turbo-stream" (the .data routes): a flat JSON array where
    objects map "_<key index>" to value indexes. Only the first line is needed."""
    a = json.loads(text.splitlines()[0])
    # turbo-stream constants: HOLE -1, NAN -2, -INF -3, -0 -4, NULL -5, +INF -6, UNDEFINED -7
    specials = {-1: None, -2: float("nan"), -3: float("-inf"), -4: 0, -5: None, -6: float("inf"), -7: None}

    def h(i):
        if isinstance(i, int) and i < 0:
            return specials.get(i)
        v = a[i]
        if isinstance(v, dict):
            return {a[int(k[1:])]: h(x) for k, x in v.items()}
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in ("D", "P", "Z", "R", "E", "Y", "S", "M"):
                return None  # dates, promises, maps... not used by this fetcher
            return [h(x) for x in v]
        return v
    return h(0)


def _money(amount_minor):
    return None if amount_minor is None else f"{amount_minor / 100:.2f}"


def _rest_product(pid, handle, title, body_html, vendor, product_type, tags, option_names, variants, images):
    """The /products.json shape normalize_product_fields() and the writer read.
    variants: dicts with id, title, sku, available, opts {name: value}, price,
    compare_at, image."""
    option_names = option_names or ["Title"]
    # Variant photos only mean something when they differ (a colour's own
    # photo); one shared photo on every variant is just the product photo.
    if len({v.get("image") for v in variants}) < 2:
        variants = [{**v, "image": None} for v in variants]
    rest_variants = []
    for v in variants:
        rv = {"id": int(v["id"]), "product_id": int(pid), "title": v["title"], "sku": v.get("sku"),
              "price": v["price"], "compare_at_price": v.get("compare_at"), "available": bool(v["available"]),
              "featured_image": {"src": v["image"]} if v.get("image") else None}
        for i, name in enumerate(option_names[:3]):
            rv[f"option{i + 1}"] = v["opts"].get(name)
        rest_variants.append(rv)
    values = {n: [] for n in option_names}
    for v in variants:
        for n in option_names:
            val = v["opts"].get(n)
            if val is not None and val not in values[n]:
                values[n].append(val)
    return {
        "id": int(pid), "title": title, "handle": handle, "body_html": body_html or "",
        "vendor": vendor, "product_type": product_type or "", "tags": tags or [],
        "options": [{"name": n, "position": i + 1, "values": values[n]} for i, n in enumerate(option_names)],
        "variants": rest_variants,
        "images": [{"src": u, "position": i + 1, "variant_ids": []} for i, u in enumerate(images)],
        "_source": "shopify_ucp",
    }


def fetch_ucp_store(base_url, session, pacer, store_label, previous, store_name,
                    max_retries=5, backoff_base_seconds=2):
    """Yields REST-shaped product dicts for every product the store lists.
    `previous` maps numeric product id -> last raw_source (for product type
    and vendor, which the Catalog doesn't return)."""

    def get(url, missing_ok=False):
        pacer.wait()

        def do_request():
            resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
            if missing_ok and resp.status_code == 404:
                resp.status_code = 299  # a gone product page is an answer, not a failure
            return resp
        resp = _request_with_retry(do_request, store_label, max_retries, backoff_base_seconds)
        return None if resp.status_code == 299 else resp

    # 1. Sitemap: every product handle the store publishes.
    index = get(f"{base_url}/sitemap.xml").text
    handles = set()
    for sm in re.findall(r"<loc>([^<]*/sitemap/products/[^<]*)</loc>", index):
        for loc in re.findall(r"<loc>([^<]+)</loc>", get(sm.replace("&amp;", "&")).text):
            if "/products/" in loc:
                handles.add(loc.rsplit("/products/", 1)[1].split("?")[0])
    if not handles:
        raise StoreFetchError(f"[{store_label}] product sitemap is empty")

    # 2. Catalog: products, variants, stock. Sliced by price so no query hits the cap.
    def ucp(catalog):
        body = {"jsonrpc": "2.0", "method": "tools/call", "id": 1,
                "params": {"name": "search_catalog",
                           "arguments": {"meta": {"ucp-agent": {"profile": UCP_AGENT_PROFILE}},
                                         "catalog": {**catalog, "context": UCP_CONTEXT}}}}
        for _ in range(max_retries):
            pacer.wait()
            resp = _request_with_retry(
                lambda: session.post(f"{base_url}/api/ucp/mcp", json=body,
                                     headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS * 4),
                store_label, max_retries, backoff_base_seconds)
            payload = resp.json()
            if "result" in payload:
                return json.loads(payload["result"]["content"][0]["text"])
        raise StoreFetchError(f"[{store_label}] Catalog error: {payload.get('error')}")

    def ucp_slice(lo, hi, available):
        found, cursor = {}, None
        while True:
            page = {"limit": UCP_PAGE, **({"cursor": cursor} if cursor else {})}
            d = ucp({"filters": {"price": {"min": lo, "max": hi - 1}, "available": available},
                     "pagination": page})
            for p in d.get("products") or []:
                found[gid_num(p["id"])] = p
            if len(found) > UCP_SLICE_MAX and hi - lo > 100:
                mid = (lo + hi) // 2  # too close to the cap: split and redo both halves
                return {**ucp_slice(lo, mid, available), **ucp_slice(mid, hi, available)}
            pg = d.get("pagination") or {}
            if not pg.get("has_next_page"):
                return found
            cursor = pg["cursor"]

    catalog = {}
    bounds = UCP_START_SLICES + [UCP_PRICE_TOP]
    for available in (True, False):
        for lo, hi in zip(bounds, bounds[1:]):
            catalog.update(ucp_slice(lo, hi, available))

    # 3. Photos: collection loader pages, 24 products each.
    gallery, handle_by_id = {}, {}
    page, page_count = 1, 1
    while page <= page_count:
        data = turbo_decode(get(f"{base_url}/collections/all.data?page={page}").text)
        route = data.get("routes/collection") or {}
        data = route.get("data") or {}
        page_count = (data.get("pagination") or {}).get("pageCount") or 0
        for p in data.get("products") or []:
            pid = gid_num(p["id"])
            handle_by_id[pid] = p["handle"]
            gallery[pid] = [i["url"] for i in (p.get("images") or []) if i.get("url")]
        page += 1

    # 4. Build each product from the Catalog; product loader data for the rest.
    def from_product_data(handle):
        resp = get(f"{base_url}/products/{handle}.data", missing_ok=True)
        if resp is None:
            return None
        data = turbo_decode(resp.text)
        p = ((data.get("routes/product") or {}).get("data") or {}).get("product")
        if not p:
            return None
        nodes = lambda x: (x or {}).get("nodes") or [e["node"] for e in (x or {}).get("edges") or []]
        variants = []
        for v in nodes(p.get("variants")):
            cmp = (v.get("compareAtPrice") or {}).get("amount")
            variants.append({
                "id": gid_num(v["id"]), "title": v.get("title"), "sku": v.get("sku"),
                "available": v.get("availableForSale"),
                "opts": {o["name"]: o["value"] for o in v.get("selectedOptions") or []},
                "price": f'{float(v["price"]["amount"]):.2f}', "compare_at": f"{float(cmp):.2f}" if cmp else None,
                "image": (v.get("image") or {}).get("url")})
        pid = gid_num(p["id"])
        images = gallery.get(pid) or [i["url"] for i in nodes(p.get("images")) if i.get("url")]
        return _rest_product(pid, p["handle"], p["title"], p.get("descriptionHtml"), p.get("vendor") or store_name,
                             p.get("productType"), p.get("tags"), [o["name"] for o in p.get("options") or []],
                             variants, images)

    def from_catalog(pid, c, prev):
        variants = [{
            "id": gid_num(v["id"]), "title": v.get("title"), "sku": v.get("sku"),
            "available": (v.get("availability") or {}).get("available"),
            "opts": {o["name"]: o["label"] for o in v.get("options") or []},
            "price": _money((v.get("price") or {}).get("amount")),
            "compare_at": _money((v.get("list_price") or {}).get("amount")),
            "image": ((v.get("media") or [{}])[0]).get("url")} for v in c["variants"]]
        images = gallery.get(pid) or [m["url"] for m in c.get("media") or [] if m.get("url")]
        return _rest_product(pid, c["handle"], c["title"], (c.get("description") or {}).get("html"),
                             prev.get("vendor") or store_name, prev.get("product_type"), c.get("tags"),
                             [o["name"] for o in c.get("options") or []], variants, images)

    out, fallback = {}, []
    for pid, c in catalog.items():
        prev = previous.get(pid)
        if prev is None or not c.get("variants"):
            fallback.append(c["handle"])  # new product: needs its product type
        else:
            out[pid] = from_catalog(pid, c, prev)
    built_handles = {p["handle"] for p in out.values()}
    known = set(fallback) | built_handles
    fallback += [h for h in sorted(handles | set(handle_by_id.values())) if h not in known]
    for h in fallback:
        p = from_product_data(h)
        if p is None:  # listed in the sitemap but no product page (draft or just removed)
            continue
        if not p["variants"] and str(p["id"]) in catalog:  # loader had no variants: keep the Catalog's
            p = from_catalog(str(p["id"]), catalog[str(p["id"])], {"product_type": p["product_type"],
                                                                     "vendor": p["vendor"]})
        out[str(p["id"])] = p

    covered = len(handles & {p["handle"] for p in out.values()}) / len(handles)
    print(f"  [{store_label}] sitemap {len(handles)}, catalog {len(catalog)}, gallery {len(gallery)}, "
          f"product pages {len(fallback)}, built {len(out)}, sitemap coverage {covered:.1%}", flush=True)
    if covered < MIN_COVERAGE:
        raise StoreFetchError(f"[{store_label}] only {covered:.1%} of sitemap products found; nothing written")
    yield from out.values()
