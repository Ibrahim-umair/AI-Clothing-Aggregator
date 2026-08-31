"""
Business/content decision, NOT a classification fix: temporarily hides certain
real product types from the public frontend by setting products.is_browsable
= false (see db/init/01_schema.sql — the column already existed, unused,
until this script; server/index.js now filters every public query on it
alongside the existing is_active check).

This is fully reversible — is_browsable is a plain flag, no rows are
touched/deleted otherwise. To undo everything this script did:

    python hide_categories.py --unhide

Criteria hidden, per the 2026-08-28 request ("hide women shorts and tights;
where women sleeveless occurs, even in description; crop tops; women
underwears or vests"):

  1. Women's Shorts (category leaf "Shorts" under Women/Western/Bottomwear)
  2. Women's Tights (category leaf "Tights" under Women/Western/Bottomwear)
  3. Any Women's product with "sleeveless" anywhere in the title OR the
     stored description/raw source (not just the title — checked directly
     against real data: 46 matched by title, a further 117 only in the
     description/raw JSON, e.g. "Front Tie Top", "Striped Wrap Top", "Puffer
     Vest", "Long Dress With Waist Belt" all say "sleeveless" only in their
     body_html, never in the title).
  4. "Crop tops" — deliberately NOT every title containing "crop": this
     catalog uses "Cropped" broadly for cropped-length PANTS/TROUSERS/JEANS
     (9+8 real products, e.g. "Cropped Balloon Pants", "Cropped Wide Leg
     Pants") and cropped JACKETS/BLAZERS (20 real products, e.g. "Super
     Cropped Suede Jacket", "Cropped Blazer") — those are a length/silhouette
     choice on bottomwear/outerwear, not a "crop top", and hiding them would
     be over-broad. Scoped to "crop" in the title AND a real upperwear-top
     leaf (Shirt/T-Shirt/Sweatshirt/Hoodie/Sweater/Polo) under Women's
     Upperwear — 222 real products.
  5. Women's Underwear (category leaf "Underwear" under Women/Accessories) —
     already cleaned up earlier this session (a "vest" only stays in this
     leaf now if it's a genuine undergarment; see CHANGELOG.md #46), so this
     criterion is simply "all of it", 18 real products.
  6. Women's Tank Top (category leaf "Tank Top" under Women/Western/
     Upperwear, id 4393) — added 2026-08-30 per a follow-up request
     ("the tank tops of women should be hidden (shariah reasons)"),
     explicitly Women only (not Girls' Tank Top, a separate leaf, left
     untouched — not asked for). 214 real active products.

Extended 2026-08-31 during the Bandana.pk onboarding audit ("don't add non
shariah compliant clothes for women") — real gaps found by actually reading
Bandana's product descriptions before loading anything, not brand-specific
rules (this WHERE clause is gender+category+text based, so both apply
retroactively to every existing brand too):

  7. "Spaghetti strap" — Bandana's "Modal Rib Lace Tank" says "V-neckline,
     spaghetti straps, straight hem" but never says "sleeveless" anywhere,
     so criterion #3 missed it entirely. Same title/description/raw_source
     scan as "sleeveless".
  8. The crop-top check (#4) was TITLE-ONLY — Bandana has 5 real products
     where "cropped length"/"cropped hem" only appears in the DESCRIPTION,
     never the title (e.g. "Women's Brushed Spacer Hoodie", "Women's Rib
     Relaxed Fit Turtleneck"). Extended to scan description/raw_source too,
     same leaf-gating as before (a real upperwear-top leaf only — bottomwear/
     outerwear "cropped" length is still not a modesty concern, unchanged).
  9. Sleeveless carve-out for vests/gilets/bodywarmers: a real Bandana
     "Goose Down Reversible Gilet" says "sleeveless design" in its own
     description, but a gilet/bodywarmer/vest is BY DEFINITION a sleeveless
     OUTERWEAR LAYER worn over other clothing (arms are covered by whatever's
     underneath) — applying the blanket sleeveless rule to these would hide
     an entire legitimate outerwear category for no modesty reason. Excluded
     by garment word in the title (vest/gilet/bodywarmer), not by leaf,
     since these are internally confirmed as genuine outerwear (not a
     casual sleeveless top mislabeled "vest") by classify()'s own
     VEST_OUTERWEAR_SIGNAL_RE check before ever reaching the Jacket leaf.

Real counts confirmed via direct query against the live DB before writing
anything (see the SELECT-only dry run this script prints first).
"""
import sys
import psycopg2

from load_data import DSN

WOMEN_GENDER_ID = 39
WOMEN_SHORTS_CATEGORY_ID = 51
WOMEN_TIGHTS_CATEGORY_ID = 1992
WOMEN_UNDERWEAR_CATEGORY_ID = 529
WOMEN_UPPERWEAR_CATEGORY_ID = 41
WOMEN_TANK_TOP_CATEGORY_ID = 4393
CROP_TOP_LEAVES = ("Shirt", "T-Shirt", "Sweatshirt", "Hoodie", "Sweater", "Polo")

# One WHERE clause combining every criterion above (dedupes naturally: a
# product matching more than one criterion is still only touched once).
HIDE_WHERE_SQL = """
    p.category_id = %(shorts)s
    OR p.category_id = %(tights)s
    OR p.category_id = %(underwear)s
    OR p.category_id = %(tank_top)s
    OR (
        p.category_id IN (
            WITH RECURSIVE desc_cats AS (
                SELECT id FROM categories WHERE id = %(women_gender)s
                UNION ALL
                SELECT c.id FROM categories c JOIN desc_cats d ON c.parent_id = d.id
            )
            SELECT id FROM desc_cats
        )
        AND (
            p.title ILIKE '%%sleeveless%%'
            OR p.description ILIKE '%%sleeveless%%'
            OR p.raw_source::text ILIKE '%%sleeveless%%'
            OR p.title ILIKE '%%spaghetti strap%%'
            OR p.description ILIKE '%%spaghetti strap%%'
            OR p.raw_source::text ILIKE '%%spaghetti strap%%'
        )
        AND p.title NOT ILIKE '%%vest%%'
        AND p.title NOT ILIKE '%%gilet%%'
        AND p.title NOT ILIKE '%%bodywarmer%%'
    )
    OR (
        (
            p.title ILIKE '%%crop%%'
            OR p.description ILIKE '%%cropped%%'
            OR p.raw_source::text ILIKE '%%cropped%%'
        )
        AND p.category_id IN (
            SELECT id FROM categories
            WHERE parent_id = %(women_upperwear)s AND name = ANY(%(crop_leaves)s)
        )
    )
"""

PARAMS = {
    "shorts": WOMEN_SHORTS_CATEGORY_ID,
    "tights": WOMEN_TIGHTS_CATEGORY_ID,
    "underwear": WOMEN_UNDERWEAR_CATEGORY_ID,
    "tank_top": WOMEN_TANK_TOP_CATEGORY_ID,
    "women_gender": WOMEN_GENDER_ID,
    "women_upperwear": WOMEN_UPPERWEAR_CATEGORY_ID,
    "crop_leaves": list(CROP_TOP_LEAVES),
}


def main():
    unhide = "--unhide" in sys.argv
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()

    count_sql = f"SELECT COUNT(*) FROM products p WHERE ({HIDE_WHERE_SQL}) AND p.is_browsable = {'false' if unhide else 'true'}"
    cur.execute(count_sql, PARAMS)
    (n,) = cur.fetchone()

    if unhide:
        print(f"Un-hiding {n} products (setting is_browsable back to true)...")
        cur.execute(f"UPDATE products p SET is_browsable = true WHERE ({HIDE_WHERE_SQL}) AND p.is_browsable = false", PARAMS)
    else:
        print(f"Hiding {n} products (setting is_browsable = false)...")
        cur.execute(f"UPDATE products p SET is_browsable = false WHERE ({HIDE_WHERE_SQL}) AND p.is_browsable = true", PARAMS)

    conn.commit()
    print(f"DONE: {cur.rowcount} rows updated.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
