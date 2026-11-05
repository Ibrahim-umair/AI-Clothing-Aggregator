"""
Scores the keyword categoriser (classify()) against the 15k reviewed sample
(local-notes/audit_15k/reviewed.json, from the Nov 2026 agent audit of the
11 women's stores plus Ibrahim's verdicts per error pattern).

The answer for each product:
  approved          his approved pattern: the reviewer's category
  rule_right_by_ai  the reviewer said today's rule answer was right: today's
                    answer, renamed into the new tree
  needs_relabel     a pattern he corrected: his correction (see RELABEL)
  not_reviewed, unsure: not scored (counted separately)

    python eval_categorizer.py                 # score, save as the latest run
    python eval_categorizer.py --baseline      # also save it as the baseline
    python eval_categorizer.py --diff          # list products that got worse vs the baseline
    python eval_categorizer.py --set unseen    # Saya + Iznik, checked by agents (local-notes/audit_saya_iznik)

Needs the local database (products.raw_source) for the inputs.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg2

from load_data import CATEGORY_TREE, DSN, classify, strip_html
from product_normalize import normalize_product_fields

NOTES = Path(__file__).resolve().parent.parent / "local-notes" / "audit_15k"
UNSEEN = NOTES.parent / "audit_saya_iznik"
ST, UN = "Eastern > Stitched > ", "Eastern > Unstitched > "
TT, TD = "2-Piece (Shirt + Trouser)", "2-Piece (Shirt + Dupatta)"

DUP = re.compile(r"\b(?:dupatt?as?|shawls?|stoles?)\b", re.I)
BOT = re.compile(r"\b(?:shalwars?|salwars?|trousers?|pajamas?|pyjamas?|pants?|culottes?|tights|sharara|gharara|capris?|bottoms?)\b", re.I)
COUNT = re.compile(r"\b([1-4])\s*-?\s*(?:pcs?|pieces?|p)\b", re.I)


def pieces_leaf(text, default=TT):
    """Women/Girls stitched set leaf from what the text says is included."""
    m = COUNT.search(text)
    n = int(m.group(1)) if m else None
    dup, bot = bool(DUP.search(text)), bool(BOT.search(text))
    if n == 3 or (dup and bot):
        return "3-Piece"
    if n == 1:
        return "1-Piece"
    if dup:
        return TD
    if bot or n == 2:
        return TT
    return default


def renamed(path, r):
    """An answer written in the old tree, said in the new tree."""
    g, _, rest = path.partition(" > ")
    text = f"{r['title']} {r.get('desc', '')}"
    leaf = rest.rpartition(" > ")[2]
    if g in ("Women", "Girls") and rest.startswith(ST):
        if leaf in ("Kurta", "Kurti"):
            return f"{g} > {ST}1-Piece"
        if leaf in ("Kurta Set", "Shalwar Kameez"):
            return f"{g} > {ST}{pieces_leaf(text)}"
        if leaf == "Shalwar & Pajama":
            return f"{g} > {ST}Bottoms"
    if g in ("Women", "Girls") and rest.startswith(UN):
        if leaf == "Suit":
            return f"{g} > {UN}3-Piece"
        if leaf == "2-Piece":
            return f"{g} > {UN}{TD if DUP.search(text) and not BOT.search(text) else TT}"
    if g in ("Men", "Boys", "Unisex") and rest == ST + "Kurta Set":
        return f"{g} > {ST}" + ("Kurta Trouser" if re.search(r"trouser|pajama|pyjama|pant", text, re.I) else "Shalwar Kameez")
    return path


HOME = [("Bedding", r"bed ?sheet|fitted sheet|sheet set|quilt|comforter|duvet|bed in a bag|pillow|blanket|throw|bed ?spread|mattress|bed set|neck roll|fleece|4pc set"),
        ("Cushions", r"cushion|euro sham|\bsham\b"),
        ("Table & Kitchen", r"place ?mat|runner|platter|plate|dish|mug|\bcup|bowl|napkin|table|tray|coaster|multipurpose mat|apron"),
        ("Curtains & Rugs", r"curtain|\brug|prayer mat|carpet"),
        ("Bath", r"towel|bath"),
        ("Home Fragrance", r"diffuser|candle|room|scent ?scape|reed|bakhoor|abstract air")]
BEAUTY = [("Makeup", r"\blip|eye|brow|mascara|foundation|contour|palette|blush|nail|kajal|highlighter|concealer|powder|primer|fixing spray|perfecting pen|balm"),
          ("Skincare", r"serum|cream|cleans|face ?wash|toner|moistur|sunscreen|lotion|mask|scrub|\boil|shower gel")]


def not_apparel(r):
    for leaf, rx in HOME:
        if re.search(rx, r["title"], re.I):
            return f"Unisex > Home > {leaf}"
    for leaf, rx in BEAUTY:
        if re.search(rx, r["title"], re.I):
            return f"Women > Fragrance & Beauty > {leaf}"
    return None  # gift box, packaging: excluded


def new_type(r):
    t = f"{r['title']} {r['fix']}"
    g = r["now"].split(" > ")[0]
    if re.search(r"kaftan|caftan|jalabiy", t, re.I):
        return f"Women > {ST}Kaftan"
    if re.search(r"jubba", t, re.I):
        return f"{g if g in ('Men', 'Boys') else 'Men'} > {ST}Jubba"
    if re.search(r"\bcape|poncho", t, re.I):
        return "Women > Accessories > Cape"
    if re.search(r"saree|sari\b", t, re.I):
        return f"Women > {ST}Saree"
    if re.search(r"shrug", t, re.I):
        return "Women > Western > Upperwear > Sweater"
    if re.search(r"\bslip|inner", t, re.I):
        return f"Women > {ST}Slip / Inner"
    return "SKIP"


def answer(r, stock):
    """The right category for a reviewed product, or None when it isn't scored."""
    title = r["title"]
    if re.search(r"\bhijabs?\b", title, re.I):
        return "Women > Accessories > Hijab"
    if re.search(r"\bcapes?\b|\bponchos?\b", title, re.I) and not r["now"].startswith(("Men", "Boys")):
        return "Women > Accessories > Cape"  # his call: cape shawls are their own category
    if re.search(r"\bsarees?\b", title, re.I) and not re.search(r"fabric|unstitched", title + r.get("desc", ""), re.I):
        return f"Women > {ST}Saree"
    review, pat = r["review"], r.get("pattern")
    if review == "rule_right_by_ai":
        return renamed(r["now"], r)
    if review in ("not_reviewed", "unsure"):
        return None
    fix = r["fix"]
    if fix.startswith("NOT_APPAREL"):
        return not_apparel(r) or "EXCLUDED"
    if fix.startswith("NEW"):
        got = new_type(r)
        return None if got == "SKIP" else got
    if review == "needs_relabel":
        if pat in (12, 22):  # men's/boys' kurta + trouser is a Kurta Trouser
            if re.search(r"trouser|pajama|pyjama|pant", title, re.I):
                return fix.replace("Kurta Set", "Kurta Trouser")
            return fix.replace("Kurta Set", "Shalwar Kameez")  # kurta shalwar is shalwar kameez
        if pat == 14:  # girls' suits use the piece-count leaves
            return f"Girls > {ST}{pieces_leaf(title + ' ' + r.get('desc', ''))}"
        if pat == 10:
            if re.search(r"dress pants?|formal (?:pants?|trousers?)", title, re.I):
                return "Men > Western > Formalwear > Dress Pants"
            return fix
        if pat == 27:  # Maria B fabric: count only the pieces in stock
            have = stock.get(r["id"], [])
            if not have:
                return fix
            shirt = any(re.search(r"shirt|front|back|sleeve", x, re.I) for x in have)
            dup = any(re.search(r"dupatta", x, re.I) for x in have)
            bot = any(re.search(r"trouser|shalwar", x, re.I) for x in have)
            if not shirt:
                return "EXCLUDED"  # no shirt left: not a suit
            n = 1 + dup + bot
            return f"Women > {UN}" + ("3-Piece" if n == 3 else TD if dup else TT if bot else "1-Piece")
        if r.get("id") == 1108924:
            return "Girls > Western > Upperwear > Jacket"
        return fix
    return renamed(fix, r)


def leaf_exists(gender, branch, sub, leaf):
    node = CATEGORY_TREE.get(gender, {}).get(branch)
    if node is None:
        return False
    if isinstance(node, dict):
        return any(name == leaf for name, _ in node.get(sub, []))
    return any(name == leaf for name, _ in node)


def to_path(cls):
    if cls is None:
        return "EXCLUDED"
    g, b, s, l = cls["gender"], cls["branch"], cls.get("sub"), cls["leaf"]
    if l and leaf_exists(g, b, s, l):
        return " > ".join(x for x in (g, b, s, l) if x)
    return f"{g} > {b}"


def load_inputs(ids):
    cur = psycopg2.connect(DSN).cursor()
    cur.execute("""SELECT p.id, b.slug, p.title, p.raw_source FROM products p JOIN brands b ON b.id = p.brand_id
                   WHERE p.id = ANY(%s)""", (ids,))
    return {pid: (slug, title, raw) for pid, slug, title, raw in cur.fetchall()}


def run():
    rows = json.load(open(NOTES / "reviewed.json", encoding="utf-8"))
    inputs = load_inputs([r["id"] for r in rows])
    stock = {pid: [v.get("title", "") for v in (raw.get("variants") or []) if v.get("available")]
             for pid, (_, _, raw) in inputs.items()}
    out = {}
    for r in rows:
        want = answer(r, stock)
        if r["id"] not in inputs:
            continue
        slug, title, raw = inputs[r["id"]]
        nf = normalize_product_fields(raw, slug == "cougar")
        desc = strip_html(nf["description_html"]) or ""
        got = to_path(classify(slug, raw, title, nf["product_type"], ",".join(nf["tags"]), nf["vendor"], desc))
        out[r["id"]] = {"want": want, "got": got, "store": slug, "title": title, "pattern": r.get("pattern"),
                        "review": r["review"]}
    return out


def run_unseen():
    """Saya + Iznik, checked by the agents against the app's prompt (local-notes/audit_saya_iznik)."""
    rows = json.load(open(UNSEEN / "merged.json", encoding="utf-8"))
    inputs = load_inputs([r["id"] for r in rows])
    out = {}
    for r in rows:
        want = r["want"] if r["want"] and not r["want"].startswith("NEW") else None
        slug, title, raw = inputs[r["id"]]
        nf = normalize_product_fields(raw, False)
        desc = strip_html(nf["description_html"]) or ""
        got = to_path(classify(slug, raw, title, nf["product_type"], ",".join(nf["tags"]), nf["vendor"], desc))
        out[r["id"]] = {"want": want, "got": got, "store": slug, "title": title, "pattern": None, "review": "agent"}
    return out


def report(out):
    scored = [o for o in out.values() if o["want"]]
    right = sum(o["want"] == o["got"] for o in scored)
    print(f"scored {len(scored):,}: {right:,} right ({right / len(scored):.1%})")
    by_store = defaultdict(Counter)
    for o in scored:
        by_store[o["store"]][o["want"] == o["got"]] += 1
    print("  " + "  ".join(f"{s} {c[True] / sum(c.values()):.0%}" for s, c in sorted(by_store.items())))
    for review in ("approved", "needs_relabel", "rule_right_by_ai"):
        sub = [o for o in scored if o["review"] == review]
        print(f"  {review:17} {sum(o['want'] == o['got'] for o in sub):,}/{len(sub):,}")
    pats = defaultdict(Counter)
    for o in scored:
        if o["pattern"]:
            pats[o["pattern"]][o["want"] == o["got"]] += 1
    print("  patterns: " + "  ".join(f"#{p} {c[True]}/{sum(c.values())}" for p, c in sorted(pats.items()) if p <= 32))
    wrong = Counter((o["got"], o["want"]) for o in scored if o["want"] != o["got"])
    print("  top remaining mistakes (rule -> answer):")
    for (g, w), n in wrong.most_common(30):
        print(f"   {n:5}  {g}  ->  {w}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--set", choices=["15k", "unseen"], default="15k")
    a = ap.parse_args()
    where = NOTES if a.set == "15k" else UNSEEN
    out = run() if a.set == "15k" else run_unseen()
    report(out)
    json.dump(out, open(where / "eval_latest.json", "w", encoding="utf-8"), ensure_ascii=False)
    if a.baseline:
        json.dump(out, open(where / "eval_baseline.json", "w", encoding="utf-8"), ensure_ascii=False)
    if a.diff and (where / "eval_baseline.json").exists():
        base = {int(k): v for k, v in json.load(open(where / "eval_baseline.json", encoding="utf-8")).items()}
        worse = [(i, o) for i, o in out.items() if o["want"] and base.get(i, {}).get("got") == o["want"] != o["got"]]
        print(f"  {len(worse)} got worse vs baseline:")
        for i, o in worse[:60]:
            print(f"   {o['store']:16} {o['title'][:50]:50} {o['got']}  (want {o['want']})")
