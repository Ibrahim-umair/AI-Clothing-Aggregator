"""
Fetcher for Salesforce Commerce Cloud stores (Khaadi, Sapphire): no product
feed, so the product list comes from what each store's robots.txt allows.

  Khaadi    every category page in its sitemap (?start=&sz=, 96 per page).
            The listing tiles already carry name, price, sale price and every
            size with its stock (sold-out sizes are `disabled`), so sizes,
            stock and prices always come from the tiles: ~700 requests for
            the whole store. The product page is read only for a product we
            haven't stored yet, for its full photo set (tiles show 2) and
            the "Details" spec list and breadcrumb.
  Sapphire  sitemap_0-product.xml for the product pages (its ?start=/?sz=
            listing parameters are disallowed, and a listing page shows 12),
            then each page: name, price, sizes with a "SOLD OUT" flag,
            photos, details tab, breadcrumb, keywords.

Pages are read by a few workers sharing one pacer (SCRAPE_SFCC_INTERVAL
seconds between requests to a store, default 1). Both stores'
/on/demandware.store/ endpoints are disallowed by robots.txt and never
called. Each product is yielded in the /products.json shape the rest of the
pipeline reads, with handle "<id>.html": both stores redirect
/products/<id>.html to the real page, so shopper links built as
base_url/products/handle work unchanged.
"""
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

from fetchers import REQUEST_TIMEOUT_SECONDS, USER_AGENT, StoreFetchError
from pacing import Pacer

# Khaadi's sitemap lists only category pages. Every one is read (~610), since a
# section like /western/ is a landing page whose products sit in sub-categories.
# Skipped: Home (bedding etc.), blogs, and paths robots.txt disallows.
KHAADI_SKIP = re.compile(r"^/(?:home|blogs|women|c)/|\.html$")
KHAADI_PAGE = 96
MAX_FAILURES_IN_A_ROW = 25   # a blocked store, not a few broken pages
WORKERS = 3
INTERVAL = float(os.environ.get("SCRAPE_SFCC_INTERVAL", "1"))


def _text(s):
    s = re.sub(r"<(style|script).*?</>", " ", s or "", flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _prices(block):
    """Sale price and the struck-through original, from a price block's content="" values."""
    vals = sorted({float(v) for v in re.findall(r'content="(\d+(?:\.\d+)?)"', block or "")})
    if not vals:
        return None, None
    price, top = vals[0], vals[-1]
    return f"{price:.2f}", (f"{top:.2f}" if top > price else None)


def _price_block(page):
    i = page.find('<div class="price">')
    return page[i:i + 1500] if i >= 0 else ""


def _breadcrumb(page):
    names = [_text(x) for x in re.findall(r'<li class="breadcrumb-item[^"]*"[^>]*>(.*?)</li>', page, re.S)]
    return [n for n in names if n and n.lower() != "home"]


def _product(pid, title, body, product_type, tags, colour, sizes, price, compare, images):
    """sizes: [(label, available)]; [] for one-size items (fabric, fragrance)."""
    options = (["Color"] if colour else []) + ["Size"]
    variants = []
    for n, (label, avail) in enumerate(sizes, 1):
        v = {"id": f"{pid}-{label}", "product_id": pid, "title": " / ".join(x for x in (colour, label) if x),
             "sku": f"{pid}-{label}", "price": price, "compare_at_price": compare, "available": avail,
             "featured_image": None}
        opts = ([colour] if colour else []) + [label]
        for i, val in enumerate(opts):
            v[f"option{i + 1}"] = val
        variants.append(v)
    seen, imgs = set(), []
    for u in images:
        key = u.split("?")[0].lower()
        if key not in seen:
            seen.add(key)
            imgs.append(u.split("?")[0])
    return {
        "id": pid, "title": title, "handle": f"{pid}.html", "body_html": body, "vendor": "",
        "product_type": product_type, "tags": tags,
        "options": [{"name": n, "position": i + 1,
                     "values": sorted({v[f"option{i + 1}"] for v in variants})} for i, n in enumerate(options)],
        "variants": variants,
        "images": [{"src": u, "position": i + 1, "variant_ids": []} for i, u in enumerate(imgs)],
        "_source": "sfcc",
    }


def parse_khaadi(page, pid, base_url):
    ld = {}
    for m in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(m)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            ld = d
    name = _text((re.search(r'<h2 class="product-name"[^>]*>(.*?)</h2>', page, re.S) or [None, ""])[1]) or ld.get("name", "")
    if not name:
        return None
    in_stock = "InStock" in ((ld.get("offers") or {}).get("availability") or "")
    sizes = []
    for m in re.finditer(r'<input type="radio"[^>]*data-attr-value="([^"]*)"([^>]*)>\s*<span[^>]*>([^<]*)<', page):
        if f'data-pid="{pid}"' in m.group(2):
            sizes.append((m.group(3).strip() or m.group(1), "inStock" in m.group(2)))
    sizes = list(dict.fromkeys(sizes))
    if not sizes:
        sizes = [("One Size", in_stock)]
    colours = re.findall(r'data-attr="color".*?data-attr-value="([^"]*)"', page, re.S)
    specs = [_text(li) for li in re.findall(r"<li>\s*<span>(.*?)</span>\s*</li>",
                                            page[page.find('class="spec-list'):][:6000], re.S)]
    brand_line = _text((re.search(r'<div class="product-brand">(.*?)</div>', page, re.S) or [None, ""])[1])
    body = "".join(f"<p>{html.escape(s)}</p>" for s in [brand_line] + specs if s)
    crumbs = [c for c in _breadcrumb(page) if c != name]
    price, compare = _prices(_price_block(page))
    if price is None and (ld.get("offers") or {}).get("price"):
        price = f"{float(ld['offers']['price']):.2f}"
    images = [u if u.startswith("http") else base_url + u for u in ld.get("image") or []]
    return _product(pid, name, body, " > ".join(crumbs),
                    crumbs, colours[0].title() if colours and colours[0] != "MULTI" else None,
                    sizes, price, compare, images)


def parse_sapphire(page, pid):
    name = _text((re.search(r'<h2 class="product-name[^"]*"[^>]*>(.*?)<(?:input|a|/h2)', page, re.S) or [None, ""])[1])
    if not name:
        return None
    sizes = []
    for m in re.finditer(r'<input type="radio" id="([^"]*)" name="size-options"[^>]*data-pid="([^"]*)"[^>]*>', page):
        if m.group(2) != pid:
            continue  # a "shop the look" item on the same page
        before, after = page[max(0, m.start() - 400):m.start()], page[m.end():m.end() + 300]
        sold = "not-available" in before[before.rfind("size-item"):] or 'data-stock-status="SOLD OUT"' in after[:200]
        sizes.append((m.group(1), not sold))
    sizes = list(dict.fromkeys(sizes))
    if not sizes:
        notify = re.search(r'<div class="notifyMe-wrapper([^"]*)"', page)
        sizes = [("One Size", bool(notify and "d-none" in notify.group(1)))]
    i = page.find('id="nav-details"')
    details = _text(page[i + len('id="nav-details"'):i + 6000]) if i >= 0 else ""
    details = re.split(r"\s(?:Get The Look|Size Guide|Note: Actual product)", re.sub(r"^[^>]*>\s*", "", details))[0]
    keywords = (re.search(r'<meta name="keywords" content="([^"]*)"', page) or [None, ""])[1]
    colour = (re.search(r"Colou?r:\s*([A-Za-z][A-Za-z \-]{1,30}?)\s+(?:Fabric|$)", details) or [None, None])[1]
    crumbs = _breadcrumb(page)
    if crumbs and crumbs[-1].lower() == name.lower():
        crumbs = crumbs[:-1]
    price, compare = _prices(_price_block(page))
    images = re.findall(r'"(https?://[^"]*/dw/image/[^"]*%s[^"]*\.(?:jpe?g|png|webp))' % re.escape(pid.split("_")[0]),
                        page, re.I)
    tags = crumbs + [k.strip() for k in html.unescape(keywords).split(",") if k.strip()][:40]
    # The meta description is left out: it says "1 piece" even for trousers and
    # dupattas, which the piece-count rules would read as a set size.
    body = f"<p>{html.escape(details)}</p>" if details else ""
    return _product(pid, name, body, " > ".join(crumbs), tags, colour.strip().title() if colour else None,
                    sizes, price, compare, images)


def parse_khaadi_tiles(page, base_url):
    """pid -> what a listing tile shows: name, prices, sizes with stock, 2 photos."""
    out = {}
    for t in page.split('<div class="product" data-pid="')[1:]:
        pid = t[:t.find('"')]
        gtm = re.search(r'data-gtmdata="([^"]*)"', t)
        try:
            gtm = json.loads(html.unescape(gtm.group(1))) if gtm else {}
        except ValueError:
            gtm = {}
        name = _text((re.search(r'<h2 class="pdp-link-heading">(.*?)</h2>', t, re.S) or [None, ""])[1]) or gtm.get("name", "")
        i = t.find('<div class="price">')
        price, compare = _prices(t[i:i + 1500] if i >= 0 else "")
        sizes = [(m.group(2), not re.search(r"\bdisabled\b", m.group(1)))
                 for m in re.finditer(r'<input type="radio"([^>]*?)>\s*<span[^>]*>\s*([^<]*?)\s*<', t)
                 if "data-attr-value" in m.group(1)]
        if name and pid not in out:
            out[pid] = {"name": name, "price": price, "compare": compare, "sizes": list(dict.fromkeys(sizes)),
                        "collection": gtm.get("category", ""),
                        "alt": html.unescape((re.search(r'alt="([^"]*)"', t) or [None, ""])[1]),
                        "images": [base_url + u for u in re.findall(r'data-hi-res-\d+="([^"]+)"', t)]}
    return out


def _khaadi_product(pid, tile, sections, known, page, base_url):
    """Tile sizes/prices + photos/details from the product page (new) or the stored copy (known)."""
    section_tags = [s.strip("/").replace("/", " > ").replace("-", " ") for s in sections]
    if page is not None:
        d = parse_khaadi(page, pid, base_url)
        if d is None:
            return None
        images = [i["src"] for i in d["images"]]
        body, product_type, tags = d["body_html"], d["product_type"], d["tags"]
    elif known:
        images = [i["src"] for i in known.get("images") or []]
        body, product_type = known.get("body_html") or "", known.get("product_type") or ""
        tags = [t for t in known.get("tags") or [] if t not in section_tags]
    else:  # product page gone but still listed: keep what the tile shows
        images, body, product_type, tags = tile["images"], f"<p>{html.escape(tile['alt'])}</p>", "", []
    sizes = tile["sizes"] or [("One Size", True)]  # listed with no size picker: fabric, fragrance
    return _product(pid, tile["name"], body, product_type, tags + [tile["collection"]] + section_tags, None,
                    sizes, tile["price"], tile["compare"], images or tile["images"])


def fetch_sfcc_store(slug, base_url, session, pacer, store_label, max_retries=5, known=None):
    """known: native id -> stored raw_source, so Khaadi skips product pages it has read before."""
    pacer = Pacer(INTERVAL)  # shared by the workers below
    known = known or {}

    def get(url):
        """Response text, None for a gone page (404/410); raises after retries."""
        last = None
        for attempt in range(max_retries):
            pacer.wait()
            try:
                r = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
            except Exception as e:  # connection drop or timeout: back off and retry
                last = e
                continue
            if r.status_code in (404, 410):
                return None
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 429) or r.status_code >= 500:
                for _ in range(5):
                    pacer.wait()  # slow down before the next try
                continue
            return None
        raise StoreFetchError(f"[{store_label}] {url} failed after {max_retries} attempts: {last}")

    if slug == "khaadi":
        index = get(f"{base_url}/sitemap_index.xml") or ""
        sections = []
        for sm in re.findall(r"<loc>([^<]+)</loc>", index):
            for loc in re.findall(r"<loc>([^<]+)</loc>", get(sm) or ""):
                path = loc.replace(base_url, "")
                if path.endswith("/") and path != "/" and not KHAADI_SKIP.search(path):
                    sections.append(path)
        sections = list(dict.fromkeys(sections))
        tiles, found_in = {}, {}

        def read_category(section):
            got, start = {}, 0
            while start < 20000:
                page_tiles = parse_khaadi_tiles(get(f"{base_url}{section}?start={start}&sz={KHAADI_PAGE}") or "", base_url)
                new = [p for p in page_tiles if p not in got]
                got.update(page_tiles)
                # A full page often holds 95 (one slot is a banner), so a page ends the
                # category only when it is clearly short or adds nothing new to it (past
                # the end some categories repeat their products in another order).
                if len(page_tiles) < KHAADI_PAGE - 10 or not new:
                    break
                start += KHAADI_PAGE
            return section, got

        with ThreadPoolExecutor(WORKERS) as ex:
            for n, (section, got) in enumerate(ex.map(read_category, sections), 1):
                for pid, t in got.items():
                    tiles.setdefault(pid, t)
                    found_in.setdefault(pid, []).append(section)
                if n % 50 == 0:
                    print(f"  [{store_label}] {n}/{len(sections)} categories read, {len(tiles)} products", flush=True)
        if not tiles:
            raise StoreFetchError(f"[{store_label}] no products found in the category pages")
        stored = {pid for pid in tiles if len((known.get(pid) or {}).get("images") or []) > 2}
        print(f"  [{store_label}] {len(tiles)} products listed, {len(tiles) - len(stored)} product pages to read", flush=True)

        def one(pid):
            page = None if pid in stored else get(f"{base_url}/products/{pid}.html")
            return _khaadi_product(pid, tiles[pid], found_in[pid], known.get(pid), page, base_url)
        jobs = list(tiles)
    else:
        sitemap = get(f"{base_url}/sitemap_0-product.xml") or ""
        urls = {}
        for loc in re.findall(r"<loc>([^<]+\.html)</loc>", sitemap):
            urls.setdefault(loc.rsplit("/", 1)[1][:-5], loc)
        if not urls:
            raise StoreFetchError(f"[{store_label}] no product list found")
        print(f"  [{store_label}] {len(urls)} product pages to read", flush=True)

        def one(pid):
            page = get(urls[pid])
            return None if page is None else parse_sapphire(page, pid)
        jobs = list(urls)

    failures = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futures = [ex.submit(one, pid) for pid in jobs]
        for n, fut in enumerate(futures, 1):
            try:
                p = fut.result()
                failures = 0
            except StoreFetchError:
                failures += 1
                if failures >= MAX_FAILURES_IN_A_ROW:
                    for other in futures:
                        other.cancel()
                    raise
                continue
            if n % 250 == 0:
                print(f"  [{store_label}] {n}/{len(jobs)} products done", flush=True)
            if p:
                yield p
