"""
Builds the local category-review page (review-exports/category-review/):
every in-stock product the enrichment model flagged as being in the wrong
category, with its photo, the category our keyword rules gave it, and
what the model says it is. Re-run any time to refresh data.js.

    python export_category_review.py
"""
import json
import re
import time
from pathlib import Path

import psycopg2

from embed_products import build_category_paths
from load_data import DSN

OUT = Path(__file__).resolve().parent.parent / "review-exports" / "category-review"

_PREFIX = re.compile(r"^(men'?s|women'?s|boys'?|girls'?|kids'?|unisex|baby)\s+", re.I)


def pattern_name(looks_like: str) -> str:
    """'Men's knit gloves' and 'knit gloves' are the same pattern."""
    s = (looks_like or "unknown").strip().lower().replace("’", "'")
    while _PREFIX.match(s):
        s = _PREFIX.sub("", s, count=1)
    return s or "unknown"


def main():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    paths = build_category_paths(cur)
    cur.execute("""
        SELECT b.name, count(*) FILTER (WHERE p.ai_category_ok = false), count(*)
        FROM products p JOIN brands b ON b.id = p.brand_id
        WHERE p.is_active AND p.embedding_v2 IS NOT NULL GROUP BY 1
    """)
    brands = {name: {"flagged": f, "total": t} for name, f, t in cur.fetchall()}
    cur.execute("""
        SELECT p.id, b.name, p.title, p.category_id, p.ai_looks_like, p.ai_description,
               b.base_url || '/products/' || p.handle,
               (SELECT url FROM product_images i WHERE i.product_id = p.id ORDER BY position LIMIT 1),
               (SELECT min(current_price) FROM variants v WHERE v.product_id = p.id)
        FROM products p JOIN brands b ON b.id = p.brand_id
        WHERE p.is_active AND p.embedding_v2 IS NOT NULL AND p.ai_category_ok = false
        ORDER BY b.name, p.id
    """)
    products = []
    for pid, brand, title, cat_id, looks, ai_desc, url, img, price in cur.fetchall():
        path = paths.get(cat_id, "")
        products.append({
            "id": pid, "brand": brand, "title": title,
            "category": path.split(" > ")[-1] if path else "",
            "path": path, "ai": looks or "", "pattern": pattern_name(looks),
            "desc": ai_desc or "", "url": url, "img": img,
            "price": float(price) if price is not None else None,
        })
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"generated": time.strftime("%Y-%m-%d %H:%M"), "brands": brands,
            "in_stock": sum(b["total"] for b in brands.values())}
    (OUT / "data.js").write_text(
        "window.CATREVIEW = " + json.dumps({"meta": meta, "products": products}, ensure_ascii=False) + ";\n",
        encoding="utf-8")
    print(f"wrote {len(products)} flagged products to {OUT / 'data.js'}")


if __name__ == "__main__":
    main()
