"""
Builds the data for review-exports/new-categories/: for every category we
agreed to create (or extend, merge, hide), the in-stock products that belong
in it but are filed somewhere else today.

Two sources, both free (no LLM call):
  review  Claude's manual review of the 1,950 flagged products
          (local-notes/catreview/decisions.txt, case C)
  scan    the whole in-stock catalog, matched on what the enrichment model
          said the product looks like (ai_looks_like) and the title.
          Not reviewed one by one, so expect some misses.

    python export_new_categories.py
"""
import json
import re
import time
from collections import Counter
from pathlib import Path

import psycopg2

from embed_products import build_category_paths
from load_data import DSN

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "local-notes" / "catreview" / "decisions.txt"
APPROVALS = ROOT / "local-notes" / "catreview" / "approvals.json"
OUT = ROOT / "review-exports" / "new-categories"

NOT_A_SET = r"^(?!.*\b(kameez|kurta|suit|set|shirt|with|and|piece|outfit)\b)"

# key, name, action, where, why, review targets (leaf names in decisions.txt),
# looks_like regex, title regex. Checked in this order; first match wins.
CATS = [
    ("towels", "Towels", "hide", "Hide from Libas", "Home goods, not clothing.",
     {"Towels"}, r"\btowels?\b", None),
    ("candles", "Candles", "hide", "Hide from Libas", "Home goods.",
     {"Candles"}, r"\bcandles?\b", r"\bcandles?\b"),
    ("shoecare", "Shoe Care", "hide", "Hide from Libas", "Insoles, shoehorns, brushes.",
     {"Shoe Care"}, r"\b(insoles?|inserts|shoe ?horn|shoehorn|shoe (brush|polish|care|tree)s?)\b", r"\b(insoles?|shoe ?horn|shoe care)\b"),
    ("skincare", "Skincare & Makeup", "hide", "Hide from Libas", "Lip balms, nail polish and similar.",
     {"Skincare", "Makeup"}, r"\b(balm|lotion|serum|moisturi\w+|nail polish|lipstick|mascara|eyeliner)\b", r"\b(lip balm|nail polish|lipstick)\b"),
    ("buttons", "Buttons", "hide", "Hide from Libas", "Loose waistcoat buttons.",
     {"Other"}, r"^[\w\- ]*\bbuttons$", None),
    ("gloves", "Gloves", "create", "<every gender> > Accessories > Gloves", "Winter gloves and mittens.",
     {"Gloves"}, r"\b(gloves|mittens)\b", r"\b(gloves|mittens)\b"),
    ("hair", "Hair Accessories", "create", "Girls / Women > Accessories > Hair Accessories", "Clips, scrunchies, headbands.",
     {"Hair Accessories"}, r"\b(hair|scrunchies?|headbands?|hairband)\b", r"\b(hair|scrunchie|headband)\b"),
    ("pins", "Pins & Clips", "create", "Men / Women > Accessories > Pins & Clips", "Lapel pins, tie pins, tie bars, collar bars, brooches.",
     {"Pins & Clips"}, r"\b(pins?|tie clips?|tie bars?|collar bars?|brooch(es)?)\b", r"\b(lapel pin|tie pin|tie clip|tie bar|collar bar|brooch)\b"),
    ("gift", "Gift Set", "create", "Men > Accessories > Gift Set", "Boxed tie / pocket square / cufflink sets.",
     {"Gift Set"}, r"\bgift (set|box)\b|\bboxed\b|\b(tie|pocket square|cufflinks?)\b.*\bset$", r"\bgift\b"),
    ("suspenders", "Suspenders", "create", "Men > Accessories > Suspenders", "Suspenders and braces, a formal accessory of their own.",
     {"Suspenders"}, r"\b(suspenders|braces)\b", r"\bsuspenders?\b"),
    ("swim", "Swimwear", "create", "<every gender> > Western > Swimwear", "Swimsuits and swim shorts.",
     {"Swimsuit"}, r"\b(swim\w*|bikini|burkini)\b", r"\bswim\w*\b"),
    ("abaya", "Abaya", "create", "Women > Eastern > Stitched > Abaya", "Abayas.",
     {"Abaya"}, r"\babayas?\b", r"\babayas?\b"),
    ("lehenga", "Lehenga", "create", "Girls / Women > Eastern > Stitched > Lehenga", "Core Eastern category.",
     {"Lehenga"}, r"\b(lehengas?|lehnga)\b", r"\b(lehenga|lehnga)\b"),
    ("dupatta", "Dupatta", "create", "Women / Girls > Eastern > Dupatta", "Dupattas sold on their own (not part of a suit).",
     set(), NOT_A_SET + r".*\bdupattas?\b", NOT_A_SET + r".*\bdupattas?\b"),
    ("eastbottoms", "Shalwar & Pajama", "create", "<every gender> > Eastern > Stitched > Shalwar & Pajama", "Eastern bottoms sold separately, worn with a kurta.",
     {"Shalwar & Pajama"}, NOT_A_SET + r".*\b(shalwar|churidar|patiala|eastern (trousers?|pajama|pants))\b", NOT_A_SET + r".*\b(shalwar|churidar)\b"),
    ("night", "Nightwear & Loungewear", "create", "<every gender> > Western > Sleepwear > Nightwear & Loungewear", "Pajama sets, night suits, lounge sets.",
     {"Pajama", "Pajama Set"}, r"^(?!.*\b(kurta|shalwar|kameez)\b).*\b(pajamas?|pyjamas?|sleep\w*|night ?(suit|wear|dress|gown)s?|lounge\w*|pj)\b", r"\b(night ?suit|sleepwear|nightwear|loungewear|pajama set|pyjama)\b"),
    ("sandals", "Sandals & Slides", "extend", "<every gender> > Western > Footwear > Sandals (exists for Women only)", "Sandals, slides, flip-flops, chappals.",
     {"Sandals"}, r"\b(sandals?|slides|flip-?flops|chappals?|peshawari|kolhapuri)\b", r"\b(sandals?|slides|flip ?flops?|chappals?|peshawari)\b"),
    ("blazer", "Blazer", "create", "Men / Boys > Western > Formalwear > Blazer", "Blazers sold on their own, not as part of a suit.",
     {"Blazer"}, r"^(?!.*\b(suit|set)\b).*\bblazers?\b", r"^(?!.*\b(suit|set|2 ?pc|3 ?pc)\b).*\bblazers?\b"),
]


# Garments that only mention the word (a "pin buckle belt", "brooch heels",
# "bikini briefs") are not the accessory itself.
EXCLUDE = {
    "pins": re.compile(r"\b(belt|buckle|sandals?|heels|shoes?|slides|slip on|t-shirt|shirt|top|dress)\b", re.I),
    "swim": re.compile(r"\bbriefs?\b", re.I),
}


def main():
    review = {}
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        pid, case, target, note = line.split("|", 3)
        if case == "C":
            review[int(pid)] = (target.strip(), note.strip())
    approved = {k for k, v in json.loads(APPROVALS.read_text())["proposals"].items() if v.get("v") == "ok"}

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    paths = build_category_paths(cur)
    cur.execute("""
        SELECT p.id, b.name, p.title, p.category_id, coalesce(p.ai_looks_like, ''),
               coalesce(p.ai_description, ''), coalesce(p.raw_source->>'product_type', ''),
               b.base_url || '/products/' || p.handle,
               (SELECT url FROM product_images i WHERE i.product_id = p.id ORDER BY position LIMIT 1),
               (SELECT min(current_price) FROM variants v WHERE v.product_id = p.id)
        FROM products p JOIN brands b ON b.id = p.brand_id
        WHERE p.is_active AND p.embedding_v2 IS NOT NULL
    """)
    rows = cur.fetchall()

    compiled = [(c, re.compile(c[6], re.I), re.compile(c[7], re.I) if c[7] else None) for c in CATS]
    by_review_leaf = {leaf: c[0] for c in CATS for leaf in c[5]}
    products = []
    for pid, brand, title, cat_id, looks, ai, ptype, url, img, price in rows:
        current = paths.get(cat_id, "")
        leaf = current.split(" > ")[-1]
        key, source, note = None, None, ""
        if pid in review:
            target, note = review[pid]
            key, source = by_review_leaf.get(target.split(" > ")[-1]), "review"
        if key is None:
            for c, lrx, trx in compiled:
                if (lrx.search(looks) or (trx and trx.search(title))) and not (
                        c[0] in EXCLUDE and EXCLUDE[c[0]].search(looks)):
                    key, source = c[0], "scan"
                    break
        # A plain pajama filed under Eastern is the shalwar-style bottom worn
        # with a kurta, not nightwear.
        if key == "night" and source == "scan" and " > Eastern > " in current:
            key = "eastbottoms"
        if key is None:
            continue
        cat = next(c for c in CATS if c[0] == key)
        # Already in the right place, e.g. Women's sandals in Sandals.
        if leaf == cat[1] or (key == "sandals" and leaf == "Sandals"):
            continue
        products.append({
            "id": pid, "brand": brand, "title": title, "current": current, "cat": key,
            "source": source, "note": note, "ai": looks, "aiDesc": ai, "ptype": ptype,
            "url": url, "img": img, "price": float(price) if price is not None else None,
            "approved": cat[1] in approved,
        })

    counts = Counter(p["cat"] for p in products)
    meta = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "in_stock": len(rows),
        "cats": [{"key": c[0], "name": c[1], "action": c[2], "where": c[3], "why": c[4],
                  "approved": c[1] in approved, "n": counts.get(c[0], 0)} for c in CATS],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "data.js").write_text(
        "window.NEWCAT = " + json.dumps({"meta": meta, "products": products}, ensure_ascii=False) + ";\n",
        encoding="utf-8")
    print(f"wrote {len(products)} products to {OUT / 'data.js'}")
    for c in meta["cats"]:
        src = Counter(p["source"] for p in products if p["cat"] == c["key"])
        print(f"  {c['name']:<24} {c['n']:>5}   review {src.get('review', 0):>4}  scan {src.get('scan', 0):>4}")


if __name__ == "__main__":
    main()
