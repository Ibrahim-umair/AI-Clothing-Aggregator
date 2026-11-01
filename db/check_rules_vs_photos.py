"""
Checks the keyword categorizer (load_data.classify) against what the AI saw
in each product's photos (ai_looks_like, e.g. "polo shirt", "slide sandals"),
across every in-stock product. No LLM calls: the photo labels were stored by
the enrichment run.

    python check_rules_vs_photos.py                  # score + biggest disagreements
    python check_rules_vs_photos.py --save round1    # also snapshot this round
    python check_rules_vs_photos.py --vs round1      # products moved since round1
    python check_rules_vs_photos.py --group "Shirt" --show 30   # one group in detail

Held-out stores (HOLDOUT) are scored but never listed, so rules aren't written
from them: their score is how the rules do on a store they've never seen.

The label -> category table below only serves this check. A label maps to
every category that is a fair answer for it ("three-piece suit" can be a
men's Formal Suit or a women's 3-Piece), so only clear disagreements count.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import psycopg2

from eval_classify import HIDDEN, run_classifier
from embed_products import build_category_paths
from load_data import DSN

HOLDOUT = {"bandana", "furor", "royal_tag"}
SNAPSHOTS = Path(__file__).resolve().parent.parent / "local-notes" / "catrules"

UNSTITCHED = {"Suit", "1-Piece", "2-Piece", "3-Piece"}
EASTERN_SET = {"Kurta Set", "Shalwar Kameez", "Kurta Shalwar", "2-Piece", "3-Piece", "Suit", "1-Piece"}
TOPS = {"Top", "T-Shirt", "Shirt", "Tank Top", "Kurti"}
NIGHT = {"Nightwear & Loungewear"}

# (label pattern, acceptable leaves). The label's head noun decides: the
# match that ends last ("dress SHIRT", "low-top SNEAKERS"); on a tie the
# earlier rule wins, so sets and specific names come first.
LABEL_RULES = [
    (r"(towel|candle|shoe ?horn|insole|insert|shoe (brush|polish|care|cleaner)|lotion|lipstick|mug|cushion).*$", {HIDDEN}),
    (r"thermal.*$", {"Underwear", "Co-ord Set", "Trouser", "T-Shirt"}),
    (r"perfume|parfum|fragrance|cologne|body mist|attar", {"Perfume", "Gift Set"}),
    (r"(gift|accessor(y|ies)|tie|necktie|cufflink|jewel(le)?ry|box)\b.*\b(set|box|combo)", {"Gift Set", "Tie", "Jewelry", "Cufflink", "Pocket Square"}),
    (r"unstitched.*$|(shirt |suit |lawn )?fabric.*$|suit length", UNSTITCHED),
    (r"saree|sari\b", {"Saree"}),
    (r"(lehenga|sharara|gharara).*$", {"Lehenga", "Kurta Set", "Shalwar Kameez", "3-Piece", "2-Piece"}),
    (r"abaya", {"Abaya"}),
    (r"sherwani|prince coat", {"Sherwani"}),
    (r"^((wo)?men'?s |girls |boys |plain |white |printed )?(shalwar|pajama|pyjama|churidar)( trousers?| pants?)?$", {"Shalwar & Pajama", "Trouser"}),
    (r"(waistcoat|kurta|kurti|kameez|shalwar|tunic|kaftan|dupatta|eastern|embroidered|printed|lawn)\b.*\b(set|suit|pajama|pyjama|shalwar|trousers?|dupatta)\b|kameez shalwar|shirt (shalwar|dupatta)( set)?|kurta|kurti|kameez", EASTERN_SET | {"Kurta", "Kurti"}),
    # Shirt + trouser is an Eastern suit or a Western co-ord; the photo label can't tell.
    (r"shirt (and )?trousers?( set)?", EASTERN_SET | {"Co-ord Set", "Kurta", "Kurti"}),
    (r"(pajama|pyjama|sleep|night|lounge)\w*( set)?|robe\b|\bpj", NIGHT | {"Co-ord Set"}),
    (r"swim\w*|bikini", {"Swimwear"}),
    (r"dupatta", {"Dupatta"}),
    (r"shawl|stole|cape\b", {"Shawl", "Scarf"}),
    (r"scarf|muffler", {"Scarf", "Shawl"}),
    (r"(three|two|3|2)[- ]piece suit|\bsuit\b", {"Formal Suit", "3-Piece", "2-Piece", "Suit", "Kurta Set", "Shalwar Kameez", "Co-ord Set"}),
    (r"track ?suit", {"Tracksuit", "Co-ord Set"}),
    (r"co-?ord( set)?|two[- ]piece set|\bset\b|\b(tee|t-shirt|top|tank|shirt|hoodie|sweatshirt|polo)s? (and|&) \w+( set)?|matching \w+", {"Co-ord Set", "Tracksuit", "Formal Suit"} | NIGHT | EASTERN_SET),
    (r"waistcoat|waist coat|\bkoti\b|gilet|vest\b", {"Waistcoat", "Vest", "Jacket", "Sweater", "Underwear", "Tank Top"}),
    (r"blazer|sport coat|suit jacket", {"Blazer"}),
    (r"jumpsuit|romper|playsuit|dungaree|overall|bodysuit|onesie", {"Jumpsuit"} | NIGHT),
    (r"dress\b|frock|gown", {"Dress", "Frock"}),
    (r"tunic", {"Dress", "Top", "Kurti", "Kurta"}),
    (r"skirt|skort", {"Skirt"}),
    (r"legging|tights|jegging", {"Tights", "Trouser", "Jeans"}),
    (r"jogger\w*|sweatpant|track ?pants?|track trousers?", {"Joggers", "Trouser", "Cargo Trouser"}),
    (r"cargo (trousers?|pants?|jeans)", {"Cargo Trouser", "Trouser", "Joggers", "Jeans"}),
    (r"jeans|denim pants?", {"Jeans"}),
    (r"boxers?( shorts| briefs)?|briefs|undershirt|underwear|innerwear|\bbra\b|panty|panties|sando|thermal", {"Underwear", "Tank Top", "Shorts"}),
    (r"\bshorts\b|bermuda", {"Shorts"} | NIGHT),
    (r"trousers?|pants\b|chinos?|slacks|culottes?|palazzos?|bottoms?\b", {"Trouser", "Joggers", "Cargo Trouser", "Jeans", "Shalwar & Pajama", "Tights"} | NIGHT),
    (r"coat|jacket|parka|bomber|windbreaker|shacket|anorak|puffer|trench|cardigan", {"Jacket", "Blazer", "Sweater", "Hoodie", "Sweatshirt", "Shirt"}),
    (r"hoodie|hooded (sweatshirt|top|jacket)", {"Hoodie", "Sweatshirt", "Jacket"}),
    (r"polo sweat ?shirt", {"Polo", "Sweatshirt"}),
    (r"sweatshirt|pullover|fleece top", {"Sweatshirt", "Hoodie", "Sweater", "Jacket"}),
    (r"sweater|jumper|knit polo|turtleneck|mock ?neck|cable knit", {"Sweater", "Polo", "Sweatshirt", "T-Shirt"}),
    (r"polo( shirt| t-shirt)?", {"Polo", "T-Shirt", "Sweater"}),
    (r"tank( top)?|cami(sole)?|sleeveless top|crop top|bralette|sports bra|halter", {"Tank Top", "Top", "Underwear", "T-Shirt"}),
    (r"t-?shirt|\btees?\b|henley t", {"T-Shirt", "Polo", "Top"}),
    (r"blouse|\btops?\b|peplum", TOPS),
    (r"shirt|henley", {"Shirt", "T-Shirt", "Polo", "Top", "Kurta", "Kurti"}),
    (r"socks?", {"Socks"}),
    (r"sandals?|slides?|flip.?flops?|chappals?|peshawari|kolhapuri|mules?|slippers?|khussa", {"Sandals", "Shoes"}),
    (r"heels?|pumps?|flats|loafers?|sneakers?|trainers?|shoes?|boots?|oxfords?|brogues?|derby|moccasins?|espadrilles?|monk straps?|wedges?", {"Shoes", "Sandals"}),
    (r"lapel|brooch|tie pin|tie bar|tie clip|collar (bar|pin)|\bpin\b", {"Pins & Clips", "Jewelry"}),
    (r"hair|scrunch|claw clip|headband", {"Hair Accessories"}),
    (r"\btie\b|necktie|bow tie|cravat", {"Tie"}),
    (r"pocket square", {"Pocket Square"}),
    (r"cufflinks?", {"Cufflink"}),
    (r"suspenders?|braces\b", {"Suspenders"}),
    (r"belt", {"Belt"}),
    (r"wallet|card ?holder", {"Wallet"}),
    (r"bag|tote|clutch|purse|backpack|pouch|satchel|duffel", {"Bag"}),
    (r"\bcap\b|\bhat\b|beanie|bucket|visor", {"Cap"}),
    (r"sunglass\w*|eyewear|spectacles", {"Sunglasses"}),
    (r"gloves?|mittens?", {"Gloves"}),
    (r"watch", {"Watch"}),
    (r"keychain|key ?ring|charm", {"Keychain", "Jewelry"}),
    (r"earrings?|necklace|bracelet|\brings?\b|bangles?|jewel\w*|anklet|pendant|chain\b", {"Jewelry"}),
]
LABEL_RULES = [(re.compile(p, re.I), s) for p, s in LABEL_RULES]


def head_match(label):
    """(match, leaves) for the label's head noun, or None."""
    best = None
    for i, (rx, leaves) in enumerate(LABEL_RULES):
        for m in rx.finditer(label):
            key = (m.end(), -i)
            if best is None or key > best[0]:
                best = (key, m, leaves)
    return None if best is None else (best[1], best[2])


def label_to_leaves(label):
    h = head_match(label)
    return None if h is None else h[1]


def leaf_of(path):
    return HIDDEN if path == HIDDEN else path.split(" > ")[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", help="snapshot name for this round")
    ap.add_argument("--vs", help="list products moved since this snapshot")
    ap.add_argument("--group", help="only show disagreements whose rule leaf or photo label contains this")
    ap.add_argument("--show", type=int, default=3)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    now, looks, titles = run_classifier(cur)
    cur.execute("""SELECT p.id, b.slug FROM products p JOIN brands b ON b.id = p.brand_id
                   WHERE p.is_active AND p.embedding_v2 IS NOT NULL""")
    store = dict(cur.fetchall())
    paths = build_category_paths(cur)
    cur.execute("SELECT product_id, category_id, hide FROM category_overrides")
    truth = {pid: (HIDDEN if hide else paths[cat]) for pid, cat, hide in cur.fetchall()}

    per_store = defaultdict(lambda: [0, 0, 0])   # checked, agree, unmapped label
    groups = Counter()
    examples = defaultdict(list)
    unmapped = Counter()
    for pid, path in now.items():
        s = per_store[store[pid]]
        label = (looks[pid] or "").lower().replace("’", "'")
        ok_leaves = label_to_leaves(label)
        if pid in truth:
            ok_leaves = {leaf_of(truth[pid])}
        if ok_leaves is None:
            s[2] += 1
            unmapped[label] += 1
            continue
        s[0] += 1
        if leaf_of(path) in ok_leaves:
            s[1] += 1
            continue
        if store[pid] in HOLDOUT:
            continue
        key = (leaf_of(path), label_key(label))
        groups[key] += 1
        examples[key].append(f"{titles[pid]}  [{store[pid]}]  (photo: {label})")

    def pct(a, n):
        return f"{100 * a / n:5.1f}%" if n else "  -  "

    seen = [v for k, v in per_store.items() if k not in HOLDOUT]
    held = [v for k, v in per_store.items() if k in HOLDOUT]
    sn, sa = sum(v[0] for v in seen), sum(v[1] for v in seen)
    hn, ha = sum(v[0] for v in held), sum(v[1] for v in held)
    rev_n = sum(1 for pid in truth if pid in now)
    rev_ok = sum(1 for pid, want in truth.items() if pid in now and now[pid] == want)
    print(f"Agree with photo  (rule-writing stores) {sa}/{sn} {pct(sa, sn)}")
    print(f"Agree with photo  (held-out stores)     {ha}/{hn} {pct(ha, hn)}")
    print(f"Reviewed products right                 {rev_ok}/{rev_n} {pct(rev_ok, rev_n)}")
    print(f"Uncategorised (in stock)                {sum(1 for v in now.values() if leaf_of(v) == 'Uncategorised')}")
    print(f"Photo label not understood by the check {sum(v[2] for v in per_store.values())}")
    print("\nPer store (agree with photo):")
    for st, (n, a, u) in sorted(per_store.items(), key=lambda x: x[1][1] / max(x[1][0], 1)):
        print(f"  {st:<16}{' (held out)' if st in HOLDOUT else '           '} {a:>5}/{n:<5} {pct(a, n)}")

    print(f"\nBiggest disagreements (rules say -> photo shows), rule-writing stores only:")
    shown = 0
    for (got, lab), n in groups.most_common():
        if args.group and args.group.lower() not in f"{got} {lab}".lower():
            continue
        print(f"  {n:>4}  {got:<22} -> {lab}")
        for e in examples[(got, lab)][:args.show]:
            print(f"          {e}")
        shown += 1
        if shown >= args.top:
            break

    if args.save:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        (SNAPSHOTS / f"{args.save}.json").write_text(json.dumps({str(k): v for k, v in now.items()}), encoding="utf-8")
        print(f"\nsaved snapshot {args.save}")
    if args.vs:
        old = {int(k): v for k, v in json.loads((SNAPSHOTS / f"{args.vs}.json").read_text(encoding="utf-8")).items()}
        moved = Counter()
        mex = defaultdict(list)
        for pid, path in now.items():
            if old.get(pid, path) != path:
                k = (old[pid], path)
                moved[k] += 1
                lab = looks[pid] or ""
                ok_leaves = label_to_leaves(lab.lower())
                verdict = "?" if ok_leaves is None else ("photo agrees" if leaf_of(path) in ok_leaves else
                                                         "WAS right" if leaf_of(old[pid]) in ok_leaves else "both wrong")
                mex[k].append(f"{titles[pid]}  [{store[pid]}]  (photo: {lab}; {verdict})")
        print(f"\nMoved since {args.vs}: {sum(moved.values())}")
        for (o, n_), c in moved.most_common():
            print(f"  {c:>4}  {o}  ->  {n_}")
            for e in mex[(o, n_)][:args.show]:
                print(f"          {e}")


def label_key(label):
    """Group photo labels by their garment noun so 'striped polo' and
    'knit polo shirt' land in one disagreement group."""
    h = head_match(label)
    return h[0].group(0).lower() if h else label


if __name__ == "__main__":
    main()
