"""
Applies the 2026-10-28 category review as category overrides (see
migrations/2026-10-28_category_overrides.sql: a trigger keeps them in place
when the scraper or load_data.py rewrites category_id).

Two steps, so production gets exactly what was reviewed locally:

    python apply_category_overrides.py build      # review files -> db/category_overrides/2026-10-28.json
    python apply_category_overrides.py apply --dry-run
    python apply_category_overrides.py apply
    python apply_category_overrides.py undo newcat-scan   # one source back to the rules' category

Sources (a product in several keeps the last one in this order):
  review-round1   clear fixes Ibrahim approved in round 1 (groups + single products)
  review-round2   clear fixes Ibrahim approved in round 2
  newcat-review   new-category products from Claude's one-by-one review
  newcat-scan     new-category products found by the whole-catalog scan
Products are matched by (brand, native product id), not the local row id.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import psycopg2

from embed_products import build_category_paths
from load_data import DSN

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "local-notes" / "catreview"
EXPORTS = ROOT / "review-exports"
OUT = Path(__file__).resolve().parent / "category_overrides" / "2026-10-28.json"

# Where each new category lives under a gender root.
NEWCAT_PATH = {
    "gloves": "Accessories > Gloves",
    "hair": "Accessories > Hair Accessories",
    "pins": "Accessories > Pins & Clips",
    "gift": "Accessories > Gift Set",
    "suspenders": "Accessories > Suspenders",
    "swim": "Western > Swimwear > Swimwear",
    "abaya": "Eastern > Stitched > Abaya",
    "lehenga": "Eastern > Stitched > Lehenga",
    "dupatta": "Eastern > Stitched > Dupatta",
    "eastbottoms": "Eastern > Stitched > Shalwar & Pajama",
    "night": "Western > Sleepwear > Nightwear & Loungewear",
    "sandals": "Western > Footwear > Sandals",
    "blazer": "Western > Upperwear > Blazer",  # Men/Boys: see BLAZER_FORMAL
}
BLAZER_FORMAL = {"Men", "Boys"}
HIDE = {"towels", "candles", "shoecare", "skincare", "buttons"}
# The Unisex tree only has a few of the new leaves; products filed Unisex
# today are mostly "gender unknown", so they go to the usual buyer instead.
UNISEX_FALLBACK = {"pins": "Men", "gift": "Men", "suspenders": "Men", "dupatta": "Women",
                   "abaya": "Women", "hair": "Girls", "lehenga": "Girls", "blazer": "Men",
                   "gloves": "Men", "eastbottoms": "Men", "night": "Women", "swim": "Girls"}


def read_js(path):
    s = path.read_text(encoding="utf-8")
    return json.loads(s[s.index("{"):s.rindex("}") + 1])


def group_key(p):
    return p["current"].split(" > ")[-1] + " → " + p["target"] + "|" + p["cause"]


def approved_clear_fixes(review_file, data_file):
    """Ids of clear-fix products in groups (or single products) marked ok."""
    review = json.loads(review_file.read_text(encoding="utf-8"))
    ok_groups = {k[4:] for k, v in review.get("groups", {}).items() if v.get("v") == "ok"}
    votes = {int(k): v.get("v") for k, v in review.get("products", {}).items()}
    out = {}
    for p in read_js(data_file)["products"]:
        if p["case"] != "A" or p["target"] == p["current"]:
            continue
        vote = votes.get(p["id"])
        if vote == "no":
            continue
        if vote == "ok" or group_key(p) in ok_groups:
            out[p["id"]] = p["target"]
    return out


def build():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    paths = build_category_paths(cur)
    path_ids = set(paths.values())

    decisions = {}
    for line in (NOTES / "decisions.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            pid, case, target, note = line.split("|", 3)
            decisions[int(pid)] = (case, target.strip(), note.strip())

    rows = {}  # local id -> (target path or None, hide, source, note)
    r1 = approved_clear_fixes(NOTES / "review1_user.json", EXPORTS / "category-decisions" / "data.js")
    r2 = approved_clear_fixes(NOTES / "review2_user.json", NOTES / "v2_data_round2_backup.js")
    for source, ids in (("review-round1", r1), ("review-round2", r2)):
        for pid, target in ids.items():
            rows[pid] = (target, False, source, decisions.get(pid, ("", "", ""))[2])

    unresolved = Counter()
    for p in read_js(EXPORTS / "new-categories" / "data.js")["products"]:
        key, pid = p["cat"], p["id"]
        source = "newcat-" + p["source"]
        if key in HIDE:
            rows[pid] = (None, True, source, p["note"] or p["ai"])
            continue
        gender = p["current"].split(" > ")[0]
        if p["source"] == "review" and pid in decisions:
            gender = decisions[pid][1].split(" > ")[0]  # the review also fixed wrong genders
        if gender == "Unisex" and gender + " > " + NEWCAT_PATH[key] not in path_ids:
            gender = UNISEX_FALLBACK[key]
        path = "Western > Formalwear > Blazer" if key == "blazer" and gender in BLAZER_FORMAL else NEWCAT_PATH[key]
        if key == "eastbottoms" and gender in ("Women", "Girls"):
            path = "Eastern > Stitched > Bottoms"  # Nov 2026 tree
        target = gender + " > " + path
        if target not in path_ids:
            unresolved[target] += 1
            continue
        rows[pid] = (target, False, source, p["note"] or p["ai"])

    bad = Counter(t for t, hide, _, _ in rows.values() if not hide and t not in path_ids)
    if unresolved or bad:
        sys.exit(f"targets missing from the category tree: {dict(unresolved | bad)}")

    cur.execute("""SELECT p.id, b.slug, p.native_product_id FROM products p JOIN brands b ON b.id = p.brand_id
                   WHERE p.id = ANY(%s)""", (list(rows),))
    native = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    out = [{"brand": native[pid][0], "native_id": native[pid][1], "category": t, "hide": hide,
            "source": src, "note": note}
           for pid, (t, hide, src, note) in sorted(rows.items())]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"wrote {len(out)} overrides to {OUT}")
    for src, n in sorted(Counter(o["source"] for o in out).items()):
        print(f"  {src:<15} {n:>5}")
    print(f"  hidden          {sum(o['hide'] for o in out):>5}")


def apply(dry_run):
    items = json.loads(OUT.read_text(encoding="utf-8"))
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    by_path = {v: k for k, v in build_category_paths(cur).items()}
    cur.execute("SELECT b.slug, p.native_product_id, p.id, p.category_id, p.ai_category_ok "
                "FROM products p JOIN brands b ON b.id = p.brand_id")
    prod = {(r[0], r[1]): r[2:] for r in cur.fetchall()}

    missing, todo = 0, []
    for o in items:
        hit = prod.get((o["brand"], o["native_id"]))
        if hit is None:
            missing += 1
            continue
        pid, old_cat, old_ok = hit
        cat_id = None if o["hide"] else by_path.get(o["category"])
        if not o["hide"] and cat_id is None:
            sys.exit(f"category not in this database: {o['category']} (run reseed_categories.py first)")
        todo.append((pid, cat_id, o["hide"], old_cat, old_ok, o["source"], o["note"]))

    moved = sum(1 for t in todo if t[1] is not None and t[1] != t[3])
    print(f"{len(todo)} overrides ({moved} change category, {sum(t[2] for t in todo)} hidden), "
          f"{missing} products not in this database")
    for src, n in sorted(Counter(t[5] for t in todo).items()):
        print(f"  {src:<15} {n:>5}")
    if dry_run:
        print("dry run: nothing written")
        return

    # old_* columns keep the first value seen, so re-running never loses the
    # category the rules had before any override.
    cur.executemany("""
        INSERT INTO category_overrides (product_id, category_id, hide, old_category_id, old_ai_category_ok, source, note)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (product_id) DO UPDATE SET category_id = EXCLUDED.category_id, hide = EXCLUDED.hide,
            source = EXCLUDED.source, note = EXCLUDED.note
    """, todo)
    ids = [t[0] for t in todo]
    # Touching category_id fires the trigger, which writes the override in.
    # A product the AI flagged as miscategorized is fixed now, so it is shown
    # again in search v2 (which hides ai_category_ok = false).
    cur.execute("""UPDATE products SET category_id = category_id,
                       ai_category_ok = CASE WHEN ai_category_ok IS FALSE THEN NULL ELSE ai_category_ok END
                   WHERE id = ANY(%s)""", (ids,))
    conn.commit()
    cur.execute("""SELECT count(*) FROM products p JOIN category_overrides o ON o.product_id = p.id
                   WHERE (o.category_id IS NOT NULL AND p.category_id <> o.category_id) OR (o.hide AND p.is_browsable)""")
    print(f"applied; products not matching their override: {cur.fetchone()[0]}")


def undo(source):
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        WITH gone AS (DELETE FROM category_overrides WHERE source = %s
                      RETURNING product_id, old_category_id, old_ai_category_ok, hide)
        UPDATE products p SET category_id = g.old_category_id, ai_category_ok = g.old_ai_category_ok,
               is_browsable = CASE WHEN g.hide THEN true ELSE p.is_browsable END
        FROM gone g WHERE p.id = g.product_id
    """, (source,))
    print(f"undid {cur.rowcount} products from {source}")
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    a = sub.add_parser("apply")
    a.add_argument("--dry-run", action="store_true")
    u = sub.add_parser("undo")
    u.add_argument("source")
    args = ap.parse_args()
    if args.cmd == "build":
        build()
    elif args.cmd == "apply":
        apply(args.dry_run)
    else:
        undo(args.source)


if __name__ == "__main__":
    main()
