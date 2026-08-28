import json
import os
import re
import sqlite3

MAX_STORED_IMAGES = 12

DATA_DIR = r"C:\Work\scraping-init\scraped_data"
DB_PATH = os.path.join(DATA_DIR, "products.db")

STORE_BASE_URLS = {
    "outfitters": "https://outfitters.com.pk",
    "furor": "https://furorjeans.com",
    "edenrobe": "https://edenrobe.com",
    "one_be-one": "https://beoneshopone.com",
    "equator": "https://equatorstores.com",
    "meme": "https://shopatmeme.com",
    "breakout": "https://breakout.com.pk",
    "monark": "https://monark.com.pk",
    "engine_clothing": "https://engine.com.pk",
    "charcoal": "https://charcoal.com.pk",
    "royal_tag": "https://royaltag.com.pk",
    "diners": "https://diners.com.pk",
    "cambridge": "https://thecambridgeshop.com",
    "uniworth": "https://uniworthshop.com",
    "cougar": "https://cougar.com.pk",
}

DISPLAY_NAMES = {
    "outfitters": "Outfitters",
    "furor": "Furor",
    "edenrobe": "Edenrobe",
    "one_be-one": "ONE (Be-One)",
    "equator": "Equator",
    "meme": "Meme",
    "breakout": "Breakout",
    "monark": "Monark",
    "engine_clothing": "Engine Clothing",
    "charcoal": "Charcoal",
    "royal_tag": "Royal Tag",
    "diners": "Diners",
    "cambridge": "Cambridge",
    "uniworth": "Uniworth",
    "cougar": "Cougar",
}


def strip_html(html):
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def normalize_rest(p):
    variants = p.get("variants", []) or []
    prices = [float(v["price"]) for v in variants if v.get("price") is not None]
    price = min(prices) if prices else None
    compare_prices = [float(v["compare_at_price"]) for v in variants if v.get("compare_at_price")]
    compare_at = min(compare_prices) if compare_prices else None
    available = any(v.get("available") for v in variants)
    images = p.get("images", []) or []
    image_urls = [img.get("src") for img in images if img.get("src")]
    image_url = image_urls[0] if image_urls else None
    tags_raw = p.get("tags", "")
    tags = tags_raw if isinstance(tags_raw, str) else ", ".join(tags_raw or [])
    return {
        "product_id": str(p.get("id")),
        "title": p.get("title") or "",
        "vendor": p.get("vendor") or "",
        "product_type": p.get("product_type") or "",
        "tags": tags,
        "price": price,
        "compare_at_price": compare_at,
        "currency": "PKR",
        "available": 1 if available else 0,
        "image_url": image_url,
        "images_json": json.dumps(image_urls[:MAX_STORED_IMAGES]),
        "image_count": len(images),
        "description": strip_html(p.get("body_html")),
        "handle": p.get("handle") or "",
        "variant_count": len(variants),
    }


def normalize_graphql(p):
    variants = [e["node"] for e in (p.get("variants", {}) or {}).get("edges", []) or []]
    prices = [float(v["price"]["amount"]) for v in variants if v.get("price")]
    price = min(prices) if prices else None
    available = any(v.get("availableForSale") for v in variants)
    images = [e["node"] for e in (p.get("images", {}) or {}).get("edges", []) or []]
    image_urls = [img.get("url") for img in images if img.get("url")]
    image_url = image_urls[0] if image_urls else None
    price_range = (p.get("priceRange") or {}).get("minVariantPrice", {}) or {}
    if price is None and price_range.get("amount"):
        price = float(price_range["amount"])
    currency = price_range.get("currencyCode", "PKR")
    tags = ", ".join(p.get("tags", []) or [])
    return {
        "product_id": p.get("id") or "",
        "title": p.get("title") or "",
        "vendor": p.get("vendor") or "",
        "product_type": p.get("productType") or "",
        "tags": tags,
        "price": price,
        "compare_at_price": None,
        "currency": currency,
        "available": 1 if available else 0,
        "image_url": image_url,
        "images_json": json.dumps(image_urls[:MAX_STORED_IMAGES]),
        "image_count": len(images),
        "description": strip_html(p.get("descriptionHtml")),
        "handle": p.get("handle") or "",
        "variant_count": len(variants),
    }


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT,
            store TEXT,
            store_display TEXT,
            title TEXT,
            vendor TEXT,
            product_type TEXT,
            tags TEXT,
            price REAL,
            compare_at_price REAL,
            currency TEXT,
            available INTEGER,
            image_url TEXT,
            images_json TEXT,
            image_count INTEGER,
            description TEXT,
            handle TEXT,
            product_url TEXT,
            variant_count INTEGER
        )
    """)
    total = 0
    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".jsonl"):
            continue
        slug = fname[:-6]
        base_url = STORE_BASE_URLS.get(slug, "")
        display = DISPLAY_NAMES.get(slug, slug)
        path = os.path.join(DATA_DIR, fname)
        count = 0
        rows = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                p = json.loads(line)
                row = normalize_graphql(p) if slug == "cougar" else normalize_rest(p)
                row["store"] = slug
                row["store_display"] = display
                row["product_url"] = f"{base_url}/products/{row['handle']}" if row["handle"] else ""
                rows.append(row)
                count += 1
        cur.executemany("""
            INSERT INTO products (product_id, store, store_display, title, vendor, product_type,
                tags, price, compare_at_price, currency, available, image_url, images_json, image_count,
                description, handle, product_url, variant_count)
            VALUES (:product_id, :store, :store_display, :title, :vendor, :product_type,
                :tags, :price, :compare_at_price, :currency, :available, :image_url, :images_json, :image_count,
                :description, :handle, :product_url, :variant_count)
        """, rows)
        conn.commit()
        total += count
        print(f"{display}: {count} products indexed")

    cur.execute("CREATE INDEX idx_store ON products(store)")
    cur.execute("CREATE INDEX idx_title ON products(title)")
    cur.execute("CREATE INDEX idx_type ON products(product_type)")
    conn.commit()
    conn.close()
    print(f"\nTOTAL: {total} products indexed into {DB_PATH}")


if __name__ == "__main__":
    main()
