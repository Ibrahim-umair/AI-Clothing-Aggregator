"""
Test run of the next enrichment call (spec agreed 2026-11-01) on a small,
mixed sample. Nothing is written to the products table: results go to
local-notes/enrich_v3_test/results.json and a review page is built from them
(export_enrich_v3_review.py).

What's new compared with enrich_products.py:
- ALL photos (up to 12), not 2.
- The store's text and our keyword category are hints; the model judges
  from the photos.
- Category picked from the full tree (confidence, or "none fits" + proposal).
- Gender/audience with confidence; colour versions + store colour mapping.
- Search descriptors: fit, dress level, season/warmth, embellishment,
  coverage, closure, activity, style, comfort, care. Ladders (search can
  exclude on them) vs open lists (only boost). Empty when not relevant.

Only products with at least one in-stock size AND at least one photo are
ever sent (no LLM call for anything else).

    python enrich_v3_test.py --pick 50          # choose the sample, no calls
    python enrich_v3_test.py --run              # call the LLM for the sample
"""
import argparse
import base64
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import psycopg2
from openai import OpenAI

from enrich_products import MODEL, PRICE_IN, PRICE_OUT, category_path, download, url_key
from load_data import DSN

MAX_PHOTOS = 12
OUT_DIR = Path(__file__).resolve().parent.parent / "local-notes" / "enrich_v3_test"
SAMPLE_FILE = OUT_DIR / "sample.json"
RESULTS_FILE = OUT_DIR / "results.json"

PALETTE = ["beige", "black", "blue", "brown", "camel", "charcoal", "cream", "gold", "green", "grey",
           "khaki", "lilac", "maroon", "mint", "multicolor", "mustard", "navy", "off white", "olive",
           "orange", "peach", "pink", "purple", "red", "rust", "silver", "sky blue", "teal",
           "turquoise", "white", "yellow"]

# Re-checked in round 2 after the prompt fixes: a Zellbury unstitched suit
# photographed stitched (no sizes), a tie (dress level), a Lama men's tee.
REGRESSION = [483665, 185608, 611652]

# Known hard cases from the 2026-11-01 search review and the colour plan.
MUST_INCLUDE = [
    174169,  # Cambridge Grey Aristo "Formal" shirt: all-over print, button-down collar
    155214,  # Charcoal Smart Shirt Blue: chest embroidery, button-down collar
    129818,  # Equator Navy Shady: two flap chest pockets
    106722,  # Edenrobe "Business Printed Formal Shirt"
    183014,  # Uniworth "Yellow Check Woven Boxer" (navy multicolour)
    124549,  # Equator "Yellow" casual shirt
    122714,  # One by One net top (sheerness)
]

# How many random products per group. Mostly clothing, a few of the rest.
GROUP_QUOTAS = [
    ("Men > Western > Upperwear", 6),
    ("Men > Western > Bottomwear", 3),
    ("Men > Western > Formalwear", 1),
    ("Men > Western > Suits & Sets", 1),
    ("Men > Eastern", 5),
    ("Women > Western", 7),
    ("Women > Eastern > Stitched", 7),
    ("Women > Eastern > Unstitched", 2),
    ("Boys", 2),
    ("Girls", 2),
    ("Footwear", 2),
    ("Accessories", 3),
    ("Fragrance", 1),
    ("Uncategorised", 1),
]

SYSTEM_PROMPT = """You describe clothing products for a Pakistani shopping search engine.
You get one product's numbered photos and the store's own text. Judge from the
photos. The store's title, description and our current category are hints that are
often wrong or exaggerated (a store may call a printed casual shirt "formal"); use
the text only for facts photos can't show (fabric content, care, piece count,
what is included).

GENERAL
- Describe only the item being sold, not the model or styling pieces.
- Never name a colour in description or tags (colours go only in "versions").
- No marketing language. Use the words a Pakistani shopper would use.

description: 2-3 plain sentences. Start with the garment type and its fit, then
length, sleeves, neckline/collar, prints/embroidery and where they sit, fabric look,
notable details.
tags: 8-10 short lowercase shopper phrases (type, design elements, style). Don't
repeat what the descriptors already say (fit, fabric, sleeves, closure).
looks_like: the garment type only, in 1-3 shopper words: no gender, age or piece
count, and it must agree with your category.

CATEGORY
Pick the most specific category from the CATEGORY TREE at the end. Each line is
"group: category, category, ..."; answer with the full path "group > category",
e.g. "Men > Western > Upperwear > Polo", using only combinations that are listed.
Style, fit, fabric or closure is never a reason for a new category.
- category.path: the full path, or "NONE" if nothing fits.
- category.proposed_new: only when path is "NONE": a short "Gender > ... > Name";
  otherwise "".
- category.confidence: high (clearly right), medium (another category also fits),
  low (guess). category.reason: one short line when medium or low; "" when high.
- Sets: two or more pieces sold together are a set, never one of the pieces.
- Open footwear (sandals, slides, chappals, peshawari) is Sandals, not Shoes.
- A plain shalwar/pajama sold to wear with a kurta is Eastern; a printed or
  matching sleep/lounge set is Nightwear.
- "Upper"/"Zipper"/"Pullover" are brand words: decide jacket, sweatshirt, hoodie or
  sweater from the photo.
- Unstitched fabric is Unstitched even if the photo shows a stitched example.
  Stores often photograph unstitched suits stitched on a model, so use the sizes:
  stitched clothes come in sizes (S/M/L, 38/40, 2-3Y); an Eastern suit with no
  garment sizes (none, one size, "unstitched", fabric lengths) is unstitched.

AUDIENCE
audience.value: judge from cut, fit and the model. Unisex only if it is truly
meant for both (many perfumes, sunglasses, caps, some tees). Kids only for
children's items that are for both boys and girls. audience.reason: one short
line when confidence is medium or low; "" when high.

NOT APPAREL
not_apparel: true for towels, bedding, candles, shoe care, skincare, makeup and
other non-wearables (perfume and accessories ARE apparel for us: false).

VERSIONS (colours)
- versions: one entry per distinct colour version the photos show.
  main_color: the colour covering most of the piece. secondary: colours that
  also cover a large part, each with share "equal" (about as much as the main
  colour: half-and-half, two-tone, equal colour-block or stripes) or "part" (big
  but clearly less: contrast sleeves, wide bands, panels); [] for a one-colour
  piece. details: small touches only, each with
  where it is (piping, buttons, trim, lining, logo, small print, embroidery,
  patch); they never make the piece "that colour". All colours from the allowed
  list. pattern: e.g. "solid", "stripes", "colour-block", "floral print".
  photos: the photo numbers showing that version.
- color_map: for every store colour name given, the index (0-based) of the version
  it matches, or -1 if you can't tell. Store colour names are often wrong; trust
  the photos.

DESCRIPTORS
Use "n/a", "" or [] for anything that doesn't apply. Underwear, socks, fragrance
and non-apparel have no dress level, embellishment or coverage. Nightwear and
loungewear are casual. Footwear and accessories DO get a dress level: they are
worn to occasions too (a tie, oxfords, a plain wool shawl or a leather belt can
be office or party; slides, sneakers and caps are casual; an embellished clutch
can be party or wedding).
The allowed values of the ladders (dress level, warmth, embellishment level,
sheerness) are fixed in the output format; this is what they mean:
- fit: slim, regular, relaxed, oversized, skinny, straight, wide leg, tapered,
  flared, bodycon, A-line, "not clear", or "n/a" (accessories, socks, perfume).
- dress_level: the occasions the piece suits, most casual to dressiest:
  casual (home, errands, outings), smart casual (dinner out, Jummah, casual
  office), office (work, meetings, presentations), party (evening events,
  dinners, mehndi/dholki guest), wedding (Eid, baraat, walima, festive).
  Use a range only when the piece really fits both ends (from = the more casual
  end); when unsure, from = to. Judge from the piece itself:
    Men: tee/hoodie/cargo/graphic = casual. Button-down collar, chest logo or
    embroidery, patch or flap pockets, bold or all-over prints, polo, chinos,
    plain or lightly embroidered kurta = smart casual. Plain or very fine
    pattern, point or spread collar, no logo, business suit = office. Dinner
    suit, tuxedo, statement blazer, embroidered kurta in a rich fabric = party.
    Sherwani, prince coat, heavily worked kurta or kurta-waistcoat set = wedding.
    Women: printed lawn, basic kurti, jeans tops = casual. Neat pret with light
    embroidery = smart casual. Simple elegant office pret = office. What
    Pakistani stores call "formal" (chiffon, organza, silk, rich embroidery) =
    party. Heavy formals, bridal and festive wear = wedding.
    Printed lawn or cotton and light embroidery never go above smart casual.
- warmth applies to all clothing and footwear; "n/a" only for perfume and
  non-apparel. From fabric weight: lawn, cambric, voile, linen, chiffon = light;
  cotton, denim, jersey = medium; khaddar, karandi, wool, fleece, velvet, quilted,
  padded = warm.
- embellishment.level: light = small areas (neckline, cuffs, a motif); medium =
  several areas or borders; heavy = most of the piece. embellishment.work: e.g.
  embroidery, sequins, mirror work, gota, lace, block print, digital print, screen
  print, beads.
- coverage: sleeves (sleeveless, cap, short, elbow, three-quarter, full); length
  (e.g. cropped, waist, hip, thigh, knee, midi, calf, ankle, floor); neckline (e.g.
  round, crew, V, deep V, square, boat, high, collar, band collar, mandarin,
  sweetheart, off-shoulder, halter); sheerness: can you see through it in the
  photos; slit (e.g. "side slits", "front slit", "none").
- closure: quarter-zip, half-zip, full-zip, zip-up hood, buttoned, pullover, wrap,
  tie.
- seasons: summer, mid-season, winter (several allowed). fabric: only if stated or
  clearly visible, e.g. "lawn", "khaddar", "cotton poplin", "linen", "denim",
  "wool blend".
- Open lists, several allowed, common shopper words: activities (e.g. everyday,
  office, gym, running, yoga, sports, swim, travel, lounge, sleep, party, wedding,
  eid, jummah, beach, outdoor); style (e.g. classic, minimal, streetwear, trendy,
  traditional, preppy, sporty, bohemian, elegant, edgy, vintage); comfort (e.g.
  stretch, soft, breathable, lightweight, cushioned, relaxed waistband,
  moisture-wicking); care, only if the text says it (e.g. wash & wear, non-iron,
  machine wash, dry clean only).

CATEGORY TREE
"""

SCHEMA_PROPS = {
    "description": {"type": "string"},
    "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
    "looks_like": {"type": "string"},
    "category": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "reason": {"type": "string"},
            "proposed_new": {"type": "string"},
        },
        "required": ["path", "confidence", "reason", "proposed_new"],
        "additionalProperties": False,
    },
    "audience": {
        "type": "object",
        "properties": {
            "value": {"type": "string", "enum": ["Men", "Women", "Unisex", "Boys", "Girls", "Kids"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "reason": {"type": "string"},
        },
        "required": ["value", "confidence", "reason"],
        "additionalProperties": False,
    },
    "not_apparel": {"type": "boolean"},
    "versions": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "main_color": {"$ref": "#/$defs/color"},
                # Big areas: these count when someone searches by colour.
                # "equal" ranks like the main colour in search, "part" lower.
                "secondary": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"color": {"$ref": "#/$defs/color"},
                                   "share": {"type": "string", "enum": ["equal", "part"]}},
                    "required": ["color", "share"], "additionalProperties": False}},
                # Small touches (piping, logo, embroidery...): never count as the
                # piece's colour, only searchable when asked for by name.
                "details": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"color": {"$ref": "#/$defs/color"}, "where": {"type": "string"}},
                    "required": ["color", "where"], "additionalProperties": False}},
                "pattern": {"type": "string"},
                "photos": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["main_color", "secondary", "details", "pattern", "photos"],
            "additionalProperties": False,
        },
    },
    "color_map": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"store_color": {"type": "string"}, "version": {"type": "integer"}},
            "required": ["store_color", "version"],
            "additionalProperties": False,
        },
    },
    "descriptors": {
        "type": "object",
        "properties": {
            "fit": {"type": "string"},
            "dress_level": {
                "type": "object",
                "properties": {
                    "from": {"type": "string", "enum": ["casual", "smart casual", "office", "party", "wedding", "n/a"]},
                    "to": {"type": "string", "enum": ["casual", "smart casual", "office", "party", "wedding", "n/a"]},
                },
                "required": ["from", "to"],
                "additionalProperties": False,
            },
            "warmth": {"type": "string", "enum": ["light", "medium", "warm", "n/a"]},
            "seasons": {"type": "array", "items": {"type": "string", "enum": ["summer", "mid-season", "winter"]}},
            "fabric": {"type": "string"},
            "embellishment": {
                "type": "object",
                "properties": {
                    "level": {"type": "string", "enum": ["plain", "printed", "light", "medium", "heavy", "n/a"]},
                    "work": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["level", "work"],
                "additionalProperties": False,
            },
            "coverage": {
                "type": "object",
                "properties": {
                    "sleeves": {"type": "string"},
                    "length": {"type": "string"},
                    "neckline": {"type": "string"},
                    "sheerness": {"type": "string", "enum": ["opaque", "lined", "semi-sheer", "sheer", "not clear", "n/a"]},
                    "slit": {"type": "string"},
                },
                "required": ["sleeves", "length", "neckline", "sheerness", "slit"],
                "additionalProperties": False,
            },
            "closure": {"type": "string"},
            "activities": {"type": "array", "items": {"type": "string"}},
            "style": {"type": "array", "items": {"type": "string"}},
            "comfort": {"type": "array", "items": {"type": "string"}},
            "care": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["fit", "dress_level", "warmth", "seasons", "fabric", "embellishment", "coverage",
                     "closure", "activities", "style", "comfort", "care"],
        "additionalProperties": False,
    },
}
SCHEMA = {
    "name": "product_enrichment_v3",
    "strict": True,
    "schema": {"type": "object", "properties": SCHEMA_PROPS, "required": list(SCHEMA_PROPS),
               "additionalProperties": False,
               # The colour list is stated once and referenced by main_color and accents.
               "$defs": {"color": {"type": "string", "enum": PALETTE}}},
}


def leaf_paths(cur):
    """Every category that has no children, as a full path: the tree the model picks from."""
    cur.execute("SELECT id FROM categories c WHERE NOT EXISTS (SELECT 1 FROM categories k WHERE k.parent_id = c.id)")
    return sorted(category_path(cur, r[0]) for r in cur.fetchall())


def grouped_tree(cur):
    """The same tree, one line per group ("Men > Western > Upperwear: Shirt, Polo, ...").
    Every gender keeps its own categories; it just stops repeating the group path on
    each line (~2,400 -> ~1,140 tokens)."""
    groups = {}
    for path in leaf_paths(cur):
        group, _, leaf = path.rpartition(" > ")
        groups.setdefault(group, []).append(leaf)
    return "\n".join(f"{g}: {', '.join(leaves)}" for g, leaves in groups.items())


SELLABLE = """p.is_active
  AND EXISTS (SELECT 1 FROM variants v WHERE v.product_id = p.id AND v.current_available)
  AND EXISTS (SELECT 1 FROM product_images i WHERE i.product_id = p.id)"""


NON_CLOTHING_RE = ("Accessories", "Fragrance", "Footwear")


def pick_by_category(cur, n, exclude, must, non_clothing=9, seed=20261102):
    """One product from each of n different categories: mostly clothing, a few
    footwear/accessories/fragrance, plus the `must` regression products."""
    cur.execute(f"SELECT p.id, p.category_id FROM products p WHERE {SELLABLE}")
    by_leaf = {}
    for pid, cid in cur.fetchall():
        if pid not in exclude:
            by_leaf.setdefault(category_path(cur, cid) if cid else "Uncategorised", []).append(pid)
    cur.execute(f"SELECT p.id, p.category_id FROM products p WHERE p.id = ANY(%s) AND {SELLABLE}", (must,))
    picked = cur.fetchall()
    used = {category_path(cur, cid) for _, cid in picked}
    ids = [pid for pid, _ in picked]
    rng = random.Random(seed)
    leaves = sorted(set(by_leaf) - used)
    rng.shuffle(leaves)
    other = [l for l in leaves if any(w in l for w in NON_CLOTHING_RE)][:non_clothing]
    clothing = [l for l in leaves if not any(w in l for w in NON_CLOTHING_RE)][:n - len(ids) - len(other)]
    for leaf in clothing + other:
        ids.append(rng.choice(by_leaf[leaf]))
    return ids


def pick_sample(cur, n):
    cur.execute(f"SELECT p.id, p.category_id FROM products p WHERE {SELLABLE}")
    by_group = {}
    for pid, cid in cur.fetchall():
        path = category_path(cur, cid) if cid else "Uncategorised"
        for prefix, _ in GROUP_QUOTAS:
            if prefix in path:
                by_group.setdefault(prefix, []).append(pid)
                break
    cur.execute(f"SELECT p.id FROM products p WHERE p.id = ANY(%s) AND {SELLABLE}", (MUST_INCLUDE,))
    ids = [r[0] for r in cur.fetchall()]
    missing = set(MUST_INCLUDE) - set(ids)
    if missing:
        print("skipped (sold out or no photo now):", sorted(missing))
    rng = random.Random(20261101)
    for prefix, quota in GROUP_QUOTAS:
        pool = [i for i in by_group.get(prefix, []) if i not in ids]
        ids += rng.sample(pool, min(quota, len(pool)))
    return ids[:n]


def load_product(cur, pid):
    cur.execute(
        """SELECT p.id, b.name, b.slug, b.base_url, p.handle, p.title, p.description, p.category_id,
                  array_to_string(p.tags, ', ')
           FROM products p JOIN brands b ON b.id = p.brand_id WHERE p.id = %s""", (pid,))
    _, brand, slug, base_url, handle, title, desc, cid, tags = cur.fetchone()
    cur.execute("SELECT url FROM product_images WHERE product_id = %s ORDER BY position", (pid,))
    photos, seen = [], set()
    for (url,) in cur.fetchall():
        if url_key(url) not in seen and len(photos) < MAX_PHOTOS:
            seen.add(url_key(url))
            photos.append(url)
    cur.execute("""SELECT co.canonical_name, bool_or(v.current_available)
                   FROM variants v JOIN colors co ON co.id = v.color_id
                   WHERE v.product_id = %s GROUP BY co.canonical_name ORDER BY 1""", (pid,))
    colors = [{"name": n, "in_stock": s} for n, s in cur.fetchall()]
    cur.execute("""SELECT size_label FROM variants WHERE product_id = %s AND size_label IS NOT NULL
                   GROUP BY size_label ORDER BY min(id)""", (pid,))
    sizes = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT 1 FROM category_overrides WHERE product_id = %s", (pid,))
    reviewed = cur.fetchone() is not None
    return {"id": pid, "brand": brand, "store": slug, "title": title, "description": desc or "",
            "tags": tags or "", "category": category_path(cur, cid) if cid else "Uncategorised",
            "reviewed": reviewed, "colors": colors, "sizes": sizes, "photos": photos,
            "url": f"{base_url}/products/{handle}" if handle else base_url}


def user_content(product, photos):
    colors = ", ".join(c["name"] for c in product["colors"]) or "(none given)"
    text = (f"Brand: {product['brand']}\nTitle: {product['title']}\n"
            f"Our current category (keyword rules, a hint only): {product['category']}\n"
            f"Store colour names: {colors}\n"
            f"Sizes: {', '.join(product.get('sizes') or []) or '(none)'}\n"
            f"Store tags: {product['tags'][:500] or '(none)'}\n"
            f"Store description: {product['description'][:1500] or '(none)'}")
    content = [{"type": "text", "text": text}]
    for n, (data, mime) in photos:
        content.append({"type": "text", "text": f"Photo {n}:"})
        content.append({"type": "image_url", "image_url": {
            "url": f"data:{mime};base64,{base64.b64encode(data).decode()}", "detail": "low"}})
    return content


CACHE_KEY = "libas-enrich-v3"


def request_body(system_prompt, product, photos):
    return {
        "model": MODEL, "reasoning_effort": "none",
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_content(product, photos)}],
        "response_format": {"type": "json_schema", "json_schema": SCHEMA},
        # Same key on every call routes them to the same cache, so the ~4,900
        # token prefix (rules + category tree) is billed at the cached rate.
        "prompt_cache_key": CACHE_KEY,
    }


def fetch_photos(product):
    photos = []
    for n, url in enumerate(product["photos"], 1):
        got = download(url)
        if got:
            photos.append((n, got))
    return photos


def usage_dict(u):
    """Token usage from an SDK object (sync) or a plain dict (batch output)."""
    if isinstance(u, dict):
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        return {"in": u["prompt_tokens"], "out": u["completion_tokens"], "cached": cached}
    return {"in": u.prompt_tokens, "out": u.completion_tokens,
            "cached": getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0}


def run_one(client, system_prompt, product):
    photos = fetch_photos(product)
    if not photos:
        return {"product": product, "error": "no photo could be downloaded"}
    t0 = time.time()
    resp = client.chat.completions.create(**request_body(system_prompt, product, photos))
    return {"product": product, "photos_sent": [n for n, _ in photos],
            "result": json.loads(resp.choices[0].message.content),
            "usage": usage_dict(resp.usage), "seconds": round(time.time() - t0, 1)}


def cost_line(results, batch):
    ok = [r for r in results if "usage" in r]
    tin = sum(r["usage"]["in"] for r in ok)
    tout = sum(r["usage"]["out"] for r in ok)
    cached = sum(r["usage"]["cached"] for r in ok)
    # Cached input assumed billed at a tenth of the input rate; Batch halves everything.
    cost = ((tin - cached) * PRICE_IN + cached * PRICE_IN / 10 + tout * PRICE_OUT) / 1e6
    if batch:
        cost /= 2
    per = cost / max(len(ok), 1)
    return (f"{len(ok)} results, {tin} in ({cached} cached, {100 * cached / max(tin, 1):.0f}%) / {tout} out, "
            f"~${cost:.4f} = ${per:.5f} per product, ~${per * 45693:.2f} for all 45,693 in-stock"
            + (" (batch price)" if batch else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="", help="file suffix, e.g. r2 (round 1 used none)")
    ap.add_argument("--pick", type=int, help="choose a sample of this size (no LLM calls)")
    ap.add_argument("--by-category", action="store_true", help="with --pick: one product per category")
    ap.add_argument("--run", action="store_true", help="call the LLM now for the chosen sample")
    ap.add_argument("--batch-submit", action="store_true", help="send the sample through the Batch API")
    ap.add_argument("--batch-collect", action="store_true", help="fetch the batch results when done")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sfx = f"_{args.round}" if args.round else ""
    sample_file, results_file = OUT_DIR / f"sample{sfx}.json", OUT_DIR / f"results{sfx}.json"
    batch_file = OUT_DIR / f"batch{sfx}.json"
    cur = psycopg2.connect(DSN).cursor()
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / "server" / ".env")

    if args.pick:
        if args.by_category:
            seen = set()  # never re-test a product from an earlier round
            for old in OUT_DIR.glob("sample*.json"):
                seen |= {p["id"] for p in json.loads(old.read_text(encoding="utf-8"))}
            ids = pick_by_category(cur, args.pick, seen, REGRESSION)
        else:
            ids = pick_sample(cur, args.pick)
        products = [load_product(cur, i) for i in ids]
        sample_file.write_text(json.dumps(products, indent=1, ensure_ascii=False), encoding="utf-8")
        for p in products:
            print(f"{p['id']:>7} {p['store']:<15} {len(p['photos']):>2} ph  {p['category'][:58]:<58} {p['title'][:38]}")
        print(f"{len(products)} products -> {sample_file}")

    system_prompt = SYSTEM_PROMPT + grouped_tree(cur)
    valid_paths = set(leaf_paths(cur))

    if args.run:
        products = json.loads(sample_file.read_text(encoding="utf-8"))
        client = OpenAI()
        results = []
        with ThreadPoolExecutor(args.workers) as ex:
            futs = [ex.submit(run_one, client, system_prompt, p) for p in products]
            for f in as_completed(futs):
                try:
                    results.append(f.result())
                except Exception as e:  # keep going; report at the end
                    print("ERROR", e, file=sys.stderr)
        order = {p["id"]: i for i, p in enumerate(products)}
        results.sort(key=lambda r: order[r["product"]["id"]])
        results_file.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
        print("done:", cost_line(results, batch=False))

    if args.batch_submit:
        products = json.loads(sample_file.read_text(encoding="utf-8"))
        lines, sent = [], {}
        for p in products:
            photos = fetch_photos(p)
            if not photos:
                print("no photo could be downloaded, skipped:", p["id"])
                continue
            sent[p["id"]] = [n for n, _ in photos]
            lines.append(json.dumps({"custom_id": str(p["id"]), "method": "POST", "url": "/v1/chat/completions",
                                     "body": request_body(system_prompt, p, photos)}))
        jsonl = OUT_DIR / f"batch{sfx}_input.jsonl"
        jsonl.write_text("\n".join(lines), encoding="utf-8")
        client = OpenAI()
        with open(jsonl, "rb") as fh:
            up = client.files.create(file=fh, purpose="batch")
        b = client.batches.create(input_file_id=up.id, endpoint="/v1/chat/completions", completion_window="24h")
        batch_file.write_text(json.dumps({"batch_id": b.id, "photos_sent": sent}), encoding="utf-8")
        print(f"submitted {len(lines)} requests ({jsonl.stat().st_size / 1e6:.1f} MB): {b.id}")

    if args.batch_collect:
        meta = json.loads(batch_file.read_text(encoding="utf-8"))
        client = OpenAI()
        b = client.batches.retrieve(meta["batch_id"])
        print("status:", b.status, b.request_counts)
        if b.status != "completed":
            return
        products = {p["id"]: p for p in json.loads(sample_file.read_text(encoding="utf-8"))}
        results = []
        for line in client.files.content(b.output_file_id).text.splitlines():
            row = json.loads(line)
            pid = int(row["custom_id"])
            body = (row.get("response") or {}).get("body") or {}
            if not body.get("choices"):
                results.append({"product": products[pid], "error": json.dumps(row.get("error") or body)[:300]})
                continue
            results.append({"product": products[pid], "photos_sent": meta["photos_sent"][str(pid)],
                            "result": json.loads(body["choices"][0]["message"]["content"]),
                            "usage": usage_dict(body["usage"])})
        order = {pid: i for i, pid in enumerate(products)}
        results.sort(key=lambda r: order[r["product"]["id"]])
        results_file.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
        print("done:", cost_line(results, batch=True))
        print("errors:", [r["error"] for r in results if "error" in r][:3])
        # The grouped tree makes the model assemble the path itself: check it exists.
        bad = [(r["product"]["id"], r["result"]["category"]["path"]) for r in results if "result" in r
               and r["result"]["category"]["path"] not in valid_paths | {"NONE"}]
        print("category paths not in the tree:", bad or "none")


if __name__ == "__main__":
    main()
