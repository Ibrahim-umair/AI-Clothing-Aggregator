"""
Shared REST-vs-GraphQL field mapping, extracted from load_data.py so both the
JSONL-replay loader and the live scraper pipeline (db/scraper/) parse a raw
product/variant record identically instead of maintaining two copies that
can silently drift apart.

Two shapes come in: a Shopify REST /products.json record (14 of 15 stores)
and a Shopify Storefront GraphQL record (Cougar only, is_graphql=True). Both
normalize down to the same plain-dict shape the rest of the pipeline
(classify(), the DB writers) already expects.
"""
import re


def normalize_product_fields(p, is_graphql):
    """Extracts the handful of fields classify() and the DB writers need
    from a raw product record, regardless of which of the two source shapes
    it came from. Returns a dict with: native_id, product_type, tags (list),
    vendor, description (HTML, not yet stripped), images (list of urls),
    raw_variants (list of variant dicts in that platform's native shape)."""
    if is_graphql:
        tags_raw = p.get("tags") or []
        return {
            "native_id": p.get("id") or "",
            "product_type": p.get("productType") or "",
            "tags": tags_raw if isinstance(tags_raw, list) else [],
            "vendor": p.get("vendor") or "",
            "description_html": p.get("descriptionHtml"),
            "images": [
                e["node"].get("url")
                for e in (p.get("images") or {}).get("edges", [])
                if e["node"].get("url")
            ],
            "raw_variants": [e["node"] for e in (p.get("variants") or {}).get("edges", [])],
        }
    tags_raw = p.get("tags", "")
    tags = tags_raw if isinstance(tags_raw, list) else [t.strip() for t in tags_raw.split(",") if t.strip()]
    return {
        "native_id": str(p.get("id")),
        "product_type": p.get("product_type") or "",
        "tags": tags,
        "vendor": p.get("vendor") or "",
        "description_html": p.get("body_html"),
        "images": [i.get("src") for i in (p.get("images") or []) if i.get("src")],
        "raw_variants": p.get("variants") or [],
    }


def normalize_variant_fields(v, option_defs, is_graphql):
    """Extracts native_vid, color_name, size_val, price, compare_at,
    available, sku from one raw variant record, regardless of source shape.
    `option_defs` is the parent product's REST `options` array (used to map
    positional option1/2/3 -> color/size by name); ignored for GraphQL,
    which carries `selectedOptions` with names already attached."""
    if is_graphql:
        sel = {so["name"].lower(): so["value"] for so in v.get("selectedOptions", [])}
        return {
            "native_vid": v.get("id") or "",
            "color_name": sel.get("color"),
            "size_val": sel.get("size"),
            "price": (v.get("price") or {}).get("amount"),
            "compare_at": None,
            "available": bool(v.get("availableForSale")),
            "sku": None,
            # Cougar's Storefront GraphQL variant node carries no image
            # reference at all (verified against real product data) — the
            # reverse images[].variant_ids link this REST branch uses has no
            # GraphQL equivalent here either. Callers fall back to the
            # product's default image for this store; not a bug, just what
            # Cougar's own feed provides.
            "image_url": None,
        }
    color_name = size_val = None
    for i, opt in enumerate(option_defs):
        oname = (opt.get("name") or "").lower()
        oval = v.get(f"option{i+1}")
        if "color" in oname:
            color_name = oval
        elif "size" in oname:
            size_val = oval
    price = v.get("price")
    compare_at = v.get("compare_at_price")
    if compare_at in ("0.00", 0, "0", None) or compare_at == price:
        compare_at = None
    # The variant's OWN featured_image is real when present, but is null on
    # many real variants even for stores that otherwise link color photos —
    # the caller (load_data.py) additionally checks the product's images[]
    # array's own variant_ids for the same link and prefers that, since real
    # coverage testing found it's the more complete of the two sources.
    # Coverage varies enormously by store (Outfitters ~95%, Zellbury ~84%,
    # Cambridge/Furor ~15%, Edenrobe/Charcoal/Meme near 0%) — genuinely a
    # per-store data gap, not something to paper over.
    featured_image = v.get("featured_image") or {}
    return {
        "native_vid": str(v.get("id")),
        "color_name": color_name,
        "size_val": size_val,
        "price": price,
        "compare_at": compare_at,
        "available": bool(v.get("available")),
        "sku": v.get("sku"),
        "image_url": featured_image.get("src"),
    }


def classify_size_system(size_val):
    """Buckets a raw size label string into the DB's size_system_enum."""
    if not size_val:
        return "none"
    if re.match(r"^\d{1,2}-\d{1,2}Y$", size_val, re.I) or re.match(r"^\d+Y$", size_val, re.I):
        return "kids_age_years"
    if re.match(r"^\d{2,3}\s*ml$", size_val, re.I):
        return "volume_ml"
    if re.match(r"^\d{2}$", size_val):
        return "waist_inches"
    if size_val.strip() in ("-", "One Size", "OS"):
        return "one_size"
    return "alpha"
