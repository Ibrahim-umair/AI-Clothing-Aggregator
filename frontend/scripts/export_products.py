"""
Export a diverse, real sample of products from products.db into a static
JSON file for the React frontend, applying a heuristic taxonomy bucketing
(Gender -> Branch [Eastern/Western/Accessories/Fragrance & Beauty] ->
Sub-branch -> Garment category) since the real classification pipeline
does not exist yet.

Color and Size are NOT heuristic: they are pulled per-product from the raw
scrape files (scraped_data/*.jsonl), matched by (store, product_id), since
products.db itself has no per-variant option data. See
build_raw_variant_index() / extract_options_from_pairs() below.

Run: python scripts/export_products.py
"""
import json
import random
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(r"C:\Work\scraping-init\scraped_data\products.db")
RAW_DATA_DIR = Path(r"C:\Work\scraping-init\scraped_data")
OUT_PATH = Path(__file__).resolve().parent.parent / "src" / "data" / "products.json"

random.seed(42)

STORES = [
    "outfitters", "furor", "edenrobe", "one_be-one", "equator", "meme",
    "breakout", "monark", "engine_clothing", "charcoal", "royal_tag",
    "diners", "cambridge", "uniworth", "cougar",
]

TARGET_TOTAL = 360
PER_STORE_AVAILABLE = 16
PER_STORE_UNAVAILABLE = 4

# ---------------------------------------------------------------------------
# Heuristic taxonomy
# ---------------------------------------------------------------------------

def word(pattern):
    return r"\b" + pattern + r"\b"

GENDER_RULES = [
    ("Boys", re.compile(word(r"boys?|junior boy|infant boy|baby boy|teen boy")) ),
    ("Girls", re.compile(word(r"girls?|junior girl|infant girl|baby girl|teen girl")) ),
    ("Unisex", re.compile(word(r"unisex|kids unisex")) ),
    ("Women", re.compile(word(r"wom[ae]n|ladies|lady|her\b")) ),
    ("Men", re.compile(word(r"men'?s?|gents?|him\b|\bd man\b")) ),
]

# A handful of stores in this dataset are (in reality) exclusively or
# overwhelmingly menswear/formal-wear brands whose product feeds rarely spell
# out "men" anywhere (e.g. Charcoal, Uniworth, Cambridge, Royal Tag, Equator,
# Monark). When no explicit gender keyword is found in a product's own text,
# fall back to the store's real-world dominant gender instead of a generic
# "Unisex" default so the taxonomy feels realistic.
STORE_GENDER_DEFAULT = {
    "equator": "Men",
    "monark": "Men",
    "charcoal": "Men",
    "royal_tag": "Men",
    "cambridge": "Men",
    "uniworth": "Men",
    "furor": "Men",
}

FRAGRANCE_RE = re.compile(r"perfume|fragrance|cologne|deodorant|\bedt\b|\bedp\b|attar|body spray|mist\b")

ACCESSORY_RE = re.compile(
    r"\bbelt|\btie\b|\bcap\b|caps\b|cufflink|sunglass|\bglasses\b|jewel|earring|"
    r"\bbracelet|\bbag\b|bags\b|wallet|\bscarf|scarves|stole|dupatta|shawl|"
    r"\bsock|watch\b|\bhat\b|beanie|necktie|brace(s)?\b"
)

UNSTITCHED_RE = re.compile(r"un[\s-]?stitched|unstitch")
SEMI_STITCHED_RE = re.compile(r"semi[\s-]?stitched|semi[\s-]?stitch")

EASTERN_RE = re.compile(
    r"kurta|shalwar|kameez|kurti|sherwani|eastern|lawn|khaddar|cambric|"
    r"viscose suit|3[\s-]?piece|2[\s-]?piece|1[\s-]?piece|suit length|"
    r"unstitched|semi[\s-]?stitched"
)

FOOTWEAR_RE = re.compile(r"shoe|sandal|slide|sneaker|loafer|footwear")
BOTTOMWEAR_RE = re.compile(
    r"trouser|jean|denim pant|\bpant(s)?\b|short(s)?\b|jogger|chino|track pant"
)
SUITS_SETS_RE = re.compile(
    r"blazer|waist ?coat|\bsuit(s)?\b(?!.*length)|co-?ord|frock|jumpsuit|"
    r"\bdress(es)?\b|combo suit|sherwani suit|3 piece stitched|2 piece stitched"
)

WESTERN_RE = re.compile(
    r"shirt|tee\b|t-shirt|polo|jacket|hoodie|sweatshirt|sweater|blouse|"
    r"\btop\b|tank|coat|western|denim|graphic tee|activewear"
)

# Level-3 garment categories -------------------------------------------------

EASTERN_CATEGORY_RULES = [
    ("Shalwar Kameez", re.compile(r"shalwar kameez|shalwar\s*kameez|kameez shalwar")),
    ("Kurta Set", re.compile(r"kurta shalwar|kurta pajama|kurta set")),
    ("Sherwani", re.compile(r"sherwani")),
    ("Kurti", re.compile(r"kurti")),
    ("3-Piece", re.compile(r"3[\s-]?piece")),
    ("2-Piece", re.compile(r"2[\s-]?piece")),
    ("1-Piece", re.compile(r"1[\s-]?piece")),
    ("Dupatta & Shawl", re.compile(r"dupatta|shawl|stole")),
    ("Waistcoat Suit", re.compile(r"waist ?coat")),
    ("Kurta", re.compile(r"kurta")),
    ("Unstitched Fabric", re.compile(r"unstitched|fabric")),
]

WESTERN_UPPER_CATEGORY_RULES = [
    ("Polo Shirt", re.compile(r"polo")),
    ("Graphic Tee", re.compile(r"graphic tee")),
    ("T-Shirt", re.compile(r"\btee\b|t-shirt|tank top")),
    ("Formal Shirt", re.compile(r"formal shirt|dress shirt")),
    ("Casual Shirt", re.compile(r"casual shirt")),
    ("Shirt", re.compile(r"shirt|blouse")),
    ("Hoodie", re.compile(r"hoodie")),
    ("Sweatshirt", re.compile(r"sweatshirt")),
    ("Sweater", re.compile(r"sweater|knitwear")),
    ("Jacket", re.compile(r"jacket|outerwear|long coat")),
    ("Top", re.compile(r"\btop\b|fashion top")),
]

WESTERN_BOTTOM_CATEGORY_RULES = [
    ("Jeans", re.compile(r"jean|denim")),
    ("Jogger", re.compile(r"jogger|track pant")),
    ("Chino", re.compile(r"chino")),
    ("Shorts", re.compile(r"short")),
    ("Trouser", re.compile(r"trouser|\bpant(s)?\b")),
]

WESTERN_SUITS_CATEGORY_RULES = [
    ("Blazer", re.compile(r"blazer")),
    ("Waistcoat Suit", re.compile(r"waist ?coat")),
    ("Co-ord Set", re.compile(r"co-?ord")),
    ("Dress", re.compile(r"dress|frock|jumpsuit")),
    ("Formal Suit", re.compile(r"suit")),
]

WESTERN_FOOTWEAR_CATEGORY_RULES = [
    ("Sandals", re.compile(r"sandal|slide")),
    ("Sneakers", re.compile(r"sneaker")),
    ("Shoes", re.compile(r"shoe|loafer|footwear")),
]

ACCESSORY_CATEGORY_RULES = [
    ("Belts", re.compile(r"belt")),
    ("Ties", re.compile(r"\btie\b|necktie")),
    ("Caps & Hats", re.compile(r"\bcap\b|caps\b|\bhat\b|beanie")),
    ("Cufflinks", re.compile(r"cufflink")),
    ("Sunglasses", re.compile(r"sunglass|\bglasses\b")),
    ("Jewellery", re.compile(r"jewel|earring|\bbracelet")),
    ("Bags", re.compile(r"\bbag\b|bags\b|wallet")),
    ("Scarves & Stoles", re.compile(r"scarf|scarves|stole|shawl|dupatta")),
    ("Socks", re.compile(r"\bsock")),
    ("Watches", re.compile(r"watch")),
]

FRAGRANCE_CATEGORY_RULES = [
    ("Deodorant", re.compile(r"deodorant|body spray")),
    ("Perfume", re.compile(r"perfume|fragrance|cologne|\bedt\b|\bedp\b|attar|mist")),
]

COLOR_WORDS = [
    "black", "white", "navy", "blue", "red", "maroon", "green", "olive",
    "khaki", "beige", "grey", "gray", "brown", "pink", "purple", "yellow",
    "orange", "teal", "mustard", "charcoal", "cream", "ivory", "rust",
    "burgundy", "mint", "lavender", "coral", "peach", "tan", "gold", "silver",
]

# ---------------------------------------------------------------------------
# Real per-product variant color/size extraction
#
# products.db only carries aggregated price/availability — it has no notion
# of a product's actual Color/Size options. Rather than guess sizes from
# which taxonomy category a product landed in (a mistake this project has
# already made and corrected once), we go back to the raw per-store scrape
# files (scraped_data/*.jsonl, one full raw Shopify product JSON per line)
# and pull each product's REAL options straight from its own data, matched
# by (store, product_id). 14 stores are REST format (p["options"] +
# p["variants"]); "cougar" is GraphQL (variants.edges[].node.selectedOptions).
# See build_db.py's normalize_rest / normalize_graphql for the same store-id
# matching convention used here.
# ---------------------------------------------------------------------------

PLACEHOLDER_VALUES = {"default title", "default", ""}

# Shopify's generic no-options placeholder is option name "Title". A few
# stores in this dataset repurpose that same name to actually carry size (or,
# rarely, color) values instead of leaving it as the placeholder. We only
# ever trust an option's OWN values (never its taxonomy bucket) to decide
# what it is.
SIZE_TOKENS = {
    "xxs", "xs", "s", "m", "l", "xl", "xxl", "2xl", "3xl", "4xl", "5xl",
    "xxxl", "free size", "one size",
}


def is_placeholder(value):
    if value is None:
        return True
    return str(value).strip().lower() in PLACEHOLDER_VALUES


def looks_like_size(value):
    v = value.strip()
    vl = v.lower()
    if vl in SIZE_TOKENS:
        return True
    # Purely numeric (waist/collar/shoe sizes: "30", "32", "40.5", "7-8")
    stripped = re.sub(r"[0-9\s\-–.]", "", v)
    if stripped == "":
        return True
    # Numeric + a couple of unit letters: "12Y", "9M-12M", "7-8 Y"
    if re.fullmatch(r"[A-Za-z]{1,3}", stripped) and any(ch.isdigit() for ch in v):
        return True
    return False


def looks_like_color(value):
    vl = value.strip().lower()
    return any(re.search(word(c), vl) for c in COLOR_WORDS)


def classify_ambiguous_option(values):
    """Decide whether a store's misused 'Title' option is really encoding
    size or color for THIS product, purely from its own real values. Returns
    'size', 'color', or None (skip — do not invent a label)."""
    real = [v for v in values if not is_placeholder(v)]
    if not real:
        return None
    if sum(1 for v in real if looks_like_size(v)) / len(real) >= 0.5:
        return "size"
    if sum(1 for v in real if looks_like_color(v)) / len(real) >= 0.5:
        return "color"
    return None


UNIT_SUFFIX_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]{1,3})$")


def normalize_label(value):
    v = value.strip()
    if not v:
        return v
    if v.lower() in SIZE_TOKENS and v.lower() not in ("free size", "one size"):
        return v.upper()
    m = UNIT_SUFFIX_RE.match(v)
    if m:
        # Numeric + unit (fragrance "50ml"/"100 ML", age sizes "12Y") — keep the
        # unit lowercase rather than blindly title-casing an all-caps value.
        return f"{m.group(1)}{m.group(2).lower()}"
    if v.isupper() and len(v) > 2:
        return v.title()
    return v


def dedup_preserve(values):
    seen, out = set(), []
    for v in values:
        key = v.lower()
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def variant_pairs_rest(p):
    """(option_name, value) pairs from a REST product's real `options` block —
    the store's own canonical option definitions, e.g.
    [{"name": "Color", "values": ["Mushroom", "Black"]}, {"name": "Size", ...}]."""
    pairs = []
    for opt in (p.get("options") or []):
        name = opt.get("name", "")
        for v in (opt.get("values") or []):
            pairs.append((name, v))
    return pairs


def variant_pairs_graphql(p):
    """(option_name, value) pairs from a GraphQL (cougar) product's real
    variants[].selectedOptions, deduplicated across variants by first
    appearance."""
    pairs = []
    for edge in (p.get("variants", {}) or {}).get("edges", []) or []:
        node = edge.get("node", {})
        for so in node.get("selectedOptions", []) or []:
            pairs.append((so.get("name", ""), so.get("value")))
    return pairs


def extract_options_from_pairs(pairs):
    """Turn a product's real (option_name, value) pairs into (colors, sizes) —
    de-duplicated, display-normalized values pulled only from THIS product's
    own data. Unrelated option axes (Fit, Fabric, Season, Gender, Material,
    ...) are ignored outright. A genuinely option-less product yields ([], [])
    truthfully rather than a guessed/fallback value."""
    color_values, size_values, title_values = [], [], []
    for name, value in pairs:
        if is_placeholder(value):
            continue
        n = (name or "").strip().lower()
        if "color" in n:
            color_values.append(value)
        elif "size" in n:
            size_values.append(value)
        elif n == "title":
            title_values.append(value)
        # else: ignore (Fit, Fabric, Season, Gender, Material, ...)

    if title_values:
        kind = classify_ambiguous_option(title_values)
        if kind == "size":
            size_values.extend(title_values)
        elif kind == "color":
            color_values.extend(title_values)

    colors = dedup_preserve([normalize_label(v) for v in color_values])
    sizes = dedup_preserve([normalize_label(v) for v in size_values])
    return colors, sizes


def build_raw_variant_index():
    """(store, product_id) -> (colors, sizes) for every product across all 15
    raw scrape files, extracted straight from each product's own real option
    data (see extract_options_from_pairs)."""
    index = {}
    for store in STORES:
        path = RAW_DATA_DIR / f"{store}.jsonl"
        if not path.exists():
            print(f"WARNING: raw scrape file missing for store '{store}': {path}")
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                p = json.loads(line)
                if store == "cougar":
                    product_id = p.get("id") or ""
                    pairs = variant_pairs_graphql(p)
                else:
                    product_id = str(p.get("id"))
                    pairs = variant_pairs_rest(p)
                index[(store, product_id)] = extract_options_from_pairs(pairs)
    return index


def match_rules(text, rules, default):
    for name, rx in rules:
        if rx.search(text):
            return name
    return default


def classify(product_type, title, tags, vendor="", store=""):
    text = " ".join([product_type or "", title or "", tags or "", vendor or ""]).lower()

    gender = None
    for name, rx in GENDER_RULES:
        if rx.search(text):
            gender = name
            break
    if gender is None:
        gender = STORE_GENDER_DEFAULT.get(store, "Unisex")

    if FRAGRANCE_RE.search(text):
        branch = "Fragrance & Beauty"
        sub = None
        category = match_rules(text, FRAGRANCE_CATEGORY_RULES, "Perfume")
    elif ACCESSORY_RE.search(text) and not WESTERN_RE.search(text):
        branch = "Accessories"
        sub = None
        category = match_rules(text, ACCESSORY_CATEGORY_RULES, "Accessories")
    elif EASTERN_RE.search(text) and not FOOTWEAR_RE.search(text):
        branch = "Eastern"
        if UNSTITCHED_RE.search(text):
            sub = "Unstitched"
        elif SEMI_STITCHED_RE.search(text):
            sub = "Semi-Stitched"
        else:
            sub = "Stitched"
        category = match_rules(text, EASTERN_CATEGORY_RULES, "Kurta")
    elif FOOTWEAR_RE.search(text):
        branch = "Western"
        sub = "Footwear"
        category = match_rules(text, WESTERN_FOOTWEAR_CATEGORY_RULES, "Shoes")
    elif SUITS_SETS_RE.search(text):
        branch = "Western"
        sub = "Suits & Sets"
        category = match_rules(text, WESTERN_SUITS_CATEGORY_RULES, "Formal Suit")
    elif BOTTOMWEAR_RE.search(text):
        branch = "Western"
        sub = "Bottomwear"
        category = match_rules(text, WESTERN_BOTTOM_CATEGORY_RULES, "Trouser")
    elif WESTERN_RE.search(text):
        branch = "Western"
        sub = "Upperwear"
        category = match_rules(text, WESTERN_UPPER_CATEGORY_RULES, "Shirt")
    elif ACCESSORY_RE.search(text):
        branch = "Accessories"
        sub = None
        category = match_rules(text, ACCESSORY_CATEGORY_RULES, "Accessories")
    else:
        # Fallback: treat as generic Western upperwear so it's still browsable
        branch = "Western"
        sub = "Upperwear"
        category = "Apparel"

    return gender, branch, sub, category


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    candidates = []
    for store in STORES:
        cur.execute(
            """
            SELECT * FROM products
            WHERE store = ? AND available = 1
              AND image_url IS NOT NULL AND image_url != ''
              AND title IS NOT NULL AND title != ''
            ORDER BY RANDOM() LIMIT ?
            """,
            (store, PER_STORE_AVAILABLE * 3),
        )
        avail_rows = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT * FROM products
            WHERE store = ? AND available = 0
              AND image_url IS NOT NULL AND image_url != ''
              AND title IS NOT NULL AND title != ''
            ORDER BY RANDOM() LIMIT ?
            """,
            (store, PER_STORE_UNAVAILABLE * 3),
        )
        unavail_rows = [dict(r) for r in cur.fetchall()]

        candidates.append((store, avail_rows, unavail_rows))

    # Classify everything first
    pool = []
    for store, avail_rows, unavail_rows in candidates:
        for r in avail_rows + unavail_rows:
            gender, branch, sub, category = classify(
                r["product_type"], r["title"], r["tags"], r["vendor"], r["store"]
            )
            r["_gender"] = gender
            r["_branch"] = branch
            r["_sub"] = sub
            r["_category"] = category
            pool.append(r)

    # Bucket by store to pick a diverse, category-spread final set per store
    by_store = defaultdict(list)
    for r in pool:
        by_store[r["store"]].append(r)

    final_rows = []
    for store in STORES:
        rows = by_store[store]
        avail = [r for r in rows if r["available"] == 1]
        unavail = [r for r in rows if r["available"] == 0]

        # Prefer spreading across distinct (branch, category) combos
        def diverse_pick(rows_in, n):
            random.shuffle(rows_in)
            seen_combo = defaultdict(int)
            chosen, leftover = [], []
            for r in rows_in:
                combo = (r["_branch"], r["_category"])
                if seen_combo[combo] < 2:
                    chosen.append(r)
                    seen_combo[combo] += 1
                else:
                    leftover.append(r)
                if len(chosen) >= n:
                    break
            if len(chosen) < n:
                chosen.extend(leftover[: n - len(chosen)])
            return chosen[:n]

        final_rows.extend(diverse_pick(avail, PER_STORE_AVAILABLE))
        final_rows.extend(diverse_pick(unavail, PER_STORE_UNAVAILABLE))

    # Ensure minimum coverage of smaller branches (Accessories / Fragrance & Beauty).
    # These are rare enough that the random per-store sample above often misses
    # them, so pull additional candidates directly from the DB across all stores.
    def ensure_min(branch_name, minimum, extra_where_sql):
        have_ids = {r["id"] for r in final_rows if r["_branch"] == branch_name}
        if len(have_ids) >= minimum:
            return
        need = minimum - len(have_ids)
        cur.execute(
            f"""
            SELECT * FROM products
            WHERE image_url IS NOT NULL AND image_url != ''
              AND title IS NOT NULL AND title != ''
              AND ({extra_where_sql})
            ORDER BY RANDOM() LIMIT ?
            """,
            (need * 6,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        # Prefer in-stock ones first
        rows.sort(key=lambda r: -r["available"])
        added = 0
        existing_ids = {r["id"] for r in final_rows}
        for r in rows:
            if added >= need:
                break
            if r["id"] in existing_ids:
                continue
            gender, branch, sub, category = classify(
                r["product_type"], r["title"], r["tags"], r["vendor"], r["store"]
            )
            if branch != branch_name:
                continue
            r["_gender"], r["_branch"], r["_sub"], r["_category"] = gender, branch, sub, category
            final_rows.append(r)
            existing_ids.add(r["id"])
            added += 1

    FRAGRANCE_SQL = (
        "lower(product_type) LIKE '%fragrance%' OR lower(product_type) LIKE '%perfume%' "
        "OR lower(title) LIKE '%perfume%' OR lower(title) LIKE '%cologne%' "
        "OR lower(title) LIKE '%fragrance%' OR lower(tags) LIKE '%fragrance%'"
    )
    ACCESSORY_SQL = (
        "lower(product_type) LIKE '%accessor%' OR lower(product_type) LIKE '%belt%' "
        "OR lower(product_type) LIKE '%tie%' OR lower(product_type) LIKE '%cap%' "
        "OR lower(product_type) LIKE '%cufflink%' OR lower(product_type) LIKE '%sunglass%' "
        "OR lower(product_type) LIKE '%jewel%' OR lower(product_type) LIKE '%bag%' "
        "OR lower(product_type) LIKE '%scarf%' OR lower(product_type) LIKE '%sock%'"
    )
    ensure_min("Fragrance & Beauty", 18, FRAGRANCE_SQL)
    ensure_min("Accessories", 28, ACCESSORY_SQL)

    # De-dup by product row identity (id) and cap total
    seen_ids = set()
    deduped = []
    for r in final_rows:
        if r["id"] in seen_ids:
            continue
        seen_ids.add(r["id"])
        deduped.append(r)

    random.shuffle(deduped)
    if len(deduped) > TARGET_TOTAL:
        # If we need to trim, protect the rarer branches (Accessories,
        # Fragrance & Beauty, Eastern) and trim from the abundant Western pile.
        rare = [r for r in deduped if r["_branch"] != "Western"]
        common = [r for r in deduped if r["_branch"] == "Western"]
        keep_common = max(0, TARGET_TOTAL - len(rare))
        deduped = rare + common[:keep_common]

    # Pull real per-product Color/Size options from the raw scrape files.
    print("Indexing real variant options from raw scrape files...")
    raw_variant_index = build_raw_variant_index()
    missing_variant_match = 0

    # Build final export objects
    out = []
    for r in deduped:
        try:
            images = json.loads(r["images_json"]) if r["images_json"] else []
        except (json.JSONDecodeError, TypeError):
            images = []
        if not images and r["image_url"]:
            images = [r["image_url"]]
        if not images:
            continue  # skip anything with no usable image

        tags_list = [t.strip() for t in (r["tags"] or "").split(",") if t.strip()]
        gender, branch, sub, category = r["_gender"], r["_branch"], r["_sub"], r["_category"]
        category_path = [gender, branch] + ([sub] if sub else []) + [category]

        variant_key = (r["store"], r["product_id"])
        if variant_key in raw_variant_index:
            colors, sizes = raw_variant_index[variant_key]
        else:
            missing_variant_match += 1
            print(f"WARNING: no raw variant match for store={r['store']} product_id={r['product_id']} title={r['title']!r}")
            colors, sizes = [], []

        out.append({
            "id": r["id"],
            "product_id": r["product_id"],
            "store": r["store"],
            "store_display": r["store_display"],
            "title": r["title"].strip(),
            "vendor": r["vendor"],
            "product_type": r["product_type"],
            "tags": tags_list,
            "price": r["price"],
            "compare_at_price": r["compare_at_price"] if r["compare_at_price"] and r["compare_at_price"] > (r["price"] or 0) else None,
            "currency": r["currency"] or "PKR",
            "available": bool(r["available"]),
            "image_url": images[0],
            "images": images,
            "description": (r["description"] or "").strip(),
            "handle": r["handle"],
            "product_url": r["product_url"],
            "variant_count": r["variant_count"],
            "gender": gender,
            "branch": branch,
            "sub_branch": sub,
            "category": category,
            "category_path": category_path,
            "colors": colors,
            "sizes": sizes,
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # Summary
    print(f"Exported {len(out)} products to {OUT_PATH}")
    by_gender = defaultdict(int)
    by_branch = defaultdict(int)
    by_store_count = defaultdict(int)
    no_color = no_size = neither = 0
    for p in out:
        by_gender[p["gender"]] += 1
        by_branch[p["branch"]] += 1
        by_store_count[p["store_display"]] += 1
        if not p["colors"]:
            no_color += 1
        if not p["sizes"]:
            no_size += 1
        if not p["colors"] and not p["sizes"]:
            neither += 1
    print("By gender:", dict(by_gender))
    print("By branch:", dict(by_branch))
    print("By store:", dict(by_store_count))
    print(f"Raw variant match misses: {missing_variant_match}")
    print(f"Products with no real color option: {no_color}")
    print(f"Products with no real size option: {no_size}")
    print(f"Products with neither: {neither}")


if __name__ == "__main__":
    main()
