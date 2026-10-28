"""
Measures the keyword categorizer (load_data.classify) against the reviewed
category decisions, without writing anything to products.

  answer key   category_overrides (the 2026-10-28 manual review): the path
               each product should get, or "hidden" for non-apparel
  baseline     classify()'s output saved once with --save-baseline, so every
               rule change shows exactly which other products it moves

    python eval_classify.py --save-baseline     # before changing rules
    python eval_classify.py                     # after: score + every change vs baseline
    python eval_classify.py --show 40           # more examples per change
    python eval_classify.py --write             # store the rules' categories (all products)

--write only ever changes category_id: a product the rules now exclude
(towels, candles...) is left alone, never deleted (backfill_categories.py
deletes those), and reviewed products keep their override via the trigger.
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import psycopg2

from category_lookup import build_category_lookup, resolve_category_id
from embed_products import build_category_paths
from load_data import DSN, classify, strip_html
from product_normalize import normalize_product_fields

BASELINE = Path(__file__).resolve().parent / "category_overrides" / "classify_baseline.json"
HIDDEN = "(hidden: not apparel)"


def run_classifier(cur, in_stock_only=True):
    category_id, leaf_lookup = build_category_lookup(cur)
    paths = build_category_paths(cur)
    cur.execute("""SELECT p.id, b.slug, p.title, p.raw_source, coalesce(p.ai_looks_like, '')
                   FROM products p JOIN brands b ON b.id = p.brand_id
                   WHERE p.raw_source IS NOT NULL"""
                + (" AND p.is_active AND p.embedding_v2 IS NOT NULL" if in_stock_only else ""))
    out, looks, titles = {}, {}, {}
    for pid, slug, title, raw, lk in cur.fetchall():
        p = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        nf = normalize_product_fields(p, slug == "cougar")
        description = strip_html(nf["description_html"]) or ""
        cls = classify(slug, p, title or "", nf["product_type"], ",".join(nf["tags"]), nf["vendor"], description)
        out[pid] = HIDDEN if cls is None else paths.get(resolve_category_id(cls, category_id, leaf_lookup), "?")
        looks[pid], titles[pid] = lk, title
    return out, looks, titles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save-baseline", action="store_true")
    ap.add_argument("--show", type=int, default=4, help="examples per change group")
    ap.add_argument("--write", action="store_true", help="store the new categories for every product")
    args = ap.parse_args()

    if args.write:
        write_all()
        return

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    now, looks, titles = run_classifier(cur)
    if args.save_baseline:
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text(json.dumps({str(k): v for k, v in now.items()}), encoding="utf-8")
        print(f"saved baseline for {len(now)} products")

    paths = build_category_paths(cur)
    cur.execute("SELECT product_id, category_id, hide, source FROM category_overrides")
    truth = {pid: (HIDDEN if hide else paths[cat], src) for pid, cat, hide, src in cur.fetchall()}
    base = {int(k): v for k, v in json.loads(BASELINE.read_text(encoding="utf-8")).items()}

    print("\nReviewed products the rules now get right (answer key = category_overrides):")
    per_src = defaultdict(lambda: [0, 0, 0])
    misses = Counter()
    miss_ex = defaultdict(list)
    for pid, (want, src) in truth.items():
        if pid not in now:
            continue
        s = per_src[src]
        s[0] += 1
        s[1] += base.get(pid) == want
        s[2] += now[pid] == want
        if now[pid] != want:
            k = (now[pid], want)
            misses[k] += 1
            miss_ex[k].append(titles[pid])
    tot = [sum(v[i] for v in per_src.values()) for i in range(3)]
    for src, (n, b, a) in sorted(per_src.items()) + [("TOTAL", tuple(tot))]:
        print(f"  {src:<15} {n:>5}   before {b:>5} ({100*b/n:5.1f}%)   after {a:>5} ({100*a/n:5.1f}%)")

    print("\nStill wrong, biggest groups (rules give -> review says):")
    for (got, want), n in misses.most_common(25):
        print(f"  {n:>4}  {got}  ->  {want}   e.g. {miss_ex[(got, want)][:2]}")

    changed = Counter()
    ex = defaultdict(list)
    for pid, v in now.items():
        if pid in truth or base.get(pid) == v:
            continue
        k = (base.get(pid), v)
        changed[k] += 1
        ex[k].append(f"{titles[pid]}  [AI: {looks[pid]}]")
    print(f"\nOther (unreviewed) products whose category changed vs baseline: {sum(changed.values())}")
    for (old, new), n in changed.most_common():
        print(f"  {n:>4}  {old}  ->  {new}")
        for e in ex[(old, new)][:args.show]:
            print(f"          {e}")


def write_all():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    by_path = {v: k for k, v in build_category_paths(cur).items()}
    now, _, _ = run_classifier(cur, in_stock_only=False)
    cur.execute("SELECT id, category_id FROM products")
    current = dict(cur.fetchall())
    updates = [(by_path[path], pid) for pid, path in now.items()
               if path in by_path and by_path[path] != current.get(pid)]
    cur.executemany("UPDATE products SET category_id = %s WHERE id = %s", updates)
    conn.commit()
    skipped = sum(1 for v in now.values() if v not in by_path)
    print(f"{len(now)} products classified, {len(updates)} category changes written, "
          f"{skipped} left as they are (excluded by the rules or no category)")


if __name__ == "__main__":
    main()
