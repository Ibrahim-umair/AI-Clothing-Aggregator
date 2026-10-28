"""
Builds the data for review-exports/category-decisions/: Claude's manual
review of every in-stock product the enrichment model flagged as being in
the wrong category. Input is local-notes/catreview/decisions.txt, one line
per product:  id|case|target category path|note
  A = clear fix to an existing category (or "already right": a false flag)
  B = unsure, needs a human call
  C = no fitting category exists, a new one is proposed

    python export_category_decisions.py
"""
import json
import re
import time
from pathlib import Path

import psycopg2

from embed_products import build_category_paths
from load_data import DSN

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "local-notes" / "catreview" / "decisions.txt"
OUT = ROOT / "review-exports" / "category-decisions"

# Why the keyword rules got it wrong, read off the review note.
CAUSES = [
    ("false_flag", "AI flag was wrong: category already right", r"false flag|correct \(|is right \(|acceptable"),
    ("missing", "No fitting category exists yet", r"no \w+ category|no category|exists only for|not apparel|no pin|no Eastern-bottoms|no beauty|no makeup"),
    ("gender", "Right type, wrong gender or age", r"filed under (Men|Women|Boys|Girls)|Teens 2PC|gender|adult"),
    ("typo", "Typo or code-only title", r"typo|code '|only with a code"),
    ("set", "Two-piece set filed under one of its pieces", r"set filed|combo|two-piece|co-ord set|\+ (trouser|shorts|leggings|sweatpants|joggers)"),
    ("vocab", "The brand's own word for the garment isn't in the rules", r"Upper|Suiting|dungaree|W/C|5 Pocket|TIES|CUFF LINKS|COATS|Tunics|Long Maxi|romper|SLACKS|Bottom"),
    ("word", "A word in the title triggered the wrong rule", r"word|titled|-> (Jeans|Cargo|Belt|Cap|Scarf|Shorts|Socks|Shawl|Polo|Jacket|Waistcoat|Tie|Bag)\b|'[^']*' -> "),
    ("store_type", "Brand's own product type ignored or misread", r"store type|product type|filed"),
    ("fallback", "No rule matched, so it fell into 'Shirt'", r"fallback"),
]

# Claude's consolidated recommendation per proposed category (the "bigger
# picture"): what to create, merge or hide. Keys are the proposed leaf name.
PROPOSALS = {
    "Pins & Clips": ("create", "Men > Accessories > Pins & Clips",
                     "Tie pins, lapel pins and collar bars. Formal accessory sold in large numbers by Uniworth, Royal Tag and Edenrobe."),
    "Gift Set": ("create", "Men > Accessories > Gift Set",
                 "Boxed tie + pocket square + pin sets. Could also go into Tie, but shoppers look for gift boxes as a thing of their own."),
    "Sandals": ("extend", "Men / Boys > Western > Footwear > Sandals",
                "Sandals already exists for Women. Extending it to Men and Boys covers peshawari chappals, slides and flip-flops."),
    "Nightwear & Loungewear": ("create", "<every gender> > Western > Sleepwear > Nightwear & Loungewear",
                               "Pajama sets and lounge bottoms. One leaf per gender, under a new Sleepwear group."),
    "Gloves": ("create", "<every gender> > Accessories > Gloves", "Winter gloves and mittens, mostly Breakout."),
    "Suspenders": ("merge", "Men > Accessories > Belt  (rename to 'Belts & Suspenders')",
                   "Only 17 products. Merging into Belt avoids a near-empty category."),
    "Blazer": ("create", "Men > Western > Formalwear > Blazer",
               "Blazers sold on their own. More blazers probably sit unflagged under Jacket today."),
    "Shalwar & Pajama": ("create", "Men > Eastern > Stitched > Shalwar & Pajama",
                         "Eastern bottoms sold separately to wear with a kurta."),
    "Hair Accessories": ("create", "Girls / Women > Accessories > Hair Accessories", "Clips, ties and headbands now filed as Jewelry."),
    "Abaya": ("create", "Women > Eastern > Stitched > Abaya", "Zellbury abayas."),
    "Lehenga": ("create", "Girls / Women > Eastern > Stitched > Lehenga", "One product today, but a core Eastern category."),
    "Swimsuit": ("create", "Girls > Western > Swimwear", "Two products."),
    "Tracksuit": ("extend", "Boys > Western > Suits & Sets > Tracksuit", "Tracksuit exists for every other gender."),
    "Towels": ("hide", "Hide from Libas", "Zellbury towels: home goods, not clothing."),
    "Candles": ("hide", "Hide from Libas", "Lama scented candles: home goods."),
    "Shoe Care": ("hide", "Hide from Libas", "Insoles, shoehorns and brushes."),
    "Skincare": ("hide", "Hide from Libas", "Lip balms and balms."),
    "Makeup": ("hide", "Hide from Libas", "Nail polish."),
    "Other": ("hide", "Hide from Libas", "Waistcoat buttons."),
}


def cause_of(note):
    for key, _, rx in CAUSES:
        if re.search(rx, note, re.I):
            return key
    return "other"


def main():
    rows = []
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        pid, case, target, note = line.split("|", 3)
        rows.append((int(pid), case, target.strip(), note.strip()))

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    paths = build_category_paths(cur)
    cur.execute("""
        SELECT p.id, b.name, p.title, p.category_id, p.ai_looks_like, p.ai_description,
               left(regexp_replace(coalesce(p.description, ''), '<[^>]+>', ' ', 'g'), 260),
               b.base_url || '/products/' || p.handle,
               (SELECT url FROM product_images i WHERE i.product_id = p.id ORDER BY position LIMIT 1),
               (SELECT min(current_price) FROM variants v WHERE v.product_id = p.id)
        FROM products p JOIN brands b ON b.id = p.brand_id WHERE p.id = ANY(%s)
    """, ([r[0] for r in rows],))
    info = {r[0]: r for r in cur.fetchall()}
    cur.execute("""SELECT b.name, count(*) FROM products p JOIN brands b ON b.id = p.brand_id
                   WHERE p.is_active AND p.embedding_v2 IS NOT NULL GROUP BY 1""")
    brand_totals = dict(cur.fetchall())

    products = []
    for pid, case, target, note in rows:
        _, brand, title, cat_id, looks, ai, store, url, img, price = info[pid]
        current = paths.get(cat_id, "")
        leaf = target.split(" > ")[-1]
        group = "Nightwear & Loungewear" if case == "C" and "Sleepwear" in target else leaf
        products.append({
            "id": pid, "brand": brand, "title": title, "current": current, "target": target,
            "case": "keep" if case == "A" and target == current else case,
            "cause": cause_of(note), "note": note, "ai": looks or "", "aiDesc": ai or "",
            "store": " ".join((store or "").split()), "url": url, "img": img,
            "price": float(price) if price is not None else None,
            "proposal": group if case == "C" else None,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    meta = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "in_stock": sum(brand_totals.values()),
        "brand_totals": brand_totals,
        "causes": {k: label for k, label, _ in CAUSES} | {"other": "Other"},
        "proposals": {k: {"action": a, "where": w, "why": y} for k, (a, w, y) in PROPOSALS.items()},
    }
    (OUT / "data.js").write_text(
        "window.CATDEC = " + json.dumps({"meta": meta, "products": products}, ensure_ascii=False) + ";\n",
        encoding="utf-8")
    from collections import Counter
    print(f"wrote {len(products)} decisions to {OUT / 'data.js'}")
    print(Counter(p["case"] for p in products))
    print(Counter(p["cause"] for p in products))
    missing = {p["proposal"] for p in products if p["proposal"]} - set(PROPOSALS)
    print("proposals without a recommendation:", missing or "none")


if __name__ == "__main__":
    main()
