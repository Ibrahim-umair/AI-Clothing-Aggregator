"""
Second pass over classify()'s answer for the Nov 2026 tree (see the "Nov 2026
tree" block in load_data.py). Written from the 15k-product audit of the
women's stores (eval_categorizer.py scores it).

Two parts:
  STORE_SIGNALS  what a store's own naming says (codes, lines, tags), one
                 table so every store-specific rule is in one place
  refine()       general rules: home/beauty, kids by size, stitched vs
                 unstitched, Eastern vs Western for Eastern-first brands,
                 the pieces sold together, men's sets, new types
"""
import re

ST, UN = "Stitched", "Unstitched"
TT, TD = "2-Piece (Shirt + Trouser)", "2-Piece (Shirt + Dupatta)"

# store -> [(field, pattern, what it means)]. field: title, type, tags, desc, any.
# Meanings: gender, stitch (stitched/unstitched), line (eastern/western),
# home, leaf (men's set).
STORE_SIGNALS = {
    "gul_ahmed": [
        ("any", r"\b(?:PK-)?(?:MN|FS|FP)-", {"gender": "Men"}),
        ("any", r"\b(?:PK-)?(?:WM|AW)-", {"gender": "Women", "line": "western"}),
        ("any", r"\b(?:PK-)?(?:KG|JG|TG)-", {"gender": "Girls"}),
        ("any", r"\b(?:PK-)?(?:KB|JB|TB)-", {"gender": "Boys"}),
        ("any", r"\b(?:PK-)?(?:IBS|IFS|IWW|IFA)-", {"gender": "Women"}),
        ("type", r"ideas home", {"home": True}),
        ("type", r"women fabric", {"stitch": UN, "gender": "Women"}),
        ("any", r"\b(?:PK-)?(?:IPST|IUSTTS|IPS|IUSTKSD)-?\d", {"line": "eastern"}),
        # men's "Suits": SK- and KP- codes both describe kameez shalwar
        ("any", r"\b(?:PK-)?(?:SK|KP)-", {"gender": "Men", "leaf": "Shalwar Kameez"}),
        ("any", r"\b(?:PK-)?FC-", {"gender": "Men"}),
        ("title", r"\bMN[A-Z]{3}", {"gender": "Men"}),
        ("any", r"\bPK-KWC-", {"gender": "Boys"}),
    ],
    "alkaram": [
        ("title", r"^\s*RTS\b", {"stitch": UN, "line": "eastern"}),
        ("title", r"^\s*RTW\b", {"stitch": ST}),
        ("title", r"^\s*HOME\b", {"home": True}),
    ],
    "nishat_linen": [
        ("type", r"pack suit|\bmeter\b", {"stitch": UN}),
        ("any", r"\bU[1-4](?:P|ST|PC)\b|-U[1-4]P-", {"stitch": UN}),
        ("any", r"\bNaqsh\b", {"gender": "Men"}),
    ],
    "junaid_jamshed": [
        ("tags", r"boys&girls-(?:\w+-)?(?:teen|kid|infant)girls", {"gender": "Girls"}),
        ("tags", r"boys&girls-(?:\w+-)?(?:teen|kid|infant)boys", {"gender": "Boys"}),
        ("tags", r"\bsyncc", {"line": "western"}),
        ("any", r"\bJ(?:LU|SU)-", {"stitch": UN}),
    ],
    "maria_b": [
        ("type", r"^kidsclothes$", {"gender": "Girls"}),
        ("type", r"^kidswear", {"gender": "Boys"}),
        ("type", r"loose fabrics?|^fabrics?$", {"stitch": UN}),
        # bridal sold by design name only ("Zarin"): mostly lehengas
        ("type", r"wedding wear|couture", {"gender": "Women", "line": "eastern", "unknown_leaf": "Lehenga"}),
    ],
    "ethnic": [
        ("tags", r"\bwomen-eastern\b", {"line": "eastern"}),
        ("tags", r"women-western|co-ord sets western", {"line": "western"}),
        # article code E1234/103/…: 10x women's Eastern, 11x-12x women's Western, 3xx-4xx kids (girls)
        ("title", r"E\d{3,4}[/-]10\d[/-]", {"line": "eastern"}),
        ("title", r"E\d{3,4}[/-]1[12]\d[/-]", {"line": "western"}),
        ("title", r"E\d{3,4}[/-][34]\d\d[/-]", {"gender": "Girls"}),
    ],
    "limelight": [
        ("tags", r"eastern bottoms", {"line": "eastern"}),
        ("tags", r"co-ords \(west\)", {"line": "western"}),
        ("title", r"\(pret\)", {"line": "eastern"}),
        ("tags", r"\bwestern\b", {"line": "western"}),
    ],
    "sapphire": [
        ("desc", r"^\s*unstitched", {"stitch": UN}),
        ("type", r"\bwest\b", {"line": "western"}),
    ],
    "khaadi": [
        ("title", r"^\s*fabrics?\b", {"stitch": UN}),
        ("type", r"casuals|urban off.duty", {"line": "western"}),
    ],
    "bonanza_satrangi": [
        ("any", r"\bWU\d?P", {"stitch": UN, "gender": "Women"}),
        ("any", r"\bWP\d?P", {"stitch": ST, "gender": "Women"}),
    ],
}
# Brands whose women's pret is Eastern unless the item says otherwise: a
# plain "trouser", "shirt" or "co-ord set" from them is Eastern.
EASTERN_FIRST = {"khaadi", "sapphire", "junaid_jamshed", "gul_ahmed", "bonanza_satrangi", "maria_b", "ethnic",
                 "limelight", "nishat_linen", "alkaram", "beechtree", "zellbury", "edenrobe"}

WESTERN_WORDS = re.compile(r"\b(?:jeans?|denim|cargo|joggers?|sweatpants|leggings?|jeggings?|shorts|skirts?|blazers?|"
                           r"hoodies?|sweatshirts?|t-?shirts?|tees?|polos?|jackets?|coats?|cardigans?|sweaters?|"
                           r"button[- ]?downs?|oxford|western|tank|crop top|tunics?|knit)\b", re.I)
EASTERN_FABRIC = re.compile(r"\b(?:lawn|cambric|khaddar|karandi|raw silk|slub|jacquard|dobby|chikankari|zari|"
                            r"banarsi|organza|chiffon|marina|pret|kurt[ai]s?|shalwar|kameez|dupatta|eastern)\b", re.I)
UNSTITCHED_WORDS = re.compile(r"un[\s-]?stitched|ready[\s-]?to[\s-]?stitch|\bfabrics?\b(?!ation)|\bmeters?\b", re.I)
KIDS_SIZE = re.compile(r"^\s*(?:\d{1,2}\s*(?:-|to)\s*\d{1,2}\s*(?:y|yrs?|years?|m|months?)|\d{1,2}\s*(?:y|yrs?|years?)|"
                       r"\d{1,2}\s*-\s*\d{1,2}\s*m)\b", re.I)
GIRL_WORDS = re.compile(r"\b(?:girls?|her|she|daughter|princess|frock)\b", re.I)
BOY_WORDS = re.compile(r"\b(?:boys?|his|he|son|gentleman)\b", re.I)
KIDS_TITLE = re.compile(r"\b(?:for kids|kids?|girls?|boys?|toddlers?|infants?|bab(?:y|ies)|juniors?|teens?|little)\b", re.I)
ADULT_MEN = re.compile(r"\bfor men\b|\bmen'?s\b|\bmens\b|\bgents\b|(?:^|\|\s*|,\s*)men\s*(?:,|\||$)", re.I)
# Boys' garments: a kids' kurta pajama with no gender word is a boy's.
BOYS_GARMENT = re.compile(r"kurta\s*(?:&|and)?\s*(?:pajama|pyjama|shalwar|trouser)|kameez\s*shalwar|shalwar\s*kameez|"
                          r"sherwani|waistcoat|jubba|prince\s*coat", re.I)
WOMEN_WORDS = re.compile(r"\b(?:wom[ae]n|ladies|girls?|mom|mother)\b", re.I)
# Words that make a product Eastern by themselves, whatever the store: Western clothes
# are never sold as "stitched", "2 piece (shirt/trouser)", lawn or khaddar.
# ("3 piece" alone isn't: a Western suit is a 3-piece too; nor is "frock": it can be a Western dress.)
EASTERN_STRONG = re.compile(r"\b(?:kurt[ai]s?|kameez|shalwar|salwar|dupatta|un-?stitched|stitched|"
                            r"shirt\s*/\s*(?:trouser|dupatta)|pret|lawn|khaddar|karandi|cambric|chikankari|"
                            r"angrakha|p[ei]shwas|gharara|sharara|wash\s*(?:n|&|and)\s*wear)\b", re.I)

DUP = re.compile(r"\b(?:dupatt?as?|shawls?|stoles?)\b", re.I)
BOT = re.compile(r"\b(?:shalwars?|salwars?|trousers?|pajamas?|pyjamas?|pants?|culottes?|tights|sharara|gharara|"
                 r"capris?|bottoms?|palazzo)\b", re.I)
INNER = re.compile(r"\b(?:inners?|slips?|linings?)\b", re.I)
COUNT = re.compile(r"\b([1-4])\s*-?\s*(?:pcs?|pieces?|p)\b|\b(one|two|three|four)[\s-]?pieces?\b", re.I)
WORD_N = {"one": 1, "two": 2, "three": 3, "four": 4}

HOME = [("Bedding", r"bed ?sheets?|fitted sheet|sheet set|quilt|comforter|duvet|bed in a bag|pillow|blanket|throw|"
                    r"bed ?spread|mattress|bed set|neck roll|fleece"),
        ("Cushions", r"cushion|euro sham|\bshams?\b"),
        ("Table & Kitchen", r"place ?mats?|runner|platter|\bplates?\b|\bdish|\bmugs?\b|\bcups?\b|bowls?|napkin|"
                            r"\btable|trays?\b|coaster|multipurpose mat|apron"),
        ("Curtains & Rugs", r"curtain|\brugs?\b|prayer mat|carpet|janamaz"),
        ("Bath", r"towel|\bbath"),
        ("Home Fragrance", r"diffuser|candle|room (?:spray|freshener)|bakhoor|reed")]
BEAUTY_TYPE = re.compile(r"beauty|cosmetic|skin ?care|make ?up", re.I)
MAKEUP = re.compile(r"\b(?:lip\w*|eye\w*|brows?|mascara|foundation|contour|palette|blush|nail|kajal|highlighter|"
                    r"concealer|powder|primer|fixing spray|perfecting pen|balm|bronzer)\b", re.I)
SKINCARE = re.compile(r"serum|cream|cleans|face ?wash|toner|moistur|sunscreen|lotion|mask|scrub|\boils?\b|shower gel|"
                      r"body wash|soap", re.I)
NOT_A_PRODUCT = re.compile(r"^\s*gift box\s*$|payment link|^\s*(?:multi )?envelopes?\s*$|gift wrap|packaging", re.I)
GARMENT = re.compile(r"\b(?:shirt|kurta|kameez|suit|dress|trouser|dupatta|shawl|fabric|unstitched|stitched)\b", re.I)


def _signals(store, title, ptype, tags, desc):
    out = {}
    fields = {"title": title, "type": ptype, "tags": tags, "desc": desc, "any": f"{title} | {ptype} | {tags} | {desc}"}
    for field, pattern, meaning in STORE_SIGNALS.get(store, []):
        if re.search(pattern, fields[field] or "", re.I):
            for k, v in meaning.items():
                out.setdefault(k, v)
    return out


WHOLE_COUNT = re.compile(r"(?:\b(?:un)?stitched\s*|\b)([1-4])\s*-?\s*(?:pcs?|pieces?)\s*(?:suit|set|outfit|dress|ensemble)\b|"
                         r"\b(?:un)?stitched\s*([1-4])\s*-?\s*(?:pcs?|pieces?)\b", re.I)


def _whole_count(text):
    m = WHOLE_COUNT.search(text)
    return int(m.group(1) or m.group(2)) if m else None


def _piece_count(text):
    m = COUNT.search(text)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else WORD_N[m.group(2).lower()]


def pieces_leaf(texts, unstitched=False):
    """The pieces sold together, from the first text that names them (title, then description)."""
    texts = [t for t in texts if t]
    # The count: the title's, else a description's count of the whole product.
    n = next((c for c in [_piece_count(texts[0]) if texts else None] + [_whole_count(t) for t in texts[1:]] if c), None)
    dup = bot = inner = False
    for text in texts:  # which pieces: the first text that names any
        dup, bot, inner = bool(DUP.search(text)), bool(BOT.search(text)), bool(INNER.search(text))
        if dup or bot:
            break
    shirt = any(re.search(r"\bshirt|kurt|kameez|top\b|co-?ord|suit|\bset\b", t, re.I) for t in texts)
    if unstitched and (n == 4 or n is None and inner and dup and bot):
        return "4-Piece"
    if n in (3, 4) or n is None and dup and bot:
        return "3-Piece"
    if n == 1:
        return "1-Piece"
    if n == 2:
        return TD if dup and not bot else TT
    if dup and shirt:
        return TD
    if bot and shirt:
        return TT
    return None


def _variants(p):
    """Variant dicts from a stored product (Shopify REST list; GraphQL stores keep {"edges": [{"node": ...}]})."""
    v = (p or {}).get("variants") or []
    if isinstance(v, dict):
        v = [e.get("node", e) for e in v.get("edges") or v.get("nodes") or []]
    return [x for x in v if isinstance(x, dict)]


def _stock_pieces(p):
    """Maria B style fabric: the variants are the pieces (Shirt / Dupatta / Trouser), each with its own stock."""
    variants = _variants(p)
    names = [(v.get("title") or "", v.get("available", True)) for v in variants]
    if not names or not all(re.search(r"shirt|front|back|sleeve|dupatta|trouser|shalwar", n, re.I) for n, _ in names):
        return None
    have = [n for n, ok in names if ok]
    if not any(re.search(r"shirt|front|back|sleeve", n, re.I) for n in have):
        return 0
    dup = any(re.search(r"dupatta", n, re.I) for n in have)
    bot = any(re.search(r"trouser|shalwar", n, re.I) for n in have)
    return "3-Piece" if dup and bot else TD if dup else TT if bot else "1-Piece"


def _sizes(p):
    return [v.get("title") or v.get("option1") or "" for v in _variants(p)]


FALLBACK = [  # an item the old rules couldn't place, by its own name
    (r"\b(?:rings?|studs?|hoops?|dangles?|drops|earrings?|jhumkas?|bangles?|bracelets?|anklets?|necklaces?|"
     r"pendants?|chokers?|tikkas?|nath|matha ?patti|jewell?e?ry|kara|tassels?|huggies|cuffs?)\b", ("Accessories", None, "Jewelry")),
    (r"\bhair\b|scrunchies?|catchers?|\bclips?\b|claw|headbands?|hair ?bands?", ("Accessories", None, "Hair Accessories")),
    (r"\b(?:totes?|clutch(?:es)?|pouch(?:es)?|potli|handbags?|bags?|purses?)\b", ("Accessories", None, "Bag")),
    (r"\bwallets?\b|card ?holders?", ("Accessories", None, "Wallet")),
    (r"\b(?:kolhapuris?|khola ?puris?|khussas?|chappals?|slides|sandals?|slippers?|flip ?flops?)\b", ("Western", "Footwear", "Sandals")),
    (r"\b(?:pumps|heels?|sneakers?|skechers?|slingbacks?|loafers?|shoes?|mules|flats|courts?|moccasins?)\b",
     ("Western", "Footwear", "Shoes")),
    (r"\b(?:t-?shirts?|tees?)\b", ("Western", "Upperwear", "T-Shirt")),
    (r"\btops?\b", ("Western", "Upperwear", "Top")),
    (r"\b(?:sweaters?|cardigans?|pullovers?|jumpers?)\b", ("Western", "Upperwear", "Sweater")),
    (r"\b(?:boxers?|briefs?|vests?|undershirts?)\b", ("Accessories", None, "Underwear")),
]


def _fallback(cls, title, tags, unknown_leaf):
    """The title first, then the store's tags ("Women Shoes", "PK-T-Shirt ...")."""
    for text in (title, tags):
        got = _fallback_leaf(cls, text)
        if got:
            return got
    if unknown_leaf:
        return _eastern(cls, cls["gender"], ST, unknown_leaf)
    return cls


def _fallback_leaf(cls, text):
    for rx, (branch, sub, leaf) in FALLBACK:
        if re.search(rx, text, re.I):
            if leaf == "Top" and cls["gender"] in ("Men", "Boys"):
                leaf = "T-Shirt"
            return _set(cls, branch=branch, sub=sub, leaf=leaf,
                        style="not_applicable" if branch == "Accessories" else "western")
    return None


KEEP = object()


def _set(cls, gender=None, branch=None, sub=KEEP, leaf=None, style=None, construction=None, **extra):
    """A copy of cls with the given fields changed (sub=None really clears the sub-group)."""
    cls = dict(cls)
    for k, v in (("gender", gender), ("branch", branch), ("leaf", leaf), ("style", style), ("construction", construction)):
        if v is not None:
            cls[k] = v
    if sub is not KEEP:
        cls["sub"] = sub
    cls.update(extra)
    return cls


def _eastern(cls, gender, sub, leaf):
    return _set(cls, gender=gender, branch="Eastern", sub=sub, leaf=leaf, style="eastern",
                construction="unstitched_fabric" if sub == UN else "ready_to_wear")


def refine(store, p, cls, title, ptype, tags, desc):
    title, ptype, tags, desc = title or "", ptype or "", tags or "", (desc or "")[:700]
    sig = _signals(store, title, ptype, tags, desc)
    name_blob = f"{title} {ptype}"

    # Not clothing: home goods and beauty kept under their own groups, hidden from search.
    if NOT_A_PRODUCT.search(title) and not GARMENT.search(title):
        return None
    if sig.get("home") or re.search(r"\bhome\b", ptype, re.I) or (cls is None and any(
            re.search(rx, title, re.I) for _, rx in HOME)):
        for leaf, rx in HOME:
            if re.search(rx, title, re.I):
                return dict(gender="Unisex", branch="Home", sub=None, leaf=leaf, style="not_applicable",
                            construction="not_applicable", browsable=False)
        if sig.get("home") or re.search(r"\bhome\b", ptype, re.I):
            return dict(gender="Unisex", branch="Home", sub=None, leaf=None, style="not_applicable",
                        construction="not_applicable", browsable=False)
    if BEAUTY_TYPE.search(ptype) or (cls is None and (MAKEUP.search(title) or SKINCARE.search(title))):
        leaf = "Skincare" if SKINCARE.search(title) and not MAKEUP.search(title) else "Makeup"
        if not re.search(r"fragrance|perfume|eau de|attar|mist", name_blob, re.I):
            g = cls["gender"] if cls and cls["gender"] in ("Men", "Women") else "Women"
            return dict(gender=g, branch="Fragrance & Beauty", sub=None, leaf=leaf, style="not_applicable",
                        construction="not_applicable", browsable=False)
    if cls is None:
        return None

    tl = title.lower()
    if cls["branch"] == "Uncategorised" or not cls["leaf"]:
        if sig.get("gender") and cls["gender"] == "Unisex":
            cls = _set(cls, gender=sig["gender"])
        cls = _fallback(cls, title, tags, sig.get("unknown_leaf"))
    if (cls["branch"] == "Uncategorised" or not cls["leaf"]) and cls["gender"] in ("Women", "Girls", "Unisex") \
            and re.search(r"\bshirt\b", desc, re.I):
        # A title that is only a code and a fabric ("UE-605 Embroidered Lawn"): the description lists the pieces.
        sizes_now = _sizes(p)
        garment_sizes = any(re.search(r"\b(?:xxs|xs|s|m|l|xl|xxl|small|medium|large|\d{2})\b", x, re.I) for x in sizes_now)
        fabric_sold = any(re.fullmatch(r"\s*unstitched\s*", x, re.I) for x in sizes_now) or (
            not garment_sizes and re.search(r"\b(?:meters?|metres?|yards?|yds)\b|\d(?:\.\d+)?\s*m\b", desc, re.I))
        got = pieces_leaf([desc], bool(fabric_sold))
        if got:
            cls = _eastern(cls, "Women" if cls["gender"] == "Unisex" else cls["gender"], UN if fabric_sold else ST, got)
    g, branch, sub, leaf = cls["gender"], cls["branch"], cls.get("sub"), cls["leaf"]

    # Gender: the store's own codes, then the product's own words, then kids sizes.
    eastern_words = bool(EASTERN_STRONG.search(f"{title} {ptype}"))
    if sig.get("gender") and not (sig["gender"] in ("Men", "Women") and g in ("Boys", "Girls")):
        g = sig["gender"]
    elif g in ("Women", "Unisex") and ADULT_MEN.search(f"{title} | {ptype} | {tags}") and not WOMEN_WORDS.search(title):
        g = "Men"  # "For Men", a "Mens" tag: beats a women's store's default
    sizes = _sizes(p)
    kid_sizes = bool(sizes) and sum(bool(KIDS_SIZE.search(s)) for s in sizes) >= max(1, len(sizes) // 2)
    if g in ("Women", "Men", "Unisex") and not re.search(r"\b(?:wom[ae]n|ladies|men)\b", tl) and (
            kid_sizes or KIDS_TITLE.search(title)):
        kid_text = f"{title} {tags} {desc}"
        girl, boy = bool(GIRL_WORDS.search(kid_text)), bool(BOY_WORDS.search(kid_text))
        if g == "Men" or boy and not girl or not girl and BOYS_GARMENT.search(title):
            g = "Boys"
        elif g == "Women" or girl and not boy or branch == "Eastern" or eastern_words or EASTERN_FABRIC.search(title):
            g = "Girls"  # kids' Eastern clothes that don't say boy are girls' (boys' say "For Boys")
    if g in ("Unisex", "Boys", "Girls") and branch == "Eastern" and re.search(r"\bwom[ae]n\b|\bladies\b", f"{ptype} {tags}", re.I) \
            and not sig.get("gender") and g == "Unisex":
        g = "Women"
    if leaf == "Perfume" and re.search(r"\bunisex\b", f"{title} {desc[:300]}", re.I):
        g = "Unisex"
    cls = _set(cls, gender=g)

    # New types with their own leaf.
    if re.search(r"\bhijabs?\b", tl):
        return _set(cls, gender="Women", branch="Accessories", sub=None, leaf="Hijab", style="not_applicable")
    if re.search(r"\b(?:kaftans?|caftans?|jalabiy?as?)\b", tl) and g in ("Women", "Unisex", "Girls") and "abaya" not in tl:
        return _eastern(cls, "Women" if g == "Unisex" else g, ST, "Kaftan") if g != "Girls" else cls
    if re.search(r"\bjubbas?\b", tl):
        return _eastern(cls, g if g in ("Men", "Boys") else "Men", ST, "Jubba")
    if re.search(r"\b(?:capes?|ponchos?)\b", tl) and g in ("Women", "Unisex") and not re.search(
            r"sleeve|sweater|coat|dress|hoodie|\btop|jacket|shirt|kurt|blouse", tl):
        return _set(cls, gender="Women", branch="Accessories", sub=None, leaf="Cape", style="not_applicable")
    if re.search(r"\bshrugs?\b", tl):
        return _set(cls, branch="Western", sub="Upperwear", leaf="Sweater", style="western")
    if leaf == "Underwear" and re.search(r"\b(?:sweaters?|cardigans?|pullovers?)\b", tl):
        return _set(cls, branch="Western", sub="Upperwear", leaf="Sweater", style="western")

    eastern_first = store in EASTERN_FIRST
    line = sig.get("line")
    unstitched = sig.get("stitch") == UN or bool(UNSTITCHED_WORDS.search(name_blob)) or sub == UN
    if sig.get("stitch") == ST:
        unstitched = bool(re.search(r"un[\s-]?stitched", name_blob, re.I))

    # Men and boys: sets are Shalwar Kameez or Kurta Trouser; RTS fabric is unstitched.
    if g in ("Men", "Boys", "Unisex"):
        if unstitched and (branch == "Eastern" or leaf in ("Gift Set", "Formal Suit") or sig.get("stitch") == UN) \
                and g != "Unisex" and not re.search(r"shawl|scarf|dupatta", tl):
            return _eastern(cls, g, UN, "Suit")
        if sig.get("leaf") and (branch == "Eastern" or leaf == "Formal Suit"):
            return _eastern(cls, g, ST, sig["leaf"])
        if branch == "Eastern" and sub == ST or leaf == "Formal Suit" and eastern_first and not re.search(
                r"blazer|tuxedo|coat|2[\s-]?piece|3[\s-]?piece|jacket", tl):
            kurta_trouser = r"kurta\s*(?:&|and|with|\+)?\s*(?:trousers?|pajamas?|pyjamas?|pants?)"
            if re.search(kurta_trouser, tl) or leaf == "Kurta Set" and (
                    re.search(r"trouser|pajama|pyjama|pant", tl) or re.search(kurta_trouser, desc, re.I)):
                return _eastern(cls, g, ST, "Kurta Trouser")
            if leaf in ("Kurta Set", "Formal Suit") or re.search(r"kurta\s*(?:&|and)?\s*shalwar|kameez|\bsuits?\b", tl) \
                    and leaf == "Kurta":
                return _eastern(cls, g, ST, "Shalwar Kameez")
        if g in ("Men", "Boys") and branch == "Western" and leaf in ("Co-ord Set", "Formal Suit") and eastern_words \
                and not WESTERN_WORDS.search(title):
            if unstitched:
                return _eastern(cls, g, UN, "Suit")
            shalwar = re.search(r"\bshalwar|\bsalwar", f"{title} {tags} {desc}", re.I)
            return _eastern(cls, g, ST, "Shalwar Kameez" if shalwar else "Kurta Trouser")
        if g in ("Men", "Boys") and branch == "Western" and leaf == "Trouser" and re.search(
                r"dress pants?|formal (?:pants?|trousers?)", tl):
            return _set(cls, sub="Formalwear", leaf="Dress Pants")
        return cls

    if g not in ("Women", "Girls"):
        return cls

    # Women and girls.
    if re.search(r"\babayas?\b", tl) and leaf in ("Scarf", "Shawl"):
        return _eastern(cls, g, ST, "Abaya")
    if re.search(r"\bsarees?\b|\bsaris?\b", tl) and g == "Women":
        return _eastern(cls, g, UN if unstitched else ST, "Saree")
    if re.search(r"\b(?:slips?|inners?)\b", tl) and not re.search(r"slip[\s-]?on|slipper", tl) and branch != "Accessories" \
            and not BOT.search(tl) and not re.search(r"shirt|kurt|suit|dress", tl):
        return _eastern(cls, g, ST, "Slip / Inner")

    # Eastern or Western: the product's own words first; the brand's usual line only
    # settles a plain "pants" with an Eastern fabric and nothing else to go on.
    western = line == "western" or (WESTERN_WORDS.search(title) and line != "eastern")
    evidence = bool(EASTERN_FABRIC.search(f"{title} {tags} {desc[:200]}"))
    eastern = line == "eastern" or not western and (
        eastern_words or evidence and (eastern_first or leaf == "Trouser") or eastern_first and leaf == "Trouser")
    if g == "Girls" and line != "eastern" and not (eastern_words or EASTERN_FABRIC.search(title) or
                                                   re.search(r"shalwar|pajama|kurt|kameez|\bsuit\b", tl)):
        eastern = False

    # Things the old rules filed Western that the product's words say are Eastern.
    if branch == "Western" and eastern and not western:
        if leaf == "Trouser" and not re.search(r"\b(?:shirt|kurta|top)\b", tl):
            return _eastern(cls, g, ST, "Bottoms")
        if leaf in ("Trouser", "Co-ord Set") or leaf in ("Shirt", "Top") and BOT.search(tl):
            got = pieces_leaf([title, desc], unstitched) or TT
            return _eastern(cls, g, UN if unstitched else ST, got)
        if leaf == "Shirt" or leaf in ("Top", "Dress") and re.search(r"kurt|kameez|frock", f"{title} {desc[:200]}", re.I):
            return _eastern(cls, g, UN if unstitched else ST, "1-Piece")

    if branch != "Eastern":
        return cls

    # Eastern: the pieces sold together, and stitched vs unstitched.
    if leaf in ("Dupatta", "Abaya", "Waistcoat", "Lehenga", "Saree", "Kaftan", "Slip / Inner", "Bottoms"):
        return _eastern(cls, g, sub, leaf)
    if re.search(r"\b(?:sharara|gharara)\b", tl) and (BOT.search(tl.replace("sharara", "").replace("gharara", "")) or
                                                       re.search(r"shirt|kurt|suit|set|piece|pc", tl)):
        return _eastern(cls, g, ST, "Sharara / Gharara")
    if leaf == "Shalwar & Pajama":
        return _eastern(cls, g, ST, "Bottoms")
    if unstitched:
        stock = _stock_pieces(p)
        if stock == 0:
            return None  # the shirt is sold out: not a suit any more
        got = stock or pieces_leaf([title, desc], True) or {"Suit": "3-Piece", "2-Piece": TT, "1-Piece": "1-Piece",
                                                           "3-Piece": "3-Piece"}.get(leaf, "3-Piece")
        return _eastern(cls, g, UN, got)
    if leaf in ("Kurta", "Kurti"):
        texts = [title, desc] if re.search(r"\bsuit|co-?ord|\bset\b", tl) else [title]
        got = pieces_leaf(texts) or (TT if len(texts) == 2 else "1-Piece")
        return _eastern(cls, g, ST, got)
    got = pieces_leaf([title, desc]) or (TT if leaf in ("Kurta Set", "Shalwar Kameez") else leaf)
    return _eastern(cls, g, ST, got)
