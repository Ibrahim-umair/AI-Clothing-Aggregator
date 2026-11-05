"""
Loads the full scraped catalog (95,992 products, 15 brands) into Postgres,
applying the same class of heuristic classification used in the frontend
prototype (regex over product_type/title/tags) — good enough to get real,
full-scale, browsable data in now; the rigorous per-store rule+LLM pipeline
designed separately is still the real production path.
"""
import json
import os
import re
import time
import psycopg2
from psycopg2.extras import execute_values

from product_normalize import normalize_product_fields, normalize_variant_fields, classify_size_system, tags_force_unavailable

# This sandbox's docker network appears to kill any single long-lived
# Postgres connection after a few minutes ("terminating connection due to
# administrator command"), which previously aborted the load partway
# through the first brand. Everything below is written to survive that:
# each product is inserted+committed as its own atomic unit (so a killed
# connection loses at most one in-flight product, never silently leaves a
# product row without its images/variants), the connection is proactively
# recycled on a timer, and any transient connection error triggers a
# reconnect-and-retry rather than aborting the whole run.
RECONNECT_SECONDS = 60


def connect():
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    return conn, conn.cursor()

DATA_DIR = r"C:\Work\scraping-init\scraped_data"
# Env-var driven (same convention as backfill_categories.py/reseed_categories.py)
# so this — and run_scrape.py, which imports DSN from here — can run against
# production via SSM without a code change; falls back to the local dev
# defaults when unset.
DSN = (
    f"host={os.environ.get('PGHOST', 'localhost')} "
    f"port={os.environ.get('PGPORT', '5433')} "
    f"dbname={os.environ.get('PGDATABASE', 'libas')} "
    f"user={os.environ.get('PGUSER', 'libas')} "
    f"password={os.environ.get('PGPASSWORD', 'libas_dev_password')}"
)

BRANDS_ALL = [
    ("outfitters", "Outfitters", "https://outfitters.com.pk", "liquid_rest"),
    ("furor", "Furor", "https://furorjeans.com", "liquid_rest"),
    ("edenrobe", "Edenrobe", "https://edenrobe.com", "liquid_rest"),
    ("one_be-one", "ONE (Be-One)", "https://beoneshopone.com", "liquid_rest"),
    ("equator", "Equator", "https://equatorstores.com", "shopify_ucp"),  # headless since Nov 2026
    ("meme", "Meme", "https://shopatmeme.com", "liquid_rest"),
    ("breakout", "Breakout", "https://breakout.com.pk", "liquid_rest"),
    ("monark", "Monark", "https://monark.com.pk", "liquid_rest"),
    ("engine_clothing", "Engine Clothing", "https://engine.com.pk", "liquid_rest"),
    ("charcoal", "Charcoal", "https://charcoal.com.pk", "liquid_rest"),
    ("royal_tag", "Royal Tag", "https://royaltag.com.pk", "liquid_rest"),
    ("diners", "Diners", "https://diners.com.pk", "liquid_rest"),
    ("cambridge", "Cambridge", "https://thecambridgeshop.com", "liquid_rest"),
    ("uniworth", "Uniworth", "https://uniworthshop.com", "liquid_rest"),
    ("cougar", "Cougar", "https://cougar.com.pk", "hydrogen_graphql"),
    # Added 2026-08-28 — no historical scraped_data/{slug}.jsonl exists for
    # these (they were never part of the original one-time scrape), so
    # they're populated live via db/scraper/run_scrape.py instead of this
    # loader's JSONL-replay path (see the os.path.exists guard below).
    # leisureclub.pk was checked too but is currently password-protected
    # ("coming soon" mode) — Shopify hides all public storefront data,
    # /products.json included, while that's on, so it's not addable until
    # the store owner makes it public.
    ("zellbury", "Zellbury", "https://zellbury.com", "liquid_rest"),
    # Fixed 2026-08-30 — the bare "lamaretail.com" root domain is a DEMO/
    # PLACEHOLDER Shopify instance, not Lama's real storefront: every one of
    # its 250 sampled products carries the literal tag "Demo Collections",
    # its product IDs/timestamps don't match the real store (US-timezone
    # offsets, e.g. "-05:00", vs. the real store's Pakistan "+05:00"), and
    # every variant is unavailable — which is exactly why 100% of Lama's
    # 1,616 products in this catalog were showing 0 in-stock variants (user
    # report: "I have been able to add products to cart myself" on
    # pk.lamaretail.com). Verified directly against the real domain before
    # switching: pk.lamaretail.com's own /products.json (same endpoint
    # shape fetch_rest_store already uses) returns real product data,
    # vendor "LAMA RETAIL", 2,000+ products across 8+ pages, and the exact
    # product from the user's own URL
    # (signature-cotton-shirt-mas26tp080-grey) shows every size
    # available:true there — matching what the user actually experienced
    # adding to cart. The old domain was never a real substitute; it just
    # happened to return valid-looking (but fake) Shopify JSON.
    ("lama", "Lama", "https://pk.lamaretail.com", "liquid_rest"),
    # Added 2026-08-31 — same live-scrape-only path as zellbury/lama above
    # (no historical scraped_data/{slug}.jsonl). Real Shopify store, 201
    # collections, activewear/basics/loungewear only (no Eastern wear at
    # all, confirmed by a full pre-load audit reading real product
    # descriptions across every women's/men's/kids' collection before
    # writing any classify() rule for it — see CHANGELOG.md).
    ("bandana", "Bandana", "https://bandana.pk", "liquid_rest"),
    # Added 2026-11-03: Salesforce Commerce Cloud stores, no product feed;
    # fetched by reading product pages (db/scraper/fetch_sfcc.py).
    ("khaadi", "Khaadi", "https://pk.khaadi.com", "sfcc"),
    ("sapphire", "Sapphire", "https://pk.sapphireonline.pk", "sfcc"),
    # Added 2026-11-03: women's Eastern brands, all Shopify with /products.json.
    ("junaid_jamshed", "J. (Junaid Jamshed)", "https://www.junaidjamshed.com", "liquid_rest"),
    ("gul_ahmed", "Gul Ahmed", "https://www.gulahmedshop.com", "liquid_rest"),
    ("bonanza_satrangi", "Bonanza Satrangi", "https://bonanzasatrangi.com", "liquid_rest"),
    ("maria_b", "Maria B", "https://www.mariab.pk", "liquid_rest"),
    ("ethnic", "Ethnic", "https://pk.ethnc.com", "liquid_rest"),
    ("limelight", "Limelight", "https://www.limelight.pk", "liquid_rest"),
    ("nishat_linen", "Nishat Linen", "https://nishatlinen.com", "liquid_rest"),
    ("alkaram", "Alkaram Studio", "https://www.alkaramstudio.com", "liquid_rest"),
    ("beechtree", "Beechtree", "https://beechtree.pk", "liquid_rest"),
    # Added 2026-11-05 as an unseen test of the Nov 2026 rules (category_refine.py).
    ("generation", "Generation", "https://generation.com.pk", "liquid_rest"),
    ("saya", "Saya", "https://saya.pk", "liquid_rest"),
    ("iznik", "Iznik", "https://iznikfashions.com", "liquid_rest"),
]
# NOTE: an earlier run duplicated the category tree (see get_or_make_category
# below) and split ~43k already-loaded products across the two copies, so
# products/variants/images and the duplicate categories were deleted and the
# root-cause fixed (partial unique index on root-level category slugs).
# Starting over from a clean products table — every brand is pending again.
BRANDS = BRANDS_ALL

# gender -> branch -> subbranch (or None) -> [(name, slug)]
# "Vest" added 2026-09-01 — user-reported: browsing Women's Jackets turned
# up real vests (a sleeveless outer layer, a fundamentally different
# garment from a jacket, which has sleeves). Read every one of the 156 real
# vest/gilet/bodywarmer products sitting in Jacket across every gender
# before making this change (Men 103, Cambridge's quilted/sherpa/puffer
# vests and Edenrobe's "Vest Gilet" line the bulk of it; Women 32, Bandana/
# Cougar/Lama casual and activewear vests; Boys 13, Girls 6, Unisex 2) —
# none showed any real Eastern signal (no shalwar/kameez/kurta/koti
# wording anywhere), so this is purely a Western sub-category split, not a
# branch move. They previously folded into Jacket because no separate
# Vest leaf existed at all (see _upperwear_leaf_from's own prior comment).
CATEGORY_TREE = {
    "Men": {
        "Western": {
            # "Tank Top" added 2026-08-29 — 140 real Men's tank tops
            # (Furor's own product_type literally "Men Tank Tops", Cambridge/
            # Engine's activewear tanks) had no leaf or keyword anywhere and
            # were falling to the generic Shirt default — found by a
            # dedicated category-by-category audit prompted after real
            # tank-tops/pocket-squares/scarves turned up in the live Men's
            # Shirt listing.
            "Upperwear": [("T-Shirt","t-shirt"),("Polo","polo"),("Shirt","shirt"),("Jacket","jacket"),("Vest","vest"),("Sweatshirt","sweatshirt"),("Hoodie","hoodie"),("Sweater","sweater"),("Tank Top","tank-top")],
            "Bottomwear": [("Trouser","trouser"),("Cargo Trouser","cargo-trouser"),("Jeans","jeans"),("Shorts","shorts"),("Joggers","joggers"),("Tights","tights")],
            # "Formal Suit"/"Tracksuit" added 2026-08-30 — a tailored Western
            # 2/3-piece business suit (blazer/lapel/breasted/waistcoat/tuxedo
            # language) and an athletic tracksuit are both a different
            # product from a casual matching "Co-ord Set" (loungewear/resort/
            # office-casual separates), the same distinction the user drew
            # after the Co-ord Set audit above. 247 real Men's/Boys' formal
            # suits (Equator 64, Monark 51, Edenrobe 55, Cambridge 35,
            # Charcoal 26, Diners 9, Uniworth 4, Royal Tag 3) and 34 real
            # tracksuits (Furor 23, Equator 5, Meme 5, Edenrobe 1) were
            # sitting in Co-ord Set. Deliberately did NOT move a handful of
            # Women's "Suit"/"Blazer Co-ord Set" titles that use the same
            # words — verified via real description ("...perfect for casual
            # outings, travel, everyday wear") that those genuinely are
            # casual separates, not tailored formalwear.
            "Suits & Sets": [("Co-ord Set","co-ord-set"),("Tracksuit","tracksuit")],
            # Split into its own sub-branch 2026-08-30, at the user's request
            # — a tailored Western business suit isn't a "set" in the same
            # sense as a Co-ord Set/Tracksuit and shouldn't be nested under
            # that same nav group. See classify()'s own comment for why
            # "Formal Suit" is Men/Boys-only.
            "Formalwear": [("Formal Suit","formal-suit")],
            "Footwear": [("Shoes","shoes")],
        },
        "Eastern": {
            "Stitched": [("Kurta","kurta"),("Shalwar Kameez","shalwar-kameez"),("Kurta Set","kurta-set"),("Waistcoat","waistcoat"),("Sherwani","sherwani")],
            "Unstitched": [("1-Piece","1-piece"),("2-Piece","2-piece"),("3-Piece","3-piece"),("Suit","suit")],
        },
        # "Keychain" added for 9 real Furor products (product_type
        # literally "Key Chains") that had nowhere to resolve — see
        # ACCESSORY_RE/_KEYWORD_LEAVES comments above.
        # "Scarf"/"Pocket Square" added 2026-08-29, same audit as Tank Top
        # above — 522 real Men's scarves/mufflers (Uniworth "Aqua Wool
        # Scarf", "Men Muffler") and 323 real pocket squares (Uniworth
        # "100% Silk Pocket Square", Cambridge/Equator formal accessories)
        # had no leaf/keyword and were falling to Shirt.
        "Accessories": [("Belt","belt"),("Tie","tie"),("Cap","cap"),("Wallet","wallet"),("Cufflink","cufflink"),("Watch","watch"),("Sunglasses","sunglasses"),("Jewelry","jewelry"),("Underwear","underwear"),("Socks","socks"),("Bag","bag"),("Shawl","shawl"),("Keychain","keychain"),("Scarf","scarf"),("Pocket Square","pocket-square")],
        "Fragrance & Beauty": [("Perfume","perfume")],
    },
    "Women": {
        "Western": {
            # "Tank Top" added 2026-08-29 — see Men's tree comment. 165 real
            # Women's tank tops were falling to Shirt for the same reason.
            "Upperwear": [("T-Shirt","t-shirt"),("Polo","polo"),("Top","top"),("Shirt","shirt"),("Jacket","jacket"),("Vest","vest"),("Sweatshirt","sweatshirt"),("Hoodie","hoodie"),("Sweater","sweater"),("Dress","dress"),("Tank Top","tank-top"),("Jumpsuit","jumpsuit")],
            # "Skirt" added 2026-08-31 — see SKIRT_RE's own comment. 95 real
            # products across the existing catalog had nowhere correct to
            # land.
            "Bottomwear": [("Trouser","trouser"),("Cargo Trouser","cargo-trouser"),("Jeans","jeans"),("Shorts","shorts"),("Joggers","joggers"),("Tights","tights"),("Skirt","skirt")],
            # "Tracksuit" added 2026-08-30 — see Men's tree comment. 9 real
            # Women's tracksuits (Furor, Meme) were sitting in Co-ord Set.
            "Suits & Sets": [("Co-ord Set","co-ord-set"),("Tracksuit","tracksuit")],
            "Footwear": [("Shoes","shoes"),("Sandals","sandals")],
        },
        "Eastern": {
            # "Kurta" added alongside the existing "Kurti" leaf — Women's
            # tree only ever had Kurti (Girls/Boys/Men all have Kurta too),
            # and classify() has always been able to emit leaf="Kurta" for
            # Women (whenever a title says "kurta" without "kurti") with
            # nowhere for it to resolve. Latent until Zellbury was added:
            # its real listings ("Embroidered Kurta - 2274", "Kurta Dupatta
            # Trouser - 0762", 111 real products) use "Kurta" for women's
            # wear, not "Kurti" — every one was stranding on the bare
            # Eastern branch node, caught by the branch-level-orphan audit.
            #
            # "Kurta Set" added the same way, one backfill pass later: real
            # Zellbury "Kurta Shalwar" combo listings (6 real products,
            # e.g. "Kurta Shalwar - 1679") hit KURTA_COMBO_RE and resolve
            # leaf="Kurta Set" (same logic Men/Boys/Girls already use for
            # this combo), but Women's tree never had that leaf either —
            # caught by the same audit, same latent-gap class as Kurta
            # itself just one real example behind it.
            "Stitched": [("Kurti","kurti"),("Kurta","kurta"),("Kurta Set","kurta-set"),("Shalwar Kameez","shalwar-kameez"),("Waistcoat","waistcoat")],
            "Unstitched": [("1-Piece","1-piece"),("2-Piece","2-piece"),("3-Piece","3-piece"),("Saree","saree"),("Suit","suit")],
        },
        # "Keychain" added for 5 real Outfitters products ("Multi-Charm
        # Keychain", "Crochet Keychain", etc. — vendor "Women", product_type
        # "JEWELLERY") stranding on the bare Accessories branch node: the
        # Keychain leaf added earlier this pass only went to Men's tree.
        # "Scarf"/"Pocket Square" added 2026-08-29 — see Men's tree comment.
        # 217 real Women's scarves/stoles were falling to Shirt for the same
        # reason (a standalone Dupatta/Stole was landing even further wrong,
        # in Shalwar Kameez — see the SCARF_RE check in classify()).
        "Accessories": [("Bag","bag"),("Jewelry","jewelry"),("Sunglasses","sunglasses"),("Shawl","shawl"),("Watch","watch"),("Underwear","underwear"),("Socks","socks"),("Belt","belt"),("Cap","cap"),("Wallet","wallet"),("Keychain","keychain"),("Scarf","scarf"),("Pocket Square","pocket-square")],
        "Fragrance & Beauty": [("Perfume","perfume")],
    },
    "Boys": {
        "Western": {
            "Upperwear": [("T-Shirt","t-shirt"),("Polo","polo"),("Shirt","shirt"),("Sweatshirt","sweatshirt"),("Hoodie","hoodie"),("Sweater","sweater"),("Jacket","jacket"),("Vest","vest"),("Tank Top","tank-top"),("Jumpsuit","jumpsuit")],
            "Bottomwear": [("Trouser","trouser"),("Cargo Trouser","cargo-trouser"),("Shorts","shorts"),("Jeans","jeans"),("Joggers","joggers")],
            # "Formal Suit" added 2026-08-30 — see Men's tree comment. 17
            # real Boys' tuxedo/double-breasted formal suits (Edenrobe,
            # Diners) were sitting in Co-ord Set. Split into its own
            # "Formalwear" sub-branch, same as Men's tree.
            "Suits & Sets": [("Co-ord Set","co-ord-set")],
            "Formalwear": [("Formal Suit","formal-suit")],
            "Footwear": [("Shoes","shoes")],
        },
        "Eastern": {"Stitched": [("Kurta","kurta"),("Kurta Set","kurta-set"),("Shalwar Kameez","shalwar-kameez"),("Waistcoat","waistcoat"),("Sherwani","sherwani")], "Unstitched": [("2-Piece","2-piece"),("Suit","suit")]},
        "Accessories": [("Cap","cap"),("Bag","bag"),("Underwear","underwear"),("Sunglasses","sunglasses"),("Socks","socks"),("Belt","belt"),("Watch","watch"),("Wallet","wallet"),("Scarf","scarf"),("Pocket Square","pocket-square")],
        "Fragrance & Beauty": [("Perfume","perfume")],
    },
    "Girls": {
        "Western": {
            "Upperwear": [("T-Shirt","t-shirt"),("Polo","polo"),("Top","top"),("Shirt","shirt"),("Sweatshirt","sweatshirt"),("Hoodie","hoodie"),("Sweater","sweater"),("Jacket","jacket"),("Vest","vest"),("Dress","dress"),("Tank Top","tank-top"),("Jumpsuit","jumpsuit")],
            "Bottomwear": [("Trouser","trouser"),("Cargo Trouser","cargo-trouser"),("Shorts","shorts"),("Jeans","jeans"),("Joggers","joggers"),("Tights","tights"),("Skirt","skirt")],
            # "Tracksuit" added 2026-08-30 — see Men's tree comment. 1 real
            # Girls' tracksuit (Edenrobe) was sitting in Co-ord Set.
            "Suits & Sets": [("Co-ord Set","co-ord-set"),("Tracksuit","tracksuit")],
            "Footwear": [("Shoes","shoes")],
        },
        "Eastern": {"Stitched": [("Kurti","kurti"),("Kurta","kurta"),("Kurta Set","kurta-set"),("Shalwar Kameez","shalwar-kameez"),("Waistcoat","waistcoat")], "Unstitched": [("2-Piece","2-piece"),("Suit","suit")]},
        "Accessories": [("Jewelry","jewelry"),("Bag","bag"),("Underwear","underwear"),("Sunglasses","sunglasses"),("Socks","socks"),("Belt","belt"),("Watch","watch"),("Cap","cap"),("Wallet","wallet"),("Scarf","scarf"),("Pocket Square","pocket-square")],
        "Fragrance & Beauty": [("Perfume","perfume")],
    },
    # This is a genuine catch-all for products with NO gender signal
    # anywhere (not even the store default) — real examples are Cambridge
    # Junior kids items where nothing in vendor/tags/title/product_type says
    # boy or girl. Needs the same real Western/Eastern branches as every
    # other gender, not just Accessories — 712 real products (kurtas,
    # shalwar kameez, polos, jeans...) were resolving gender correctly as
    # Unisex but then had no leaf to land on and fell back to the bare
    # gender root, since this tree previously had only Accessories.
    "Unisex": {
        "Western": {
            # "Dress" added — classify() can emit gender=Unisex when NO
            # gender word exists anywhere in vendor/tags/title/product_type
            # (the honest "we don't know" fallback), and that's independent
            # of whether the garment itself is a dress. Real example:
            # Lama's "PETERPAN DRESS" (vendor "LAMA", tags only mention a
            # sale collection, nothing gendered) — was stranding on the
            # bare Western branch node with nowhere for a Unisex dress to
            # go, caught by the branch-level-orphan audit.
            "Upperwear": [("T-Shirt","t-shirt"),("Polo","polo"),("Shirt","shirt"),("Sweatshirt","sweatshirt"),("Hoodie","hoodie"),("Sweater","sweater"),("Jacket","jacket"),("Vest","vest"),("Dress","dress"),("Tank Top","tank-top")],
            "Bottomwear": [("Trouser","trouser"),("Cargo Trouser","cargo-trouser"),("Jeans","jeans"),("Shorts","shorts"),("Joggers","joggers")],
            # Added alongside the FOOTWEAR_RE broadening (CHANGELOG #56) —
            # 4 real Lama/Zellbury footwear products ("LEATHER COWBOY
            # BOOTS", "MADDIE MAMA LOAFERS", "Slides - 5001", vendor is
            # just the store name, no gender word anywhere) resolve
            # gender=Unisex and had no Footwear branch at all to land on.
            "Footwear": [("Shoes","shoes")],
        },
        "Eastern": {
            "Stitched": [("Kurta","kurta"),("Kurta Set","kurta-set"),("Shalwar Kameez","shalwar-kameez"),("Waistcoat","waistcoat")],
            "Unstitched": [("1-Piece","1-piece"),("2-Piece","2-piece"),("3-Piece","3-piece"),("Suit","suit")],
        },
        "Accessories": [("Socks","socks"),("Cap","cap"),("Bag","bag"),("Tie","tie"),("Cufflink","cufflink"),
                        ("Sunglasses","sunglasses"),("Belt","belt"),("Wallet","wallet"),("Watch","watch"),
                        ("Jewelry","jewelry"),("Underwear","underwear"),("Shawl","shawl"),
                        ("Scarf","scarf"),("Pocket Square","pocket-square")],
        "Fragrance & Beauty": [("Perfume","perfume")],
    },
}


# Added 2026-10-28 from the manual category review (docs/NEXT_RUN_SPEC.md,
# review-exports/new-categories/): types that had no leaf, so they were filed
# under the nearest wrong one (blazers under Jacket, slides under Shoes,
# lapel pins under Jacket/Tie, dupattas under Scarf...). Kept as a separate
# block so the review's additions are easy to see. A new sub-group is created
# when it doesn't exist yet (Sleepwear, Swimwear).
def _add_leaves(gender, path, leaves):
    node = CATEGORY_TREE[gender]
    for key in path[:-1]:
        node = node.setdefault(key, {})
    last = path[-1]
    if isinstance(node, dict) and last not in node:
        node[last] = []
    existing = {name for name, _ in node[last]}
    for name in leaves:
        if name not in existing:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "")).strip("-")
            node[last].append((name, slug))


for _g in ("Men", "Women", "Boys", "Girls"):
    _add_leaves(_g, ("Western", "Footwear"), ["Sandals"])
    _add_leaves(_g, ("Western", "Sleepwear"), ["Nightwear & Loungewear"])
    _add_leaves(_g, ("Western", "Swimwear"), ["Swimwear"])
    _add_leaves(_g, ("Eastern", "Stitched"), ["Shalwar & Pajama"])
    _add_leaves(_g, ("Accessories",), ["Gloves"])
# Men's and boys' blazers are formalwear; women's and girls' are mostly
# casual, so they sit with upperwear. Search finds both by the name "Blazer".
_add_leaves("Men", ("Western", "Formalwear"), ["Blazer"])
_add_leaves("Boys", ("Western", "Formalwear"), ["Blazer"])
_add_leaves("Women", ("Western", "Upperwear"), ["Blazer"])
_add_leaves("Girls", ("Western", "Upperwear"), ["Blazer"])
_add_leaves("Unisex", ("Western", "Footwear"), ["Sandals"])
_add_leaves("Men", ("Accessories",), ["Pins & Clips", "Gift Set", "Suspenders"])
_add_leaves("Women", ("Accessories",), ["Pins & Clips", "Hair Accessories"])
_add_leaves("Girls", ("Accessories",), ["Hair Accessories"])
_add_leaves("Women", ("Eastern", "Stitched"), ["Abaya", "Lehenga", "Dupatta"])
_add_leaves("Girls", ("Eastern", "Stitched"), ["Lehenga", "Dupatta"])
# Where classify() puts a product no rule recognises, instead of guessing
# "Shirt" (231 of the 1,950 reviewed mistakes were that guess). The LLM
# enrichment run decides these; browse menus don't show this branch.
for _g in CATEGORY_TREE:
    CATEGORY_TREE[_g].setdefault("Uncategorised", [])


# Nov 2026 tree, from the women's stores audit (decided with Ibrahim, pieces
# checked with his mom). Women's and girls' Eastern clothes are filed by the
# pieces sold together; kurta/kurti/kameez/"shirt" all mean the shirt.
# Men's sets are Shalwar Kameez (kurta + shalwar) or Kurta Trouser; "Kurta
# Set" is gone. Home and Beauty hold what clothing stores also sell; they
# stay out of search and the AI run for now.
def _leaves(names):
    return [(n, re.sub(r"[^a-z0-9]+", "-", n.lower().replace("&", "")).strip("-")) for n in names]


PIECES = ["1-Piece", "2-Piece (Shirt + Trouser)", "2-Piece (Shirt + Dupatta)", "3-Piece"]
CATEGORY_TREE["Women"]["Eastern"] = {
    "Stitched": _leaves(PIECES + ["Bottoms", "Dupatta", "Abaya", "Waistcoat", "Lehenga", "Sharara / Gharara",
                                  "Saree", "Kaftan", "Slip / Inner"]),
    "Unstitched": _leaves(PIECES + ["4-Piece", "Saree"]),
}
CATEGORY_TREE["Girls"]["Eastern"] = {
    "Stitched": _leaves(PIECES + ["Bottoms", "Dupatta", "Waistcoat", "Lehenga", "Sharara / Gharara"]),
    "Unstitched": _leaves(PIECES),
}
for _g in ("Men", "Boys", "Unisex"):
    CATEGORY_TREE[_g]["Eastern"]["Stitched"] = [
        leaf for leaf in CATEGORY_TREE[_g]["Eastern"]["Stitched"] if leaf[0] != "Kurta Set"]
    _add_leaves(_g, ("Eastern", "Stitched"), ["Kurta Trouser"])
for _g in ("Men", "Boys"):
    _add_leaves(_g, ("Eastern", "Stitched"), ["Jubba"])
    _add_leaves(_g, ("Western", "Formalwear"), ["Dress Pants"])
_add_leaves("Women", ("Accessories",), ["Hijab", "Cape"])
for _g in ("Women", "Men", "Unisex"):
    _add_leaves(_g, ("Fragrance & Beauty",), ["Makeup", "Skincare"])
CATEGORY_TREE["Unisex"]["Home"] = _leaves(
    ["Bedding", "Cushions", "Table & Kitchen", "Curtains & Rugs", "Bath", "Home Fragrance"])
NOT_BROWSABLE_BRANCHES = {"Home"}
NOT_BROWSABLE_LEAVES = {"Makeup", "Skincare"}

FABRICS =["Lawn","Khaddar","Cambric","Cotton","Silk","Chiffon","Denim","Polyester","Linen","Wool","Blended","Organza","Velvet"]

# minimal seed; loader adds any new canonical color it meets
COLORS = [
    ("Black","#1c1c1c"), ("White","#f5f5f0"), ("Off-White","#efe8da"), ("Grey","#8a8a8a"),
    ("Navy","#1b2a4a"), ("Blue","#2f5fa8"), ("Red","#b02a2a"), ("Maroon","#5c1f1f"),
    ("Green","#2f6b3a"), ("Olive","#6b6b2f"), ("Beige","#d9c7a3"), ("Brown","#5a3a28"),
    ("Coffee","#5a3a28"), ("Pink","#e08bb0"), ("Yellow","#d9b93a"), ("Mustard","#c9962a"),
    ("Orange","#d9752a"), ("Purple","#6b3aa0"), ("Multi","#999999"), ("Mushroom","#c7b299"),
]

GENDER_WORDS = {"men": "Men", "man": "Men", "women": "Women", "woman": "Women", "boys": "Boys",
                "boy": "Boys", "girls": "Girls", "girl": "Girls", "unisex": "Unisex", "kids": "Unisex"}

STORE_GENDER_DEFAULT = {"furor": "Men", "charcoal": "Men", "uniworth": "Men", "royal_tag": "Men",
                         "monark": "Men", "equator": "Men", "cambridge": "Men",
                         # Khaadi's PK site has no men's line and never names a gender;
                         # Sapphire's breadcrumb says Woman/Man, this is only its fallback.
                         "khaadi": "Women", "sapphire": "Women",
                         # No men's clothing in a 100-product sample of each (2026-11-03).
                         "ethnic": "Women", "limelight": "Women", "nishat_linen": "Women",
                         "beechtree": "Women",
                         # Women's Eastern labels (2026-11-05).
                         "generation": "Women", "saya": "Women", "iznik": "Women"}

UNSTITCHED_RE = re.compile(r"un[\s-]?stitched", re.I)
# Singular-only was the bug: 131 real Outfitters/ONE-Be-One/Lama perfumes
# (product_type literally "FRAGRANCES"/"Perfumes", titles are just scent
# names with no fragrance word at all — "Spiced Rage", "Aqua Bloom",
# "AMALFI ORANGE") never matched `\bfragrance\b` against the plural
# "FRAGRANCES", and fell all the way through to the generic Shirt/T-Shirt
# default. User-reported: "Spiced Rage ... and other perfumes!" was one
# visible symptom of a much larger, previously-unfound gap.
FRAGRANCE_RE = re.compile(r"\b(perfumes?|fragrances?|colognes?|eau\s+de\s+\w+)\b|\b\d+\s*ml\b", re.I)
# This used to only recognize shoe/sandal/sneaker/heel — 1,024 real
# products (Diners/French Emporio's entire "Men Shoes"/"WOMEN SHOES"
# line, Lama's "PUMPS"/"BOOTS"/"SLIDES"/"MULES"/"LOAFERS" product_type
# buckets, Outfitters' "OPEN SHOES"/"CLOSED SHOES", one_be-one's
# "Slip-on"/"Sandals", real titles using "Khussa" — a traditional South
# Asian sandal — or one of three real misspelled variants of "moccasin"
# this catalog actually uses) were all falling through to the generic
# Shirt/T-Shirt Upperwear default with no footwear-specific word in this
# narrower list to catch them. Found via a full audit across every
# Upperwear leaf for exactly this class of bug, not just the one example
# reported ("saw a slipper there too").
# Excludes a footwear word immediately followed by an Upperwear garment
# noun — real example, Cougar's "Flip Flops T-Shirt", a t-shirt with a
# flip-flops print/theme (same naming pattern as "Spider Man Printed
# Tee"), not an actual sandal — was resolving to Shoes since this check
# runs before the T-Shirt leaf is ever considered. Same exclusion shape
# as `_SHORTS_ADJ_EXCLUDE` above.
FOOTWEAR_RE = re.compile(
    r"\b(shoes?|sandals?|sneakers?|heels?|boots?|pumps?|slippers?|"
    r"slides?|loafers?|trainers?|mules?|khussa|"
    r"mocassins?|moccassins?|moccasins?|flip.?flops?|brogues?|oxfords?|espadrilles?|chappals?|peshawaris?|kolhapuris?|"
    r"wedges?|slip[\s-]?ons?|clogs?|stilettos?|lace[\s-]?ups?)\b"
    r"(?!(?:\s+\w+){0,2}\s+(?:shirts?|tees?|t-shirts?|polos?|hoodies?|sweatshirts?|sweaters?|cardigans?|jackets?|blazers?|trousers?|pants?"
    r"|tops?|blouses?|dress(?:es)?|skirts?|shorts?|jumpsuits?)\b)",
    re.I,
)
# "Sandals" is a real leaf CATEGORY_TREE only defines for Women (Men/
# Boys/Girls only ever had "Shoes") — real sandal-shaped items
# (sandal/slide/khussa/flip-flop/mule) route there for Women instead of
# the generic Shoes leaf; everything else (boot/pump/loafer/sneaker/
# heel/moccasin) still goes to Shoes for every gender.
SANDAL_LEAF_RE = re.compile(r"\b(sandals?|slides?|khussa|flip.?flops?|mules?|chappals?|peshawaris?|kolhapuris?|slippers?)\b", re.I)
JOGGERS_RE = re.compile(r"\b(sweatpants?|joggers?|track\s*(?:pants?|trousers?))\b", re.I)
GIFT_CARD_RE = re.compile(r"gift\s*card", re.I)
# QA/placeholder artifacts left live on the storefront by mistake — not real
# merchandise at all. Real examples: "Test" (Equator, Rs. 10), "Test XPay"
# (Monark, Rs. 10, a payment-gateway test SKU), "MEN T-SHIRT (TEST)"
# (Breakout, Rs. 3499 — otherwise looks like a real listing, but the
# parenthetical "(TEST)" is not something a real customer-facing product
# would ever carry). Word-boundary so this can't collide with a real word
# containing "test" (e.g. "Testosterone").
TEST_PRODUCT_RE = re.compile(r"\btest\b", re.I)
# Checkout/packaging bags sold as a nominal add-on (Rs. 20-40 — far below
# any real fashion accessory price), not a wearable/carryable fashion item.
# Real examples: "Outfitters Shopping Bag" (product_type "SHOPPING BAGS"),
# "Shopping Bags" (Equator). Distinct from a real "Tote Bag"/"Handbag"/
# "Crossbody Bag" accessory, which stays a normal Accessories>Bag product.
SHOPPING_BAG_RE = re.compile(r"\bshopping\s*bags?\b", re.I)

BRANCH_KEYWORDS = [
    ("Fragrance & Beauty", "Perfume", FRAGRANCE_RE),
]
# "shawl" alone would also match "Shawl Collar Sweater" — a Western garment
# named for its collar STYLE, not an actual shawl accessory. Excluding that
# phrase here rather than in ACCESSORY_RE keeps the exclusion local to the
# one keyword that actually has this collision.
# "watch" collides with fabric/pattern names that have nothing to do with
# the accessory — "(Watch Maker)" and "Blackwatch"/"Black Watch" are real
# examples seen in this catalog (a tartan-style weave name and an internal
# collection label), not wristwatches. Excluded here rather than relying on
# the UNSTITCHED_RE guard alone, since a stitched item could carry the same
# fabric-pattern name.
# "tie" collides with "Tie Dye"/"Tie & Dye" (a common fabric-print name) and
# "Front Tie" (a design detail on a top's closure, not a necktie sold as its
# own product) — real examples found misfiled into Accessories: "TIE DYE
# T-SHIRT FOR MEN", "Tie Dye Polo", "TIE DYE JOGGER PANT FOR MEN", "Front Tie
# Top". Also excluded when hyphenated directly onto another word ("Tie-Waist
# Playsuit", "Tie-Up Jumpsuit", "Tie-Front Schiffli Net Shirt", "Tie-Dye
# Graphic T-Shirt") — real neckties are never written this way ("Poly Silk
# Tie", "Bow Tie", "Tie Pin" all use a space or stand alone), so `(?!-)`
# right after the word boundary is a safe general exclusion rather than
# enumerating every "Tie-X" compound individually. Also excluded when
# written with a plain space instead of a hyphen ("Tie Up Jumpsuit") and
# "die" as a common real-world misspelling of "dye" ("Tie & Die Viscose
# Dress", Furorjeans). Excluded the same way as shawl/watch above rather
# than dropping "tie" entirely, since real neckties are the large majority
# of matches and must keep working.
# "key\s*chain" added after a real Furor example: "Furor Jeans Club
# Keychain"/"Furor Jeans Keychain" (product_type literally "Key Chains")
# were landing in Men's Jeans, because ACCESSORY_RE never recognized
# "keychain" as an accessory at all — a bare "jeans" in the title fell
# through to the Bottomwear check further down uncontested. The other 7
# real Furor keychains with no "jeans" in the title ("Acrylic Keychain",
# "Fire Keychain", "FJ Keychain", "Insignia Keychain", "Leather Keychain")
# had the same underlying gap — they were falling through every branch to
# the generic Western/Upperwear "Shirt" default, just without the more
# visible Jeans collision. Recognizing "keychain" here fixes the
# collision at the source rather than special-casing "jeans" once more.
# Found by user-prompted extensive testing across the whole T-Shirt/Shirt
# leaf, all genders: this whole outer gate was singular-only for belt/
# cap/wallet/cufflink/bracelet/necklace/earring/clutch/watch, even though
# the leaf-picking regexes further down (_KEYWORD_LEAVES) had already
# been made plural-safe for some of these in earlier fixes — the plural
# form just never got past THIS gate to reach them. Real, substantial
# scope: 361 "Belts", 546 "Caps", 156 "Wallets", 752 "Cufflinks", 86
# "Bracelets", 40 "Necklaces", 230 "Earrings", 25 "Watches", 4 "Clutches"
# — e.g. an entire real product line, Furor/Cambridge/Diners' "Belts -
# CBT-4901"-style listings and "CUFFLINKS"/"Caps For Men", were landing
# in the generic Shirt default. Also added "hat"/"beanie" as Cap-leaf
# triggers (34 real "Hat" + 129 real "Beanie" titles/product_types, e.g.
# "Boonie Hat", "Bucket Hat", "Ribbed Beanie" — no separate Hat leaf
# exists in CATEGORY_TREE, folds into the same Cap leaf as "coat"/
# "blazer" folded into Jacket earlier this session), and folded
# "bracelet"/"necklace"/"earring" into the Jewelry leaf trigger below
# (CATEGORY_TREE has no separate leaf for those either).
# "bag" pulled out of the shared alternation into its own lookbehind-
# guarded alternative (same treatment as watch/tie below) after a real
# collision: "paper bag"/"paper-bag"/"paperbag" is a bottomwear FIT STYLE
# (a trouser/jeans/shorts waist style), not an actual bag — 23 real
# products (Outfitters' "High-Waist Paper Bag Jeans", Meme's "PAPER BAG
# DENIM JEANS FOR GIRLS", Charcoal's "LINEN PAPERBAG PANTS", etc.) were
# resolving to the Bag accessory leaf since this whole check runs before
# the bottomwear one further down.
# "cap sleeve(s)" excluded from the Cap match, "sock-fit" from Socks — two
# real Bandana/Lama miscategorizations found auditing the Bandana/Lama
# catalogs: "Women's Raglan Cap Sleeve Tee" (a sleeve STYLE, nothing to do
# with headwear) landed under Accessories>Cap, and Lama's "SOCK-FIT CASUAL
# SNEAKERS" (Rs. 8,970 — shoe-tier pricing, confirmed against the other 114
# real Socks products all under Rs. 1,950) landed under Accessories>Socks
# because "sock-fit" (a real sneaker-construction term, a knit upper built
# like a sock) contains the bare word "sock". Same class of bug as the
# existing "front tie"/"waist tie"/"black watch" exclusions just above.
ACCESSORY_RE = re.compile(
    r"\b(belts?|caps?(?!\s*sleeves?)|hats?|beanies?|wallets?|cufflinks?|sunglass(?:es)?|"
    r"jewel(?:l?ery|ry)?|bracelets?|necklaces?|earrings?|handbags?|"
    r"clutch(?:es)?|sock(?:s)?(?!-fit\b)|key\s*chains?|backpacks?|pocket\s*squares?|purses?|crossbody)\b"
    r"|(?<!paper[\s-])(?<!paper)\bbags?\b"
    # "tote(s)" folds into the same Bag leaf — real Bandana/Lama examples
    # ("Women Tote", "Journey Tote", "SUNDAY MARKET TOTE", "GOZO TRAVELER
    # TOTE") had no other accessory keyword at all and were falling all
    # the way through to the generic Western>Shirt default.
    r"|\btotes?\b"
    r"|shawl(?!\s*collar)"
    r"|(?<!black)(?<!black\s)watch(?:es)?(?!\s*maker)"
    r"|(?<!front\s)(?<!hair\s)(?<!waist\s)\bties?\b(?!-)(?!\s+up\b)(?!\s*(?:[&]|and)?\s*(?:dye|die)\b)"
    r"|\beyewear\b",
    re.I,
)
# "with ... belt/tie/scarf" describes a design detail already attached to
# another garment, not a standalone belt/tie/scarf being sold — real
# examples: "Barrel Fit Jeans With Belt Detail", "Long Dress With  Waist
# Belt", "BUTTON DOWN SHIRT WITH TIE DETAIL", "GRAPHIC TOP WITH TIE DETAIL",
# and (Lama) "CITY DRESS WITH SCARF DETAIL" — a genuine dress landing on
# Accessories>Scarf instead, off the same class of bug "belt"/"tie" were
# already fixed for. Every one of these had "with" somewhere before the
# belt/tie/scarf word, which a real standalone accessory listing ("Faux
# Leather Belt", "Poly Silk Tie", "Printed Silk Scarf") never does.
# Stripped out of the blob before ACCESSORY_RE runs rather than folded into
# that regex, since the gap between "with" and "belt"/"tie"/"scarf" is
# variable width and Python's re module requires fixed-width lookbehind.
GARMENT_DETAIL_RE = re.compile(r"\bwith\b.{0,40}?\b(?:belt|tie|scarf)s?\b", re.I)
# Real example the bare stripping above got wrong: Equator's "Black With
# Brown Contrast Leather Belt" (tags explicitly say "Accessories"/"BELT")
# is a genuine standalone belt whose OWN two-tone color is being
# described ("black, with brown contrast") — not a garment that has a
# belt as a detail. Every real "with...belt" garment-detail example
# ("Barrel Fit Jeans With Belt Detail", "Long Dress With Waist Belt")
# names the actual garment (jeans/dress/shirt/top/etc.) somewhere in the
# same title; the false positive above names none. Only strip the
# with-clause when a real garment noun is also present, so a standalone
# accessory whose own description happens to start with "with" isn't
# emptied out and lost.
GARMENT_NOUN_RE = re.compile(
    # "pants?" added alongside "trousers?" — real Lama example, "TAPERED
    # COTTON PANTS WITH BELT", was landing on Accessories>Belt because this
    # list only recognized the word "trousers", not the equally-common
    # "pants" spelling for the exact same garment.
    r"\b(shirts?|tops?|dress(?:es)?|jeans?|trousers?|pants?|jumpsuits?|jackets?|"
    r"kurt[ai]s?|co-?ords?|playsuits?|tees?|t-shirts?|sweaters?|"
    r"sweatshirts?|hoodies?|frocks?|gowns?|rompers?|skirts?)\b",
    re.I,
)


def strip_garment_detail(text):
    if GARMENT_DETAIL_RE.search(text) and GARMENT_NOUN_RE.search(text):
        return GARMENT_DETAIL_RE.sub(" ", text)
    return text
# sherwani/waistcoat are Eastern formalwear (a sherwani is worn over a
# shalwar, and this catalog's own tree already treats Waistcoat as an
# Eastern>Stitched leaf) — without them here, both branch-routed to Western
# purely because nothing else matched, which is wrong, not just imprecise.
# "frock" is deliberately NOT here — checked all 11 real Cougar products
# using it ("Girl Frock" as their own product_type) and every one is a
# plain Western casual dress (Polka Dot Dress, Tie & Dye Dress, Asymmetrical
# Smocked Dress...) with zero Eastern styling. It's generic Pakistani-English
# for "girl's dress," not an Eastern-specific garment — treated as a Dress
# synonym in the Western fallback instead.
# sharara/gharara/lehenga/kalidar/pishwas added 2026-08-30 (Co-ord Set
# audit) — verified catalog-wide safe (81 real matches: Co-ord Set 77,
# Shirt 3, Kurta 1, zero anywhere else) before adding; real examples
# ("Jamawar Sharara Set", "Embroidered Gharara Suit", "Girls Gharara Set")
# were falling to Western Co-ord Set or the generic Shirt default.
EASTERN_RE = re.compile(r"\b(kurta|kurti|shalwar|kameez|saree|sari|dupatta|sherwani|waistcoat|sharara|gharara|lehenga|kalidar|pishwas|abayas?)\b", re.I)

# Same vocabulary as EASTERN_RE, MINUS "waistcoat" — used only when
# scanning free-text TAGS/DESCRIPTION (never title/product_type) to
# decide whether a title that looks like a Western "Suit"/"Co-ord Set" is
# actually a mislabeled Eastern ensemble (see its call site in the Suits &
# Sets check). "waistcoat" is excluded here specifically because a
# genuine WESTERN 3-piece suit's own description routinely uses that exact
# word too — a real false positive caught during verification, Equator's
# "Light Grey Three Piece Suit" ("...single-breasted jacket, notch
# lapels...finished with a shawl lapel waistcoat...", unambiguously
# Western tailoring). "waistcoat" stays a fully-trusted Eastern signal
# everywhere else in this file (title/product_type only).
EASTERN_TAGS_DESC_RE = re.compile(r"\b(kurta|kurti|shalwar|kameez|saree|sari|dupatta|sherwani|sharara|gharara|lehenga|kalidar|pishwas)\b", re.I)

# A "Prince Coat"/"Prince Suit" is a short embroidered Eastern formal coat
# (wedding/festive menswear), not a Western jacket — but this is only
# consulted from inside the Co-ord Set override below, scoped to items
# that already look like a coordinated multi-piece SET. A standalone
# "Prince Coat" with no set signal (52 real products, currently Jacket)
# is a separate, out-of-scope question this audit didn't cover and is
# deliberately left untouched.
PRINCE_SET_RE = re.compile(r"\bprince\s+(coat|suit)\b", re.I)

# Edenrobe's/Cambridge's own real structural convention for a stitched
# shirt/frock + trouser/shalwar 2-piece ensemble, used when no OTHER
# Eastern word appears anywhere (title, tags, or description) to trigger
# EASTERN_RE directly — real descriptions label each piece with its own
# "Fit Type:"/"Fabric:"/"Style:" fields, e.g. "Shirt Fit Type: Straight
# Fit Fabric: Organza Style:...Trouser Fit Type: Straight Fit Fabric:
# Organza Style:...". Requires the labeled "Fit Type:" convention
# specifically (not just any 2 mentions of "fabric") — a looser
# "fabric mentioned twice" version was verified UNSAFE: it false-matched
# Furor's Western "Resort Co-Ord Set Shirt" line, whose flowing prose
# ("Crafted from Soft, Breathable Crochet Fabric...Best Worn with Its
# Matching Trousers...") mentions "fabric" and "trousers" without using
# this labeled-piece convention at all. With "Fit Type:" required,
# verified exclusive to genuine Eastern ensembles (Edenrobe 991,
# Cambridge 17, Diners 3 — the Furor/Monark/Engine/Royal Tag/Charcoal
# false positives all disappeared).
FIT_TYPE_LABEL_RE = re.compile(r"fit type\s*:", re.I)


def _has_structured_shirt_trouser_desc(description):
    if not description:
        return False
    d = description.lower()
    return (
        ("shirt" in d or "frock" in d)
        and ("trouser" in d or "shalwar" in d)
        and len(FIT_TYPE_LABEL_RE.findall(d)) >= 2
    )

# A standalone scarf/muffler/stole/dupatta is an ACCESSORY sold on its own,
# not part of an ensemble — but "dupatta" is also one of EASTERN_RE's own
# trigger words (needed so a real "Shirt Trouser Dupatta" 3-piece unstitched
# set still counts it as a named piece further down). Without this check,
# a bare dupatta/stole product enters the Eastern branch purely because of
# that shared word, finds no other Eastern signal, and falls through that
# branch's OWN silent final-else fallback to Shalwar Kameez — worse than
# the generic Shirt default this whole audit was chasing. Real examples:
# Diners "Stoles/Dupatta" product_type, titles just "Printed Dupatta"/
# "Laces Dupatta"/"Dyed Duppatta" (both spellings seen); Uniworth "Aqua Wool
# Scarf"/"Men Muffler" (no Eastern word at all, was falling to Shirt
# instead). Checked ahead of the Eastern-branch entry below, and only wins
# when no OTHER real Eastern garment word is also present — a scarf
# genuinely bundled into a kurta/shalwar-kameez ensemble should still route
# there, not get peeled off into a standalone accessory.
SCARF_RE = re.compile(r"\b(scarf|scarves|mufflers?|stoles?|dupattas?|duppattas?)\b", re.I)
OTHER_EASTERN_GARMENT_RE = re.compile(r"\b(kurta|kurti|shalwar|kameez|sherwani|waistcoat)\b", re.I)

# See the "waistcoat" guard's own comment at its call site for the full
# reasoning — checked against product_type+title+tags+description.
WESTERN_WAISTCOAT_RE = re.compile(r"\b(western|outerwear|faux\s*leather|pinstripe|denim|leather|blazers?)\b", re.I)
EASTERN_WAISTCOAT_COMPANION_RE = re.compile(r"\b(kurta|kurti|shalwar|kameez|koti|mashriq)\b", re.I)

# Edenrobe's own real naming convention for a stitched (ready-to-wear)
# Kurti+Trouser 2-piece set — confirmed against real body_html ("Girls'
# Pret Kurti & Trouser") for the STITCHED version specifically. The
# UNSTITCHED version of the same "Shirt Trouser" title pattern (670 real
# products) already resolves correctly, because its product_type contains
# "Un Stitched" and UNSTITCHED_RE catches it independently — but the
# stitched version (399 real products, product_type "Woman Pret
# Embroidered"/"Girls Eastern") has no word EASTERN_RE recognizes anywhere
# in its own title, and was falling through to plain Western Trouser.
# Verified exclusive to Edenrobe (1,069 total real matches, no other brand)
# before adding as a general Eastern-branch trigger.
SHIRT_TROUSER_SET_RE = re.compile(r"\bshirt\s*trousers?\b", re.I)

# "boxer"/etc are real garments but not outerwear — without this check
# they fell through to the generic Western/Upperwear default and showed
# up as "Shirt". Checked ahead of ACCESSORY_RE/EASTERN_RE.
#
# Bare "vest"/"vests" used to be in this same list, but unlike
# boxers/briefs/panties it's genuinely dual-use in this catalog's real
# vocabulary: a real "vest" is as often a sleeveless OUTERWEAR piece
# (quilted/padded/puffer/sherpa vest, a "vest jacket", a sweater vest, a
# suiting/activewear vest, a "vest T-shirt" tank top) as it is a sando/
# undergarment tank. Querying the live Women's/Men's Underwear category
# found ~90 real "vest" titles, and the large majority (Cambridge's
# Quilted/Padded/Sherpa Vest line, Cougar's Sweater Vests, Engine's
# Active Wear Vests, Furor's Vest Gilets/Jackets, Equator's Training/
# Sweater Vests, Cambridge's own Suiting Vests) were real outerwear/
# activewear, not underwear at all. Handled below via a narrower,
# signal-gated check instead of this unconditional word match.
# "bra"/"camisole" added 2026-08-31 during the Bandana.pk onboarding audit
# — neither had a keyword anywhere in this file. 40 real EXISTING products
# across other brands too ("White Glide-Fit Sports Bra", "BRA TANK TOP",
# "T-SHIRT BRA", "Jogger Bra") were scattered across Shirt/Tank Top/
# T-Shirt/Co-ord Set/Joggers instead of Underwear. Word-boundary anchored
# so it doesn't match inside "bralette"/"Cobra"/"Zebra" (no boundary
# between "bra" and what follows/precedes in those words) — verified
# catalog-wide before shipping, zero false positives found.
UNDERWEAR_RE = re.compile(r"\b(boxers?|briefs?|underwear|innerwear|panties|panty|undergarment|bras?|camisoles?(?!\s+tops?)|sandos?(?!\s+tops?)"
                          r"|thermal\s+inner|inner\s+(?:tops?|bottoms?)|thermal\s+(?:suits?|sets?))\b", re.I)
VEST_RE = re.compile(r"\bvests?\b", re.I)
# A bare "vest" only counts as underwear when something explicitly says
# so — "sando" (the real Pakistani-market word for a men's undergarment
# tank) or "undergarment" itself. Uniworth's real vest listings have no
# such word in vendor/product_type/title at all, only in the product
# DESCRIPTION ("our sporty undergarment will keep you cool..." — verified
# against real raw_source body_html), which is why this check is run
# against a blob that includes description, unlike every other pattern
# in this function.
VEST_UNDERWEAR_SIGNAL_RE = re.compile(r"\bsando\b|\bundergarments?\b", re.I)
# A real outerwear/activewear/formalwear signal anywhere overrides a bare
# "vest" even if (rarely) an undergarment word also happens to be
# present — every real example above of a wrongly-caught vest had one of
# these words in its own vendor/product_type/title.
VEST_OUTERWEAR_SIGNAL_RE = re.compile(
    r"\bjackets?\b|\bgilets?\b|\bsweaters?\b|\bhoodies?\b|\bquilted\b|"
    r"\bpuffer\b|\bsherpa\b|\bsuit(?:ing|s)?\b|\bactive\s*wear\b|"
    r"\btees?\b|\bt-shirts?\b|\btank\s*tops?\b",
    re.I,
)
# A DIFFERENT distinction from the underwear-vs-not check right above —
# this decides whether an already-confirmed OUTERWEAR-class "vest" is
# really a sleeveless ATHLETIC TOP (the same garment this catalog already
# calls "Tank Top") rather than a puffer/quilted/waistcoat outer LAYER.
# See _upperwear_leaf_from's own comment for the real examples this was
# built against.
ACTIVEWEAR_VEST_SIGNAL_RE = re.compile(
    r"\bgym\b|\bactive\s*wear\b|\btraining\b|\bworkouts?\b|\bdry[\s-]?fit\b|\bsports?\s*vest\b",
    re.I,
)
# A THIRD distinction inside the same "Vest" leaf, same real class of bug
# as ACTIVEWEAR_VEST_SIGNAL_RE above — user-reported directly, browsing
# Men's Vest: "seeing... open knit vest (sweater) on vests." A plain
# ribbed/knit "vest" with no other outerwear signal is a basic jersey
# TANK, the same real garment already routed to Tank Top above — not a
# puffer/quilted/waistcoat OUTERWEAR layer. Photo-verified before
# trusting the title: Furor's whole "Ribbed Vest" line (FMTV5/FMTV6/FWTT
# SKUs — description "Regular Fit Rib Fabric") is a plain scoop-neck
# ribbed tank, and Engine Clothing's "Men Sleeveless Panel Knit Vest" is
# a plain jersey ringer tank — neither has any padding, quilting, collar,
# or closure, just a bare knit tank silhouette. Distinct from "open knit"
# above (a sweater-weight knit stitch, always outerwear-adjacent, never
# this) and gated to exclude any real outerwear word so a genuine quilted/
# puffer/sherpa/suede/down/leather/nylon/gilet/waistcoat vest that merely
# mentions a ribbed TRIM or hem as a detail (Cambridge's "Ribbed hem"
# design note on an otherwise-quilted vest, a real example already in
# this catalog) is never caught by this.
PLAIN_RIBBED_KNIT_VEST_RE = re.compile(r"\b(ribbed?|knit)\b", re.I)
VEST_REAL_OUTERWEAR_RE = re.compile(
    r"\bquilted\b|\bpuffer\b|\bsherpa\b|\bsuede\b|\bgilets?\b|\bdown\b|"
    r"\bleather\b|\bnylon\b|\bwaistcoats?\b|\bopen knit\b",
    re.I,
)

# "kurta pajama"/"kurta shalwar" is a two-piece SET, not the same product as
# a plain kurta sold alone — the two need different leaves. Checked before
# the bare kurta/kurti fallback so a combo phrase never collapses to "Kurta".
KURTA_COMBO_RE = re.compile(
    r"\bkurt[ai]\b[\s\w]{0,25}\b(pajama|payjama|shalwar)\b|\b(pajama|payjama|shalwar)\b[\s\w]{0,25}\bkurt[ai]\b",
    re.I,
)

# Word for the "sharara/gharara/lehenga/kalidar/pishwas" style group —
# these are distinctly different from a plain Shalwar Kameez, so they get
# their own leaf resolution ("Kurta Set", the closest existing multi-piece
# Eastern leaf) rather than falling into the generic Shalwar Kameez default.
LEHENGA_STYLE_RE = re.compile(r"\b(sharara|gharara|lehenga|kalidar|pishwas)\b", re.I)

# Shared leaf-naming logic for a confirmed Eastern/Stitched item, used both
# by the main Eastern-branch entry point below and by the Co-ord Set
# override (see its call site) — kept as one function so both places agree
# on what a given set of Eastern words resolves to. `blob` is the normal
# title/product_type signal (unchanged behavior at the main entry point);
# `extra_signal`, only passed by the Co-ord Set override, is the
# tags+description text that revealed the item was really Eastern in the
# first place — consulted for leaf-NAMING only, never widened further than
# what the caller already decided counts as a trustworthy signal.
def _eastern_stitched_leaf(blob, extra_signal=""):
    combined = f"{blob} {extra_signal}".lower()
    # 2026-10-28: abaya and lehenga got their own leaves (Zellbury abayas,
    # Edenrobe/Cougar "Lehenga Suit"/"Lehenga Set" were filed as Kurta Set).
    if re.search(r"\babayas?\b", blob):
        return "Abaya"
    if re.search(r"\blehn?gas?\b|\blehengas?\b", blob):
        return "Lehenga"
    if KURTA_COMBO_RE.search(blob):
        return "Kurta Set" if "kurta" in blob else "Shalwar Kameez"
    # "Shalwar Kameez with Waistcoat" is the suit, not the waistcoat (a
    # waistcoat sold alone can still have a shalwar-kameez product type).
    if re.search(r"(?:shalwar\s*kameez|kameez\s*shalwar)\b.*\bwith\s+waist\s*coat", blob):
        return "Shalwar Kameez"
    if PRINCE_SET_RE.search(combined):
        return "Sherwani"
    if "sherwani" in combined:
        return "Sherwani"
    # "waistcoat" is intentionally checked against `blob` only, never
    # `extra_signal` — see EASTERN_TAGS_DESC_RE's own comment for why a
    # description-only "waistcoat" mention isn't trustworthy here.
    # "Waistcoat Suit" / "Kurta Waistcoat Set" is a kurta outfit that comes
    # with a waistcoat, not a waistcoat on its own.
    if "waistcoat" in blob and re.search(r"\bwaistcoat\s+(?:suits?|sets?)\b|\bkurta\b", blob):
        return "Kurta Set"
    if "waistcoat" in blob:
        return "Waistcoat"
    if LEHENGA_STYLE_RE.search(combined):
        return "Kurta Set"
    if "kurti" in combined:
        return "Kurti"
    if "kurta" in combined:
        return "Kurta"
    if SHIRT_TROUSER_SET_RE.search(blob) or _has_structured_shirt_trouser_desc(extra_signal):
        return "Kurta Set"
    return "Shalwar Kameez"


# jumpsuit/playsuit/bodysuit are real one-piece garments, not a
# coordinated multi-piece SET — they must never fall into the buggy
# `\bco-?ord|suit\b` precedence bug (see the Suits & Sets check) that used
# to catch bare "suit" as a suffix inside any word. 142 real products
# (Girls 97, Women 37, Boys 8) were landing in Co-ord Set purely because
# of that bug; with it fixed, they need this explicit positive route
# instead of falling through to the generic Shirt default.
JUMPSUIT_RE = re.compile(r"\b(jumpsuits?|playsuits?|bodysuits?)\b", re.I)

# An athletic tracksuit is a distinct product from a fashion/loungewear
# "Co-ord Set" — 34 real products (Furor 23, Equator 5, Meme 5, Edenrobe 1)
# were sitting in Co-ord Set once the regex-precedence bug above was fixed
# (the bug used to catch them too, just via the bare "suit" suffix). The
# word itself is unambiguous, so no gender/signal gating is needed the way
# FORMAL_SUIT_RE below needs it.
TRACKSUIT_RE = re.compile(r"\btracksuits?\b", re.I)

# Furor's own real "Tracksuit" line uses the word as a COLLECTION name,
# not a claim that the product itself is a 2-piece set — real examples:
# "Quarter-Zip Tracksuit Sweatshirt" (product_type "Men Sweatshirts") is
# just a sweatshirt; "Mock Neck Tracksuit Zipper Jacket" (product_type
# "Men Jackets") is just a jacket; "Piping Detail Tracksuit Hoodie"/
# "Tracksuit Pullover Hoodie"/"Tracksuit Zipper Hoodie" (product_type
# "Men Hoodies") are just hoodies. A genuine 2-piece tracksuit SET never
# has another garment noun immediately after the word "tracksuit" —
# Furor's own real sets ("Hoodie Tracksuit"/"Zipper Jacket Tracksuit",
# product_type "Woman Track Suit") name the other garment BEFORE
# "tracksuit", with nothing following it; Equator/Charcoal/Meme's bare
# "___ Tracksuit"/"Tracksuit Set" titles have nothing garment-specific
# following it either. When a single-garment noun DOES follow, that's the
# real (single) product — checked at the Tracksuit call site, which falls
# through to the normal Jacket/Hoodie/Sweatshirt/etc. resolution instead
# of forcing Tracksuit.
TRACKSUIT_SINGLE_GARMENT_RE = re.compile(
    r"\btracksuit[\s\w-]{0,20}\b(jackets?|hoodies?|sweatshirts?|sweaters?|polos?|t-shirts?|tank\s*tops?)\b",
    re.I,
)

# A tailored Western 2/3-piece business suit (blazer/lapel/breasted/
# waistcoat/tuxedo tailoring language) is a distinct product from a casual
# matching "Co-ord Set" (loungewear/resort/office-casual separates) — same
# distinction as Tracksuit above, but this one needs real signal words
# rather than a single unambiguous word, since a plain "Suit" title covers
# both. Checked only for Men/Boys (see its call site): a handful of
# Women's "Suit"/"Blazer Co-ord Set" titles use these same words
# (Engine Clothing, Meme) but their own real descriptions confirm they're
# genuinely casual separates ("...perfect for casual outings, travel,
# everyday wear"), not tailored formalwear — verified before excluding
# Women/Girls from this signal. "waistcoat" is trusted here (unlike
# EASTERN_TAGS_DESC_RE's own exclusion of it) because in THIS context —
# already Men/Boys, already failed the Eastern override above — a
# waistcoat mention is exactly the Western 3-piece-suit signal it looks
# like, not a false positive.
FORMAL_SUIT_RE = re.compile(
    r"\b(blazers?|lapels?|breasted|bespoke|tuxedos?|waistcoats?)\b"
    # "formal suit" the PHRASE (not bare "suit" alone — deliberately still
    # excluded, see above) is unambiguous enough to trust outright — a
    # casual Co-ord Set never calls itself "formal." Real bug found via a
    # size-anomaly audit (chest-inch sizing on a "Co-ord Set" item — user-
    # reported, unrelated original complaint about Vest sizing turned up
    # this too): 112 real products literally titled "Formal Suit -
    # EBTCPC..." (Edenrobe) were still sitting in Co-ord Set because
    # their own text never says blazer/lapel/tuxedo/etc, only "suit" —
    # only 36 of 148 "Formal Suit"-titled products were actually
    # resolving to the Formal Suit leaf before this.
    r"|\bformal\s+suits?\b"
    # 2026-11-01: a tailoring fit named with "suit" ("Smart Fit Suit").
    r"|\b(?:smart|slim|tailored|super\s+slim|regular|classic)\s+fit\s+(?:\w+\s+)?suits?\b|\btailored\b.*\bsuits?\b",
    re.I,
)
# A second, narrower signal for the same real bug: several brands
# (Cambridge's "SHARP"/"LUXER" lines, real examples "Sharp 3 Piece Suit",
# "SHARP (3PC)") never say "formal" or any FORMAL_SUIT_RE word either —
# just "suit" plus this brand's own tailoring-fit boilerplate ("Model is
# 6'2" with a 40" chest, and is wearing a size 40"). That exact boilerplate
# phrase, checked against every current Co-ord Set product before trusting
# it: appears on only 16 total, 14 of which also say "suit" (all real
# formal suits, chest-inch sized in the variant data too); the other 2
# ("KNIT & PAJAMA," a genuine loungewear set) don't say "suit" at all, so
# requiring BOTH together — not just the boilerplate alone — keeps this
# safe.
FORMAL_SUIT_CHEST_BOILERPLATE_RE = re.compile(r"\bchest,?\s+and\s+is\s+wearing\b", re.I)

# Bare "short" is too greedy — it matches "short sleeve shirt/tee/polo",
# a description of an UPPERWEAR item's sleeve length, not the bottomwear
# garment. Real bottomwear listings say "shorts" (plural) or "short" not
# immediately followed by "sleeve". TROUSER_RE covers trouser/jean/pant
# separately since those never have this collision.
#
# The sleeve exclusion originally only handled a whitespace-separated
# "sleeve"/"sleeves" — real titles ("Short-Sleeve Polo Shirt",
# "Short-Sleeved Sweater") use a hyphen instead of a space (`\s` doesn't
# match `-`) and/or the "-d" adjective suffix, and both were slipping
# through into Women's Shorts. `[\s-]*` covers the hyphen-or-space
# separator and `(?:s|d)?` covers sleeve/sleeves/sleeved.
#
# Separately, bare singular "short" (as opposed to plural "shorts") is
# almost always the LENGTH ADJECTIVE, not the garment, when it precedes
# another garment noun — real examples "Short Coat", "Short Dress", and
# Engine Clothing's "Women Shorts Body Blazer"/"...Body Jacket" (9 real
# products, a line-naming convention where "Shorts" precedes "Body
# Blazer"/"Body Jacket" and never actually means the garment) were all
# resolving to Women's Shorts. Excluded via a lookahead for a small,
# real-example-driven list of garment nouns within a couple of words —
# not a lookbehind-only check, since "Shorts Body Blazer" has "Body"
# between "Shorts" and the noun that actually disambiguates it.
# "chino(s)" added 2026-08-29 — 84 real Zellbury products ("Signature
# Chino - S003", product_type "Shirt") were falling to the generic Shirt
# default; every real "chino"/"chinos" title checked catalog-wide (Edenrobe,
# Furor, Zellbury — over 1,200 products) unambiguously names a trouser, no
# collision shape found worth excluding.
TROUSER_RE = re.compile(r"\b(trousers?|jeans?|pants?|chinos?|cargos?)\b", re.I)

# "Skirt" never had a leaf or keyword anywhere in this file — found during
# the Bandana.pk onboarding audit (a real "Skirts" collection there), but
# 95 real products across the EXISTING catalog too ("WILDFLOWER TIER
# SKIRT", "Denim Skirt With Front Slit") were scattered across Shirt (67),
# Jeans (10), Shorts (10), Co-ord Set (5), Trouser (3) with nowhere
# correct to land. Checked ahead of the Trouser/Jeans/Shorts split (title-
# first, matching that section's own precedent) so a "Denim Skirt" isn't
# pulled into Jeans by the bare-denim fallback.
SKIRT_RE = re.compile(r"\bskirts?\b", re.I)
# Bare "cargo" alone is a strong enough bottomwear signal on its own — real
# examples with NO other bottomwear word at all: "TWILL CARGO" (product_type
# "Relaxed Fit"), "Men Cargo Touser" (a real title typo for "Trouser") —
# both were falling to the generic Shirt default. Added to TROUSER_RE above
# so these actually enter the Bottomwear branch, and used here to give
# cargo-styled full-length pants their OWN leaf: "cargo" was previously
# splitting across Trouser/Jeans/Shirt depending on incidental wording
# ("Denim Cargo Trouser" landed in Jeans purely because of bare "denim"
# outranking the title's own "Trouser"), which is exactly the kind of
# subjective-style pollution a shopper searching "cargo trousers" was
# reporting — real Jeans/Trousers with a totally different silhouette
# ranking alongside genuine cargo pants. Checked ahead of the Jeans/Trouser
# split, but NOT ahead of Shorts/Joggers (checked earlier/separately) —
# "Cargo Shorts"/"Cargo Joggers" are real, already-distinctly-named
# garments and were deliberately left alone; only the Trouser/Jeans
# ambiguity needed resolving. 443 real products across Men/Women/Boys/
# Girls/Unisex.
CARGO_RE = re.compile(r"\bcargo\b", re.I)
# "heel" added the same way: a real Meme product, "SHORT BLOCK HEEL", is a
# low-heeled shoe (a footwear-height descriptor), not the garment — landed
# in Women's Shorts with 0 intervening words, same collision shape as
# "Short Coat"/"Short Dress".
_SHORTS_ADJ_EXCLUDE = r"(?:coat|dress|jacket|blazer|heels?)"
# "jorts" (a real, unambiguous portmanteau for jean shorts — no other
# meaning) added as its own alternative, no exclusion logic needed since
# it doesn't share the "short sleeve"/"short coat" collision shape at
# all. Real examples: "Baggy Denim jorts", "Denim Bermuda Jorts" — with
# no literal word "short(s)" in the title and a bare "denim" also
# present, these were resolving to Jeans via the title-first bottomwear
# check (a bare "denim" with no other bottomwear signal defaults to
# Jeans) before ever reaching a correct product_type "SHORTS" fallback.
# ("bermuda" alone isn't added — it also names an unrelated real product
# line, "Blissful Bermuda Blue Drop Earrings", so it isn't a safe general
# signal the way "jorts" is.)
SHORTS_RE = re.compile(
    r"\bjorts?\b"
    r"|\bshorts?\b(?![\s-]*sleeve(?:s|d)?\b)"
    rf"(?!(?:\s+\w+){{0,2}}\s+{_SHORTS_ADJ_EXCLUDE}\b)",
    re.I,
)


GENDER_PATTERNS = [
    # "women"/"woman" MUST be checked before "men"/"man" via word-boundary
    # regex rather than plain substring containment — a plain `"men" in
    # blob` check (the original approach) matches "women"/"woman" too,
    # since "men"/"man" are literal substrings of them, silently sending
    # every women's product into the men's bucket (this is why real runs
    # of this loader landed exactly zero products under "Women").
    (re.compile(r"\bwomen\b", re.I), "Women"),
    (re.compile(r"\bwoman\b", re.I), "Women"),
    # "boys"/"girls" MUST be checked before "men"/"man" too, for a
    # different reason: a real product, Breakout's "BOYS DROP SHOULDER
    # SPIDER MAN PRINTED TEE" (vendor "KIDS" — not a GENDER_PATTERNS word
    # itself, so this doesn't get resolved at the vendor-only pass above
    # and falls through to the full blob), has an explicit "BOYS" in both
    # its tags and title, but also "SPIDER MAN" (two words, space-
    # separated — "Spiderman" as one word doesn't collide) which matches
    # bare `\bman\b`. With `\bman\b` checked first, the incidental "Man"
    # from the character name won gender resolution over the item's own
    # explicit "Boys" signal. The character-name collision only exists for
    # "man"/"men" (Spider Man, Iron Man, Super Man) — no equivalent
    # collision exists for "boys"/"girls" — so moving them ahead is a safe
    # general fix, not just a one-off exclusion for "Spider Man".
    (re.compile(r"\bboys?\b", re.I), "Boys"),
    (re.compile(r"\bgirls?\b", re.I), "Girls"),
    (re.compile(r"\bmen\b", re.I), "Men"),
    (re.compile(r"\bman\b", re.I), "Men"),
    (re.compile(r"\bunisex\b", re.I), "Unisex"),
]
BOTH_WOMEN_RE = re.compile(r"\bwom[ae]n\b", re.I)
BOTH_MEN_RE = re.compile(r"\bm[ae]n\b", re.I)

# Anchored to the START of the title only — see guess_gender()'s own use of
# this for why an anchored check is needed in addition to GENDER_PATTERNS
# above (which scans anywhere in a merged blob, tags included). "'?s?"
# covers both "Men's"/"Women's" (the possessive form real titles use) and a
# bare plural "Mens"/"Womens" some stores use instead.
TITLE_GENDER_PREFIX_PATTERNS = [
    (re.compile(r"^women'?s?\b", re.I), "Women"),
    (re.compile(r"^boys?'?\b", re.I), "Boys"),
    (re.compile(r"^girls?'?\b", re.I), "Girls"),
    (re.compile(r"^men'?s?\b", re.I), "Men"),
    (re.compile(r"^unisex\b", re.I), "Unisex"),
]

# "kids"/"junior"/"toddler"/"infant" are age-only words — they don't specify
# boy vs girl on their own, unlike the explicit gender words in
# GENDER_PATTERNS above. Deliberately kept OUT of that list and checked only
# as a later fallback: a real Cambridge vendor "CAMBRIDGE JUNIOR" was
# matching this as a vendor-level "win outright" (per the vendor-priority
# fix below) and returning Unisex before ever getting to check that store's
# own tags/product_type, which said "BOYS SWEATER" explicitly — 712 real
# Cambridge Junior boys' products (sweaters, hoodies, polos, jeans, kurta
# pajama suits) were losing an explicit Boys signal to this weaker one and,
# since CATEGORY_TREE's Unisex node has no Western/Eastern branches, ending
# up with no leaf at all. A separate real product confirmed the age-only
# case still needs to resolve to *something*: "Junior Pajama Suit", sized
# 3-4 years through T1-T4, had no gender word anywhere and was defaulting to
# the adult store's Men fallback — hence still routing to Unisex, just only
# after every explicit-gender check (vendor AND full blob) has had a chance.
AGE_ONLY_RE = re.compile(r"\bkids?\b|\bjuniors?\b|\btoddlers?\b|\binfants?\b", re.I)

# See its call site in classify() for the full reasoning — an explicit
# "UNISEX" word in a product's own description, used only when a real
# "men" AND a real "women" word are both present in the same product's
# tags/title.
UNISEX_WORD_RE = re.compile(r"\bunisex\b", re.I)

# Kids age-range or toddler-code sizing ("3-4 years", "5-6 Year", "T1"-"T4")
# is a strong, direct kids signal even when no text says so anywhere — a
# real Cougar dress had exactly this (sizes 5-6Y/7-8Y/9-10Y) and no textual
# gender/age word at all, and defaulted straight to that store's adult
# "Men" fallback. Checked only as a last resort, after every textual signal
# has already had a chance to give a more specific answer.
KIDS_SIZE_RE = re.compile(r"^\s*\d{1,2}\s*-\s*\d{1,2}\s*y(?:ears?|rs?)?\s*$|^\s*t[1-4]\s*$", re.I)


def has_kids_sizing(p, is_graphql):
    try:
        if is_graphql:
            variants = [e["node"] for e in (p.get("variants") or {}).get("edges", [])]
            sizes = [so["value"] for v in variants for so in v.get("selectedOptions", [])
                     if so.get("name", "").lower() == "size"]
        else:
            options = p.get("options") or []
            size_idx = next((i for i, o in enumerate(options) if "size" in (o.get("name") or "").lower()), None)
            if size_idx is None:
                return False
            sizes = [v.get(f"option{size_idx+1}") for v in (p.get("variants") or [])]
        return any(s and KIDS_SIZE_RE.match(s) for s in sizes)
    except Exception:
        return False


def guess_gender(store, title, product_type, tags, vendor, p=None, is_graphql=False):
    # Vendor is checked in isolation FIRST and wins outright if it resolves
    # anything — it's consistently the most reliable, structured field
    # across every store we've seen (Outfitters/ONE/Cougar all encode
    # gender directly in it). Full-blob tags are freeform and noisy: a real
    # Cougar girls' dress had vendor "COUGAR GIRL (...)" but also a stray
    # "Women-Jacquard" tag (a shared fabric-batch label bleeding across
    # genders), and since "women" was checked before "girls" in the
    # combined blob, the noise won over the reliable signal. Vendor-first
    # avoids that class of bug regardless of pattern order.
    vendor_blob = (vendor or "").lower()
    for pattern, g in GENDER_PATTERNS:
        if pattern.search(vendor_blob):
            return g

    # A gender word at the very START of the title is a second, still-
    # reliable tier, checked before the noisy merged blob below — real bug
    # found auditing Bandana's "B-Fit" activewear line: vendor is just
    # "B-Fit" (no gender word, so the vendor-only check above doesn't
    # resolve anything), and Bandana tags EVERY B-Fit product — men's and
    # women's alike — with a shared cross-collection tag literally named
    # "B-Fit Men Women". Once that hits the merged blob below, "women"
    # matches and (per GENDER_PATTERNS' own deliberate women-before-men
    # ordering) wins outright, silently overriding a title that says
    # "Men's B-Fit CoolMax Joggers" in plain English. 53 of 56 "Men's
    # B-Fit..." products were filed under Women for exactly this reason.
    # A leading "Men's"/"Women's"/"Boys'"/"Girls'" is a deliberate, human-
    # authored declaration — same class of reliable signal as vendor,
    # unlike a tag whose own name happens to contain both gender words as
    # a bucket label. Anchored to the title's start specifically so this
    # can't collide with an incidental mid-title word (the existing
    # "Spider Man" problem GENDER_PATTERNS' own ordering already guards
    # against) the way an unanchored check would.
    title_start = (title or "").lower().strip()
    for pattern, g in TITLE_GENDER_PREFIX_PATTERNS:
        if pattern.match(title_start):
            return g

    # A single tag naming BOTH genders is a bucket label, not evidence
    # (Lama tags its men's items "collection-man-woman-overall"; Bandana's
    # "B-Fit Men Women"). With women checked before men, such a tag filed
    # 683 Lama men's products under Women (2026-11-02). Drop those tags.
    tags = ",".join(t for t in (tags or "").split(",")
                    if not (BOTH_WOMEN_RE.search(t) and BOTH_MEN_RE.search(t)))
    blob = f"{vendor or ''} {tags or ''} {product_type or ''} {title or ''}".lower()
    for pattern, g in GENDER_PATTERNS:
        if pattern.search(blob):
            return g

    # Age-only words (kids/junior/toddler/infant) are weaker evidence than an
    # explicit gender word, so they're only checked now — after vendor AND
    # the full blob have both had a chance to find something more specific.
    if AGE_ONLY_RE.search(vendor_blob) or AGE_ONLY_RE.search(blob):
        return "Unisex"

    if p is not None and has_kids_sizing(p, is_graphql):
        return "Unisex"

    return STORE_GENDER_DEFAULT.get(store, "Unisex")


# --- 2026-10-28 category review rules -------------------------------------
# From the manual review of the 1,950 products the enrichment model flagged
# (local-notes/catreview/FINDINGS.md) plus the whole-catalog scan for the new
# categories. Measured with db/eval_classify.py against the reviewed
# decisions in category_overrides; every change to products outside the
# review is listed there too.

# Brand words and typos rewritten to the word the rules already know
# ("TROSUER", "LOOSE FIT CASUAL TROUSE", "W/C", "CUFF LINKS", "Pocket Sqaure").
VOCAB_FIXES = [
    (re.compile(r"\btros?uers?\b|\btrouse\b", re.I), "trouser"),
    (re.compile(r"\bsqaures?\b", re.I), "square"),
    (re.compile(r"\bbeenies?\b", re.I), "beanie"),
    (re.compile(r"\bwaist\s*(?:coat|caot|cot)s?\b|\bw/c\b", re.I), "waistcoat"),
    (re.compile(r"\bcuff\s+links?\b", re.I), "cufflinks"),
    (re.compile(r"\bdungarees?\b|\brompers?\b|\boveralls\b", re.I), "jumpsuit"),
    (re.compile(r"\bun[\s-]?stitch\b", re.I), "unstitched"),
]


def _fix_vocab(text):
    for rx, word in VOCAB_FIXES:
        text = rx.sub(word, text or "")
    return text


# Not apparel: kept out of the catalog entirely, like gift cards.
NON_APPAREL_RE = re.compile(
    r"\btowels?\b(?!\s+terry)|\bcandles?\b|\binsoles?\b|\bshoe\s*horns?\b|\bshoehorns?\b"
    r"|\bshoe\s*(?:brush|polish|care|cleaner|tree)s?\b|\blip\s*balms?\b|\bnail\s*polish\b"
    r"|^\W*(?:\w+\s+){0,3}buttons\W*$",
    re.I,
)

# Accessories that had no leaf, checked on the title before the older
# accessory leaves. Order matters: a boxed "tie set" is a Gift Set before it
# is a Tie, and a "tie pin" is a pin, not a tie.
NEW_ACCESSORY_LEAVES = [
    ("Gift Set", re.compile(
        r"\bgift\s*(?:box|set)s?\b|\baccessor(?:y|ies)\s+box\b"
        r"|\btie\s*(?:&|and|with|\+)\s*(?:pocket\s*square|cufflinks?)\b"
        r"|\b(?:cufflinks?\s+)?tie\s+sets?\b", re.I)),
    ("Pins & Clips", re.compile(
        r"\b(?:lapel|tie|collar|coat)\s*pins?\b|\btie\s*(?:clips?|bars?)\b|\bcollar\s*bars?\b|\bbrooch(?:es)?\b", re.I)),
    ("Hair Accessories", re.compile(
        r"\bhair\s*(?:clips?|pins?|bands?|ties?|bows?|claws?|accessor\w*)\b|\bscrunchies?\b|\bheadbands?\b"
        r"|\bclaw\s*clips?\b", re.I)),
    ("Gloves", re.compile(r"\bgloves?\b|\bmittens?\b", re.I)),
    ("Suspenders", re.compile(r"\bsuspenders?\b", re.I)),
    # Bag and key charms (2026-11-01); a charm bracelet is jewellery.
    ("Keychain", re.compile(
        r"^(?!.*\b(?:bracelets?|necklaces?|earrings?|anklets?|pendants?|rings?|clogs?|detail)\b)"
        r".*(?:\bkey\s*rings?\b|\b(?:bag\s+|key\s*)?charms?\b)", re.I)),
]
# "Brooch Heels", "Crew Neck T-Shirt With Brooch Pin": the accessory word
# only describes a detail of a garment or shoe.
NEW_ACCESSORY_GUARD_RE = re.compile(
    r"\b(heels?|slides?|sandals?|shoes?|slip\s*ons?|sneakers?|shirts?|t-shirts?|tees?|tops?|dress(?:es)?"
    r"|trousers?|jeans?|kurt[ai]s?|jackets?|sweaters?)\b",
    re.I,
)

# Sleep and lounge sets. Checked before the Western bottomwear words, so
# "lounge trousers" and "pajama" land here (Uniworth's "Casual Pajama" line,
# Meme's "PJ SET"). An Eastern pajama worn with a kurta never reaches this:
# the Eastern block runs first.
NIGHTWEAR_RE = re.compile(
    r"\b(?:night\s*suits?|nightwear|night\s*dress(?:es)?|nightgowns?|nightshirts?|sleepwear"
    r"|sleep\s*suits?|pj\s*sets?|pajamas?|pyjamas?|loungewear|lounge\s*(?:wear|sets?|pants?|trousers?|shorts))\b",
    re.I,
)
SWIMWEAR_RE = re.compile(r"\bswim\w*\b|\bbikinis?\b|\bburkinis?\b", re.I)

# Bottoms worn with a kurta, sold on their own (Zellbury "Shalwar - 0011",
# Edenrobe "Cotton Pajama"). Any top or set word means it is part of a suit.
EASTERN_BOTTOM_RE = re.compile(r"\b(?:shalwars?|pajamas?|pyjamas?|churidars?|patiala)\b", re.I)
EASTERN_SET_WORD_RE = re.compile(
    r"\b(?:kameez|kurt[ai]s?|suits?|sets?|shirts?|tops?|dupattas?|[1-4]\s*-?\s*p(?:c|ieces?)?|pieces?)\b", re.I)

# Unstitched fabric sold by the metre or as a suit length (Diners' men's
# "Wash & Wear Fabric", product type "Fabric"), not a shirt.
FABRIC_RE = re.compile(r"\bfabrics?\b(?!ation)", re.I)

# Western words the old rules didn't know for trousers.
EXTRA_TROUSER_RE = re.compile(r"\b(?:slacks|culottes?|palazzos?|5\s*pockets?)\b", re.I)
# A store's own "Bottom" label (Zellbury "Bottom - 6002") with no top or set word.
BOTTOM_ONLY_RE = re.compile(
    r"^(?!.*\b(?:tops?|shirts?|sets?|suits?|co-?ords?|pieces?|[1-4]\s*-?\s*pc)\b).*\bbottoms?\b", re.I)

# A tee with a shirt collar is a polo (Equator "T Shirt Collar HS", product
# type "Polo"); a band or mandarin collar is not.
COLLARED_TEE_RE = re.compile(
    r"\b(?:t[\s-]?shirts?|tees?)\s+collar\b|\bcollar(?:ed)?\s+(?:t[\s-]?shirts?|tees?)\b", re.I)
NON_POLO_COLLAR_RE = re.compile(r"\b(?:band|ban|mandarin|stand|chinese|crew)\s+collar\b", re.I)

# Only these words justify "Shirt" when nothing more specific matched; the
# old rules used Shirt for anything unrecognised.
SHIRT_WORD_RE = re.compile(r"\b(?:shirts?|blouses?|shackets?|overshirts?|button[\s-]?downs?|henleys?)\b", re.I)
TOP_WORD_RE = re.compile(r"\btops?\b", re.I)

# 2026-11-01 rules round 1 (db/check_rules_vs_photos.py). Each is a general
# naming habit of Pakistani stores, not one store's wording.

# A top and a bottom named together ("Tee - Shorts", "Hoodie With Trouser",
# "Top Bottom Set") are sold as one set.
TWO_GARMENT_SET_RE = re.compile(
    r"\b(?:tees?|t-?shirts?|tops?|tanks?|polos?|hoodies?|sweatshirts?|shirts?)\s*(?:\bwith\b|\+|&|\band\b|-|/)\s*"
    r"(?:matching\s+)?(?:shorts?|trousers?|pants?|joggers?|bottoms?|skirts?)\b"
    r"|\b(?:tees?|t-?shirts?|tops?|tanks?|polos?)\s+(?:shorts?|trousers?|pants?|joggers?|bottoms?|skirts?)\s+sets?\b", re.I)
# Women's "2PC"/"3PC" and a store type like "1 Piece Stitched" mean an
# Eastern suit or kurti in this market. Men's "2PC Suit" is a formal suit
# and keeps going to the Western rules.
PIECE_COUNT_RE = re.compile(r"\b[1-4]\s*-?\s*(?:pcs?|pieces?)\b", re.I)
# The store's own type or description naming an Eastern garment, for a
# title that only says "Shirt" (Diners "Embroidered Shirt", type "1 Piece
# Stitched", described as a "ready-to-wear kurti").
STORE_EASTERN_TYPE_RE = re.compile(
    r"\b(?:eastern|ethnic|kurt[ai]s?|[1-4]\s*-?\s*(?:pcs?|pieces?)\s+(?:un)?stitched)\b", re.I)
DESC_KURTI_RE = re.compile(r"\b(?:kurt[ai]s?)\b", re.I)
WESTERN_TITLE_GARMENT_RE = re.compile(
    r"\b(?:jeans?|denim|t-?shirts?|tees?|hoodies?|sweatshirts?|sweaters?|cardigans?|jackets?|blazers?|coats?|polos?"
    r"|shorts?|skirts?|dress(?:es)?|maxis?|frocks?|gowns?|capes?|jumpsuits?|joggers?|trousers?|pants?|co-?ords?"
    r"|tracksuits?|vests?|tanks?|swim\w*|bikinis?)\b", re.I)
# "Upper"/"Zipper" is a zip-up layer: a hood makes it a hoodie, knit a
# sweater; otherwise it is a jacket.
UPPER_WORD_RE = re.compile(r"\b(?:uppers?|zippers?|zip[\s-]?ups?)\b", re.I)
# In menswear a plain "Coat" is a tailored coat, i.e. a blazer. Long and
# winter coats keep their own words.
NOT_BLAZER_COAT_RE = re.compile(
    r"\b(?:long|over|top|rain|pea|trench|puffer|duffle|parka|car|lab|winter|hooded|quilted|padded|wool(?:len)?|fur|teddy)\s*coats?\b"
    r"|\b(?:overcoats?|raincoats?|peacoats?|topcoats?)\b", re.I)
# Heels whose own text describes an open shoe.
OPEN_SHOE_RE = re.compile(
    r"\bstrap|\bsandals?\b|\bsling\s*backs?\b|\bmules?\b|\bpeep[\s-]?toe|\bopen[\s-]toe|\bthong\b|\bcriss[\s-]?cross", re.I)
# "Dress" as the last garment word decides ("Tunic Dress", "Sweater Dress");
# "Dress Shirt"/"Dress Pant"/"Dress Socks" have another garment after it.
DRESS_HEAD_RE = re.compile(
    r"\b(?:dress(?:es)?|frocks?|gowns?)\b(?!.*\b(?:shirts?|tops?|t-?shirts?|tees?|trousers?|pants?|socks?|shoes?|belts?|shorts?)\b)",
    re.I)
FRAGRANCE_DESC_RE = re.compile(r"\b(?:fragrance|perfume|eau\s+de|cologne)\b", re.I)


def _classify_rules(store, p, title, product_type, tags, vendor, description):
    title = _fix_vocab(title)
    product_type = _fix_vocab(product_type)
    if (NON_APPAREL_RE.search(title) or NON_APPAREL_RE.search(product_type or "")) and not GARMENT_NOUN_RE.search(title):
        return None  # towels, candles, shoe care, cosmetics: not apparel ("Towel Tee" is a tee)
    if GIFT_CARD_RE.search(title):
        return None  # excluded entirely, not just unbrowsable — not a product at all
    if TEST_PRODUCT_RE.search(title) or SHOPPING_BAG_RE.search(title) or SHOPPING_BAG_RE.search(product_type or ""):
        return None  # QA placeholder or checkout packaging bag, not real merchandise
    gender = guess_gender(store, title, product_type, tags, vendor, p=p, is_graphql=(store == "cougar"))
    # A product tagged for BOTH genders simultaneously (e.g. Bandana's
    # "RUH" capsule line: the exact same product ID appears in both the
    # ruh-men and ruh-women collections, tagged "RUH Men" AND "RUH Women"
    # at once) with an explicit "UNISEX" word in its own description is a
    # genuinely unisex line, not a gendering bug. guess_gender()'s own
    # GENDER_PATTERNS checks "women" ahead of "men"/"unisex" (for a
    # different, deliberate reason — see that list's own comment), so
    # without this it would silently resolve to Women just because a
    # "women" word happens to be present in tags, ignoring the equally-
    # present "men" word and the description's own explicit declaration.
    # Scoped narrowly: only overrides when a real "men" AND a real
    # "women" word are BOTH present (not just any stray "unisex" mention
    # elsewhere) — this never touches a product that only ever names one
    # gender.
    gender_words_blob = f"{tags or ''} {title or ''}".lower()
    if (
        UNISEX_WORD_RE.search(description or "")
        and re.search(r"\bwomen\b|\bwoman\b", gender_words_blob)
        and re.search(r"\bmen\b|\bman\b", gender_words_blob)
    ):
        gender = "Unisex"
    blob = f"{product_type} {title}".lower()
    # Title-only view of the same blob — used wherever product_type
    # conflicts with what the title itself says (see its uses below: the
    # joggers-vs-footwear check, and the bottomwear title-first check
    # further down).
    title_blob = (title or "").lower()

    # A perfume titled only by its name ("Elixir", "Noir") is still known by
    # its tags or the first lines of its description.
    if FRAGRANCE_RE.search(blob) or (not GARMENT_NOUN_RE.search(title_blob) and (
            FRAGRANCE_RE.search(tags or "") or FRAGRANCE_DESC_RE.search((description or "")[:160]))):
        return dict(gender=gender, branch="Fragrance & Beauty", sub=None, leaf="Perfume",
                    style="not_applicable", construction="not_applicable")
    vest_blob = f"{vendor or ''} {product_type or ''} {title or ''} {description or ''}".lower()
    is_underwear_vest = (
        VEST_RE.search(blob)
        and VEST_UNDERWEAR_SIGNAL_RE.search(vest_blob)
        and not VEST_OUTERWEAR_SIGNAL_RE.search(vest_blob)
    )
    # A store's "Lingerie"/"Innerwear" type doesn't outrank a title that
    # names a top ("SILK LACE CAMISOLE TOP", "CROPPED STRAPPY CAMI").
    title_names_top = re.search(r"\b(?:tops?|camis?|tanks?)\b", title_blob) and not UNDERWEAR_RE.search(title_blob)
    if ((UNDERWEAR_RE.search(blob) and not title_names_top) or is_underwear_vest) and not EASTERN_RE.search(blob):
        return dict(gender=gender, branch="Accessories", sub=None, leaf="Underwear",
                    style="western", construction="not_applicable")
    # Ties, cufflinks, pocket squares, suspenders and tie/collar pins are
    # menswear; with no gender stated they are Men's, not Unisex.
    def _menswear_gender(leaf):
        if gender == "Unisex" and (leaf in ("Tie", "Cufflink", "Pocket Square", "Suspenders")
                                   or (leaf == "Pins & Clips" and re.search(r"\b(?:tie|collar|lapel)\b", title_blob))):
            return "Men"
        return gender

    if not NEW_ACCESSORY_GUARD_RE.search(title_blob):
        for leaf, rx in NEW_ACCESSORY_LEAVES:
            if rx.search(title_blob):
                return dict(gender=_menswear_gender(leaf), branch="Accessories", sub=None, leaf=leaf,
                            style="western", construction="not_applicable")
    accessory_blob = strip_garment_detail(blob)
    if ACCESSORY_RE.search(accessory_blob) and not EASTERN_RE.search(blob):
        # The keyword here must be the actual word ROOT that appears in real
        # titles, not the leaf's slug — "Jewelry" the category never
        # literally appears in a title ("Jewel"/"Jewellery" do), and the
        # same mismatch existed for Sunglasses/Socks. Using the slug as the
        # search string meant these silently always fell to the "Bag"
        # default instead of ever matching.
        # Every pattern here is word-boundary-anchored (\b...\b), matched
        # against the blob AS-IS rather than with spaces stripped out — a
        # real example ("Women Printed Cape Shawl") showed why: stripping
        # spaces first turns "printed cape shawl" into "printedcapeshawl",
        # and a bare substring search for "cap" then matches inside "cape"
        # with no word boundary to stop it, resolving to "Cap" instead of
        # "Shawl". Checked against the TITLE first, then the full blob
        # (product_type included) only as a fallback — a real example
        # ("Soccer School Backpack", "Lion Themed Pencil Case") had
        # product_type "BAGS & WALLETS" (a store's own catch-all bucket
        # naming BOTH nouns), and since "wallet" was checked before "bag"
        # the whole thing resolved to "Wallet" even though the actual item
        # is a bag. "Bag" is checked ahead of "Wallet" in the blob-fallback
        # pass for the same reason.
        _KEYWORD_LEAVES = [
            ("Belt", re.compile(r"\bbelts?\b")),
            # "waist" excluded the same way "front"/"hair" already were: a
            # real product, "TEXTURED WAIST TIE TOP" (Breakout, Women), is
            # a top with a self-tie waist closure, not a necktie
            # accessory — CATEGORY_TREE has no Tie leaf for Women at all
            # (only Men/Unisex), so this was stranding on the bare
            # Accessories branch node, caught by the branch-level-orphan
            # audit.
            # "ties" (plural) added 2026-10-28: Royal Tag's product type "TIES".
            ("Tie", re.compile(r"(?<!front\s)(?<!hair\s)(?<!waist\s)\bties?\b(?!-)(?!\s+up\b)(?!\s*(?:[&]|and)?\s*(?:dye|die)\b)")),
            # "hat"/"beanie" fold into the same Cap leaf — no separate Hat
            # leaf exists in CATEGORY_TREE, and 34 real "Hat" + 129 real
            # "Beanie" titles/product_types ("Boonie Hat", "Bucket Hat",
            # "Ribbed Beanie") were landing in the generic Shirt default.
            ("Cap", re.compile(r"\bcaps?(?!\s*sleeves?)\b|\bhats?\b|\bbeanies?\b")),
            ("Cufflink", re.compile(r"\bcufflinks?\b")),
            ("Watch", re.compile(r"(?<!black)(?<!black\s)\bwatch(?:es)?\b(?!\s*maker)")),
            ("Sunglasses", re.compile(r"\bsunglass(?:es)?\b|\beyewear\b")),
            # "bracelet"/"necklace"/"earring" fold into the same Jewelry
            # leaf — no separate leaf exists for any of them, and 86/40/
            # 230 real products respectively were landing in Shirt.
            ("Jewelry", re.compile(r"\bjewel(?:l?ery|ry)?\b|\bbracelets?\b|\bnecklaces?\b|\bearrings?\b")),
            # "backpack"/"clutch" folded into the same Bag leaf 2026-08-29 —
            # a real example, Outfitters' "Multi-Functional Backpack"/"Faux
            # Leather Backpack" (product_type literally "WALLETS", a store
            # mislabel) and Breakout's "CROCHET CLUTCH" (product_type
            # "WALLET"), had no keyword of their own so the title-first check
            # below found nothing and fell back to the mislabeled
            # product_type's "wallet(s)" match instead — same
            # title-vs-product_type conflict class as the String Sports
            # Shoes/Basic Denim Jacket fixes elsewhere in this file.
            ("Bag", re.compile(r"(?<!paper[\s-])(?<!paper)\bbags?\b|\bhandbags?\b|\bbackpacks?\b|\bclutch(?:es)?\b|\btotes?\b|\bpurses?\b|\bcrossbody\b")),
            ("Wallet", re.compile(r"\bwallets?\b")),
            # The title's "scarf" beats a store type that files scarves
            # under shawls (Cougar "Jacquard Knit Scarf", "Women Knitted Shawl").
            ("Scarf", re.compile(r"\bscar(?:f|ves)\b|\bmufflers?\b")),
            ("Shawl", re.compile(r"\bshawl\b(?!\s*collar)")),
            ("Socks", re.compile(r"\bsocks?(?!-fit\b)\b")),
            ("Keychain", re.compile(r"\bkey\s*chains?\b")),
            # Added 2026-08-29 — 323 real Men's/7 Unisex pocket squares
            # (Uniworth "100% Silk Pocket Square", Cambridge/Equator formal
            # accessories) had no keyword at all and were falling to Shirt.
            ("Pocket Square", re.compile(r"\bpocket\s*squares?\b")),
        ]
        title_only = strip_garment_detail((title or "").lower())
        leaf = next((n for n, rx in _KEYWORD_LEAVES if rx.search(title_only)), None)
        if leaf is None:
            leaf = next((n for n, rx in _KEYWORD_LEAVES if rx.search(accessory_blob)), "Bag")
        return dict(gender=_menswear_gender(leaf), branch="Accessories", sub=None, leaf=leaf,
                    style="western", construction="not_applicable")
    # Uses accessory_blob (the with-detail-stripped version), not the raw
    # blob — see GARMENT_DETAIL_RE's own comment: "CITY DRESS WITH SCARF
    # DETAIL" is a real dress, not a standalone scarf, and without this the
    # stripping done above for the ACCESSORY_RE check never reaches this
    # separate SCARF_RE check right after it.
    # A dupatta sold on its own has its own leaf since 2026-10-28. With a
    # shirt or a piece count it is part of a suit ("Shirt Dupatta"), so it
    # skips this and goes on to the Eastern rules.
    title_dupatta = re.search(r"\bdu+pp?attas?\b", title_blob)
    dupatta_in_set = title_dupatta and EASTERN_SET_WORD_RE.search(re.sub(r"\bdu+pp?attas?\b", " ", title_blob))
    if (SCARF_RE.search(accessory_blob) and not OTHER_EASTERN_GARMENT_RE.search(blob)
            and not UNSTITCHED_RE.search(blob) and not dupatta_in_set):
        if title_dupatta:
            return dict(gender="Girls" if gender in ("Girls", "Boys") else "Women", branch="Eastern",
                        sub="Stitched", leaf="Dupatta", style="eastern", construction="ready_to_wear")
        return dict(gender=gender, branch="Accessories", sub=None, leaf="Scarf",
                    style="western", construction="not_applicable")
    # A bare "waistcoat" is one of EASTERN_RE's own trigger words (a real
    # koti/traditional waistcoat worn over a shalwar kameez), but several
    # brands also sell a Western fashion vest/gilet under the same word —
    # real examples: Outfitters' "Faux Leather Cropped Waistcoat"
    # (product_type "OUTERWEAR", tags "Jackets"/"Outerwear"/"vest"),
    # Uniworth's own "Western Waistcoat" line (11 products, the brand's own
    # naming), Charcoal's denim waistcoats, Lama's "SHORT PINSTRIPE
    # WAISTCOAT"/"WAISTCOAT WITH POCKETS" (product_type "BLAZERS"). None of
    # these pair the word with any Eastern companion word anywhere — a
    # real false positive was caught and excluded before shipping this:
    # Edenrobe's "Cotton Waistcoat Suit" mentions "Blazer Suiting
    # Fabric"/"Contrast Blazer Collar" as a STYLE DETAIL on what its own
    # description confirms is a "Cotton Satin Kurta Pajama" — genuinely
    # Eastern despite the word "blazer", so the Western signal only wins
    # when no kurta/kurti/shalwar/kameez/koti/Mashriq word is also present.
    # Routes to the "Vest" leaf (added 2026-09-01 — see CATEGORY_TREE's own
    # comment) rather than Jacket: a Western "waistcoat" IS a vest, just a
    # different regional word for the identical sleeveless garment (same
    # real-world item as Uniworth's own "Western Waistcoat" line naming
    # confirms) — not a style variant of a jacket, which has sleeves.
    if "waistcoat" in blob:
        waistcoat_signal_blob = f"{blob} {tags} {description}".lower()
        if WESTERN_WAISTCOAT_RE.search(waistcoat_signal_blob) and not EASTERN_WAISTCOAT_COMPANION_RE.search(waistcoat_signal_blob):
            return dict(gender=gender, branch="Western", sub="Upperwear", leaf="Vest",
                        style="western", construction="ready_to_wear")
    is_fabric = FABRIC_RE.search(blob) and not GARMENT_NOUN_RE.search(title_blob)
    # 2026-11-01: a women's piece-count set ("Printed 2PC"), or a title that
    # only says "Shirt" while the store's own type or description names an
    # Eastern garment, is Eastern. Western garment words in the title win.
    western_title = WESTERN_TITLE_GARMENT_RE.search(title_blob)
    womens_piece_set = gender in ("Women", "Girls") and PIECE_COUNT_RE.search(title_blob) and not western_title
    shirt_only_title = (not western_title and not re.search(r"\b(?:tops?|blouses?)\b", title_blob)
                        and not FOOTWEAR_RE.search(blob))
    store_says_eastern = shirt_only_title and (
        STORE_EASTERN_TYPE_RE.search(product_type or "")
        or (re.search(r"\bshirts?\b", title_blob) and DESC_KURTI_RE.search((description or "")[:300])))
    if (EASTERN_RE.search(blob) or UNSTITCHED_RE.search(blob) or SHIRT_TROUSER_SET_RE.search(blob) or is_fabric
            or womens_piece_set or store_says_eastern or PRINCE_SET_RE.search(title_blob)):
        construction = "unstitched_fabric" if UNSTITCHED_RE.search(blob) or is_fabric else "ready_to_wear"
        sub = "Unstitched" if construction == "unstitched_fabric" else "Stitched"

        # Broadened to also catch the bare "-3P"/"-2P" SKU-suffix convention
        # (no trailing "c") that several Edenrobe titles use, on top of the
        # "3PC"/"3-Piece" phrasing the original pattern already covered, AND
        # a literal SPACE between the digit and "Piece" — real bug found
        # auditing Zellbury's Women's Unstitched catalog: 1,796 real
        # products titled "Shirt Shalwar Dupatta" (a genuine 3-piece
        # ensemble) whose OWN description says "Buy 3 Piece Printed Lawn
        # Shirt Shalwar Dupatta..." / "This elegant 3-piece set...", but
        # `\b([1-4])-?p...` requires the digit and "p" adjacent (only an
        # optional HYPHEN between them, never a space) and only ever
        # checked `blob` (title+product_type), never the description at
        # all — so this never matched, on either count, and every one of
        # these fell through to the named-piece count below instead.
        piece_count = None
        piece_count_blob = f"{blob} {description or ''}".lower()
        m = re.search(r"\b([1-4])[\s-]?p(?:c|ieces?)?\b", piece_count_blob)
        if m:
            piece_count = int(m.group(1))
        elif sub == "Unstitched":
            # No explicit count stated — many unstitched listings only name
            # their constituent pieces ("Shirt Trouser Dupatta") rather than
            # giving a number. Counting the named pieces is a real, direct
            # signal, not a guess, and lands on the same 1/2/3-Piece leaves.
            # "shalwar" added alongside "trouser" — the same Zellbury audit
            # above: even without the description-based fix, "Shirt Shalwar
            # Dupatta" was only counting 2 (shirt, dupatta) because
            # "shalwar" — the single most common Eastern bottom-piece word,
            # more common here than "trouser" — was never in this list at
            # all, undercounting a real 3-piece set to "2-Piece".
            named = sum(1 for kw in ("shirt", "trouser", "shalwar", "dupatta", "shawl") if kw in blob)
            if named:
                piece_count = min(named, 3)

        if piece_count and sub == "Unstitched":
            leaf = f"{piece_count}-Piece"
        elif "saree" in blob or "sari" in blob:
            # Checked before the Unstitched short-circuit below: unlike
            # Kurta/Kurti/Waistcoat/Sherwani, "Saree" is a real leaf under
            # Unstitched too (unstitched saree fabric is sold as such).
            leaf = "Saree"
        elif sub == "Unstitched":
            # Unstitched fabric doesn't have a finished-garment "type" the
            # way a stitched item does — a "Kurta"/"Waistcoat"/"Sherwani"
            # word in the title just describes what the fabric COULD become,
            # and none of those are real leaves under any gender's
            # Unstitched sub-tree (only piece-count and this "Suit"
            # catch-all are). A real example, "UNSTITCHED KURTA COLLECTION"
            # (Mashriq), was resolving to leaf="Kurta" — a Stitched-only
            # leaf name — and getting stranded on the bare Eastern branch
            # node since no Unstitched tree has ever defined it.
            leaf = "Suit"
        elif EASTERN_BOTTOM_RE.search(title_blob) and not EASTERN_SET_WORD_RE.search(title_blob):
            leaf = "Shalwar & Pajama"  # sold on its own, to wear with a kurta
        else:
            # KURTA_COMBO_RE/sherwani/waistcoat/sharara-etc/kurti/kurta/
            # SHIRT_TROUSER_SET_RE, in that order — see _eastern_stitched_leaf.
            leaf = _eastern_stitched_leaf(blob)
            # Nothing named the pieces ("Printed 2PC", "Embroidered Shirt"):
            # a piece count of 2+ is a kurta set, one piece is a kurti/kurta.
            if leaf == "Shalwar Kameez" and not re.search(r"\bshalwar|\bkameez|\bdupatta|\btrouser|\bpajama", blob):
                if (piece_count and piece_count >= 2) or re.search(r"\b(?:suits?|sets?)\b", title_blob):
                    leaf = "Kurta Set"
                elif piece_count == 1 or store_says_eastern:
                    leaf = "Kurti" if gender in ("Women", "Girls") else "Kurta"
        if leaf == "Kurti" and gender in ("Men", "Boys"):
            # "Kurti" never applies to a boy/man in this catalog's own
            # taxonomy (CATEGORY_TREE only defines a Kurti leaf under
            # Women/Girls) — a real example (Diners/Sohaye "Teens Kurti")
            # had the compound tag "girls-western&boys-eastern-western",
            # which contains the literal word "boys" and won gender
            # resolution over the item's own clean "girls-eastern" tag. The
            # garment-name signal here is more reliable than that tag
            # collision, so it corrects gender instead of leaving a girls'
            # garment mis-gendered.
            gender = "Girls" if gender == "Boys" else "Women"
        return dict(gender=gender, branch="Eastern", sub=sub, leaf=leaf,
                    style="eastern", construction=construction, piece_count=piece_count)
    # default: Western
    # Checked ahead of TROUSER_RE/the generic sweat* fallback below:
    # "sweatpant(s)" is one compound word, so \bpants?\b never matches it
    # (no word boundary between "sweat" and "pant"), and it would otherwise
    # fall all the way through to the bare "sweat" in blob check further
    # down and get filed as a Sweatshirt — a bottomwear item landing in
    # upperwear.
    # A store's product_type can be a merged/shared collection bucket that
    # names more than one thing — real example, Cougar's `productType:
    # "Men Joggers Shoes"` (5 real products, e.g. "Mesh Lace-Up Trainers",
    # "Suede Mesh Trainers") — with no "jogger"/"sweatpant"/"track pant"
    # word anywhere in the TITLE, just a clearly footwear one ("Trainers").
    # Same "title is more reliable than a shared product_type bucket"
    # reasoning as the Basic Barrel Jeans fix below: only trust the
    # joggers match here if the title itself doesn't look like footwear
    # instead. A genuine jogger that also says "Trainers" in its own
    # title ("Men Trainers Jogger", Engine Clothing — "trainers" used as
    # a style qualifier, not the shoe) is unaffected, since its title
    # itself contains "Jogger".
    # 2026-10-28: sleep/lounge and swim got their own groups. Checked first
    # among the Western rules, since "lounge trousers"/"swim shorts" would
    # otherwise be claimed by the bottomwear words below.
    # A plain pajama the store calls ethnic/traditional is the Eastern bottom.
    if (EASTERN_BOTTOM_RE.search(title_blob) and not EASTERN_SET_WORD_RE.search(title_blob)
            and re.search(r"\b(?:ethnic|traditional|eastern|mashriq)\b", f"{blob} {tags or ''}".lower())):
        return dict(gender=gender, branch="Eastern", sub="Stitched", leaf="Shalwar & Pajama",
                    style="eastern", construction="ready_to_wear")
    # The store's product type ("Sleepwear For Women") counts when the title
    # names no specific garment, only a set ("CO-ORD SET FOR GIRLS").
    title_garment = GARMENT_NOUN_RE.search(re.sub(r"\bco-?ords?\b", " ", title_blob))
    if NIGHTWEAR_RE.search(title_blob) or (NIGHTWEAR_RE.search(blob) and not title_garment):
        return dict(gender=gender, branch="Western", sub="Sleepwear", leaf="Nightwear & Loungewear",
                    style="western", construction="ready_to_wear")
    if SWIMWEAR_RE.search(title_blob):
        return dict(gender=gender, branch="Western", sub="Swimwear", leaf="Swimwear",
                    style="western", construction="ready_to_wear")
    if TWO_GARMENT_SET_RE.search(title_blob):
        return dict(gender=gender, branch="Western", sub="Suits & Sets", leaf="Co-ord Set",
                    style="western", construction="ready_to_wear")
    title_says_footwear_not_joggers = FOOTWEAR_RE.search(title_blob) and not JOGGERS_RE.search(title_blob)
    # The title's own garment word beats a store's bucket product type: Furor
    # files straight "Pleated Interlock Trousers" under "Men Jogger Pants".
    # Only the explicit word "trousers": a bare "pants" says nothing against
    # the store's jogger label.
    title_says_trouser_not_joggers = re.search(r"\btrousers?\b", title_blob) and not JOGGERS_RE.search(title_blob)
    # "Jogger Jeans" are jeans with a jogger cuff: the last garment word decides.
    title_says_trouser_not_joggers = title_says_trouser_not_joggers or re.search(
        r"\bjoggers?\s+(?:\w+\s+)?jeans?\b", title_blob)
    if JOGGERS_RE.search(blob) and not title_says_footwear_not_joggers and not title_says_trouser_not_joggers:
        return dict(gender=gender, branch="Western", sub="Bottomwear", leaf="Joggers",
                    style="western", construction="ready_to_wear")
    if re.search(r"\btights?\b|\bleggings?\b", blob):
        return dict(gender=gender, branch="Western", sub="Bottomwear", leaf="Tights",
                    style="western", construction="ready_to_wear")
    # Bare "denim" just names a FABRIC — it describes jeans/shorts most of
    # the time, but real examples showed it just as often describing an
    # upperwear item or dress made of (or trimmed with) denim: "DENIM
    # JACKET", "Denim Shirt", "Embroidered Denim Dress", "DENIM COLLAR POLO"
    # were all resolving to Jeans purely because "denim" appeared anywhere
    # in the title. A real bottomwear word (jean/trouser/short) is checked
    # on its own via TROUSER_RE/SHORTS_RE regardless — this guard only
    # gates the bare-"denim"-with-no-other-signal fallback.
    # "vest" and plural forms ("jackets", not just singular "jacket") added
    # after a real example: Furor's "Hooded Denim Vest" (product_type
    # literally "Men Jackets", plural — the original singular-only
    # "jacket" in this exclusion list never matched it) was resolving to
    # Jeans purely because of "denim" in the title, same collision class
    # as "DENIM JACKET"/"Denim Shirt" above.
    # "denim terry"/"terry denim" is a real fabric-line name (Bandana.pk's
    # "Denim Terry" collection) meaning terry cloth with a denim-look
    # print, NOT actual denim — its own description confirms this
    # explicitly: "the appearance of classic denim with the ease and
    # softness of terry fabric". A real "Men's Denim Terry Pants" would
    # otherwise wrongly resolve Jeans purely off the bare word "denim"
    # (shorts/joggers variants of the same line are unaffected, since
    # SHORTS_RE/JOGGERS_RE already win ahead of this bare-denim fallback).
    bare_denim = re.search(r"\bdenim\b", blob) and not re.search(
        r"\b(jackets?|shirts?|shackets?|overshirts?|coats?|dress(?:es)?|polos?|collars?|hoodies?|tees?|t-shirts?|tops?|sweatshirts?|vests?)\b",blob
    ) and not re.search(r"\bdenim\s+terry\b|\bterry\s+denim\b", blob)
    # Checked against the TITLE first, then the full blob (product_type
    # included) only as a fallback — same precedent as the Accessories
    # leaf lookup above. A real example, ONE Be-One's "Basic Barrel Jeans",
    # has Shopify's own product_type field set to the literal string
    # "Shorts" (a store-side mislabel — tags say "Women Bottoms-Jeans"/
    # "WOMEN_DENIM_JEANS_TWILL_PANTS", nothing about the item is actually
    # short), and since the full blob included that mislabeled
    # product_type, SHORTS_RE won over the title's own explicit "Jeans"
    # every time. The title is what the store is actually calling the
    # item; product_type is a coarser internal bucket that isn't always
    # accurate, so a bottomwear signal in the title wins outright before
    # product_type is even consulted.
    bare_denim_title = re.search(r"\bdenim\b", title_blob) and not re.search(
        r"\b(jackets?|shirts?|shackets?|overshirts?|coats?|dress(?:es)?|polos?|collars?|hoodies?|tees?|t-shirts?|tops?|sweatshirts?|vests?)\b",title_blob
    ) and not re.search(r"\bdenim\s+terry\b|\bterry\s+denim\b", title_blob)
    # The title's "Shorts" beats a shared "Shorts and Skirts" store type.
    if SKIRT_RE.search(title_blob) or (SKIRT_RE.search(blob) and not SHORTS_RE.search(title_blob)):
        return dict(gender=gender, branch="Western", sub="Bottomwear", leaf="Skirt",
                    style="western", construction="ready_to_wear")
    if (EXTRA_TROUSER_RE.search(blob) or BOTTOM_ONLY_RE.search(title_blob)) and not (
            SHORTS_RE.search(title_blob) or re.search(r"\bjeans?\b|\bdenim\b", blob)):
        return dict(gender=gender, branch="Western", sub="Bottomwear", leaf="Trouser",
                    style="western", construction="ready_to_wear")
    if TROUSER_RE.search(title_blob) or SHORTS_RE.search(title_blob) or bare_denim_title:
        src = title_blob
        leaf = "Shorts" if SHORTS_RE.search(src) else "Cargo Trouser" if CARGO_RE.search(src) else "Jeans" if re.search(r"\bjeans?\b", src) or bare_denim_title else "Trouser"
        return dict(gender=gender, branch="Western", sub="Bottomwear", leaf=leaf,
                    style="western", construction="ready_to_wear")
    # Same "title beats a conflicting product_type" reasoning as the
    # title-first block above, applied the other direction: a real
    # example, ONE (Be-One)'s "String Sports Shoes" (product_type
    # literally "Jeans" — a store mislabel; tags say "Girls Footwear"/
    # "KIDS_FOOTWEAR", confirming it's a shoe), was resolving to Jeans
    # purely because product_type contributed "jeans" to the blob and
    # this check runs before the footwear one below. If the title itself
    # clearly says footwear and has no bottomwear word of its own, trust
    # that over a bottomwear word that only exists in product_type.
    title_says_footwear_not_bottomwear = FOOTWEAR_RE.search(title_blob) and not (
        TROUSER_RE.search(title_blob) or SHORTS_RE.search(title_blob) or bare_denim_title
    )
    # Same reasoning again, this time for Jacket: ONE (Be-One)'s "Basic
    # Denim Jacket" has product_type literally "Jeans" (a store mislabel
    # — the title unambiguously names a jacket, not jeans) and was
    # resolving to Jeans for the identical reason as String Sports Shoes
    # above.
    title_says_jacket_not_bottomwear = re.search(r"\b(jackets?|blazers?|coats?)\b", title_blob) and not (
        TROUSER_RE.search(title_blob) or SHORTS_RE.search(title_blob) or bare_denim_title
    )
    if (TROUSER_RE.search(blob) or SHORTS_RE.search(blob) or bare_denim) and not (
        title_says_footwear_not_bottomwear or title_says_jacket_not_bottomwear
    ):
        # Shorts checked ahead of the jean/denim check: "Denim Shorts" is a
        # shorts garment made of denim fabric, not a pair of jeans (which
        # implies full length) — denim alone shouldn't outrank an explicit
        # "shorts" in the same title.
        leaf = "Shorts" if SHORTS_RE.search(blob) else "Cargo Trouser" if CARGO_RE.search(blob) else "Jeans" if re.search(r"\bjeans?\b", blob) or bare_denim else "Trouser"
        return dict(gender=gender, branch="Western", sub="Bottomwear", leaf=leaf,
                    style="western", construction="ready_to_wear")
    if FOOTWEAR_RE.search(blob):
        # Every gender has a Sandals leaf since 2026-10-28 (it was Women only,
        # so men's slides and kids' sandals were filed as Shoes).
        footwear_leaf = "Sandals" if SANDAL_LEAF_RE.search(blob) else "Shoes"
        # Heels and flats whose own text describes straps or an open toe are
        # sandals ("Criss-Cross Flats"); a monk strap is a closed shoe.
        if (footwear_leaf == "Shoes" and re.search(r"\b(?:heels?|flats?|wedges?)\b", title_blob)
                and not re.search(r"\b(?:monk|ballet|ballerinas?|mary\s*janes?)\b", title_blob)
                and OPEN_SHOE_RE.search(f"{title_blob} {(description or '')[:300]}")):
            footwear_leaf = "Sandals"
        return dict(gender=gender, branch="Western", sub="Footwear", leaf=footwear_leaf,
                    style="western", construction="not_applicable")
    # jumpsuit/playsuit/bodysuit are one-piece garments, not a coordinated
    # SET — checked ahead of the co-ord/suit regex below so the fixed
    # `\bsuits?\b` boundary (see JUMPSUIT_RE's own comment) never has to
    # decide whether a compound word counts; these get their own leaf
    # outright.
    if JUMPSUIT_RE.search(blob):
        return dict(gender=gender, branch="Western", sub="Upperwear", leaf="Jumpsuit",
                    style="western", construction="ready_to_wear")
    # An athletic tracksuit is a distinct product from a fashion/loungewear
    # Co-ord Set — checked ahead of the co-ord/suit regex below so it gets
    # its own leaf outright rather than falling into the generic one.
    # Excludes Furor's "Tracksuit <single garment>" collection-naming
    # pattern (see TRACKSUIT_SINGLE_GARMENT_RE) — those fall through to the
    # normal Jacket/Hoodie/Sweatshirt resolution further down instead.
    if TRACKSUIT_RE.search(blob) and not TRACKSUIT_SINGLE_GARMENT_RE.search(blob):
        return dict(gender=gender, branch="Western", sub="Suits & Sets", leaf="Tracksuit",
                    style="western", construction="ready_to_wear")
    # Broadened 2026-08-29 to also catch a bare piece-count ("2PC"/"3 PC"/
    # "3-Piece") or "combo" naming a coordinated set with no "suit"/"co-ord"
    # word at all — real example, Diners' entire Women's/Girls'/Boys' "N
    # Piece Stitched"/"Boys Combo" lines (real body_html confirms these are
    # genuine "ready-to-wear 2-piece set"/"Top Bottom Set" listings, not
    # Eastern ensembles — EASTERN_RE/UNSTITCHED_RE have both already failed
    # to match by this point in the function), ~970 real products across
    # Women/Girls/Boys/Teens/Infant sub-lines, were falling to the generic
    # Shirt default. Requires the literal "pc"/"piece(s)" suffix, NOT a bare
    # trailing "p" — Edenrobe's "Varsity Jacket - EBTJP5-001-2P" is a SKU
    # suffix, not a piece count, and would otherwise be wrongly pulled out
    # of Jacket. "combo" excludes an immediately-following Upperwear garment
    # noun — Equator's "Green & Black Combo Hoodie"/"Tri-Color Combo Tee" use
    # "combo" to describe a COLOR combination, not a multi-piece set, and
    # must keep resolving to their own garment leaf.
    #
    # 2026-08-30 (Co-ord Set audit) — the original `\bco-?ord|suit\b`
    # alternation had a precedence bug: it parsed as `(\bco-?ord)|(suit\b)`,
    # so the right-hand alternative had NO leading `\b` and matched "suit"
    # as a bare suffix inside ANY word — jumpsuit/playsuit/bodysuit (now
    # routed above) were all wrongly caught by this. Fixed to bound both
    # sides (`\bsuits?\b`), with pantsuit/nightsuit — real compound words
    # that legitimately ARE 2-piece sets (verified catalog-wide:
    # bodysuit/jumpsuit/nightsuit/playsuit/suit(s)/tracksuit is the
    # complete real list; "pantsuit" has zero real occurrences but is kept
    # defensively) — allowed back in explicitly. "tracksuit" is
    # deliberately NOT in this list — it has its own dedicated, earlier
    # check (TRACKSUIT_RE) that already handles every genuine tracksuit,
    # INCLUDING excluding Furor's "Tracksuit <single garment>"
    # collection-naming pattern; leaving "tracksuit" in this regex too
    # would silently re-catch those excluded single-garment titles here
    # and wrongly resolve them to the Co-ord Set default instead of letting
    # them fall through to the real Jacket/Hoodie/Sweatshirt resolution.
    #
    # The piece-count sub-check is also now restricted to `title_blob`
    # only, not the full `blob` — a real example, Cougar's own
    # `productType: "2PC"` bucket (83 real products, e.g. a single top with
    # no matching bottom at all), was wrongly pulled into Co-ord Set purely
    # because product_type said "2PC" even though the title itself never
    # does. co-ord/suit/pantsuit/nightsuit/combo stay checked against the
    # full blob, unaffected.
    coord_words = re.compile(
        r"\bco-?ords?\b|\bsuits?\b|\bpantsuits?\b|\bnightsuits?\b"
        r"|\bcombos?\b(?!\s+(?:hoodies?|tees?|t-shirts?|shirts?|polos?|sweatshirts?|sweaters?|jackets?)\b)")
    # A set word only in the store's type ("Men Track Suits") doesn't make a
    # title that names one garment ("ProStride Track Jacket") a set.
    # "Co-Ord Set Shirt" / "Co-ord Set Polo" is one piece of a co-ord
    # collection, sold on its own: the garment after "set" decides.
    single_coord_piece = re.search(
        r"\bco-?ord\s+sets?\s+(?:\w+\s+){0,3}(?:shirts?|tees?|t-?shirts?|polos?|jackets?|hoodies?|sweatshirts?|sweaters?"
        + (r"|tops?" if gender in ("Women", "Girls") else "") + r")\b",
        title_blob)
    is_coord_candidate = not single_coord_piece and bool(coord_words.search(title_blob)) or bool(
        coord_words.search(blob) and not WESTERN_TITLE_GARMENT_RE.search(title_blob)
        and not re.search(r"\b(?:shirts?|tops?|blouses?)\b", title_blob)
    ) or bool(re.search(r"\b[1-4]\s*-?\s*(?:pc|pieces?)\b", title_blob)) or bool(
        # A title that is just "... Set" ("Play Set", "Rib Wrap Set"): every
        # set with a more specific name (gift, pajama, swim, kurta) was
        # claimed above.
        re.search(r"\bsets?\b", title_blob) and not WESTERN_TITLE_GARMENT_RE.search(title_blob)
        and not re.search(r"\b(?:shirts?|tops?|blouses?)\b", title_blob))
    # A title that names one dress and no set ("Embellished Tier Panel Dress")
    # is a dress, whatever set bucket the store files it in.
    if is_coord_candidate and re.search(r"\b(?:dress(?:es)?|frocks?|maxis?|gowns?)\b", title_blob) and not re.search(
            r"\bco-?ords?\b|\bsuits?\b|\bsets?\b|\bcombos?\b|\b[1-4]\s*-?\s*(?:pc|pieces?)\b", title_blob):
        is_coord_candidate = False
    # Boys' "Suiting" (Diners "Black Suiting for Boys") is a tailored suit;
    # suiting sold as fabric was already routed to Unstitched above.
    if re.search(r"\bsuiting\b", title_blob) and gender in ("Men", "Boys"):
        return dict(gender=gender, branch="Western", sub="Formalwear", leaf="Formal Suit",
                    style="western", construction="ready_to_wear")
    if is_coord_candidate:
        # A title that reads as a Western "Suit"/"Co-ord Set" can still be
        # a mislabeled Eastern ensemble — real examples verified against
        # actual tags/description: Cambridge's tags literally say
        # "Designer Shalwar Kameez"/"Mashriq" for items titled just
        # "EMBROIDERED SUIT"; Equator's description says "This two-piece
        # suit from our Qaftaan collection...includes a kurta..." for an
        # item titled "French Grey Suit"; Zellbury's "Wash & Wear Suit"
        # description says "Men Unstitched Shalwar Kameez Fabric" with no
        # Eastern word anywhere in title/product_type; Edenrobe's/
        # Cambridge's "Co-Ord Set"-titled items use the structured
        # Shirt+Trouser "Fit Type:" convention (see
        # _has_structured_shirt_trouser_desc); Edenrobe's/Diners' "Prince
        # Suit" items are a Sherwani ensemble under a Western-sounding
        # name. Scoped deliberately to ONLY this already-co-ord-shaped
        # candidate set — verified this does NOT reintroduce the earlier,
        # explicitly-rejected "eastern"-anywhere-in-tags idea (that one
        # caused 700+ false positives across Shirt/Trouser/Sweatshirt/etc
        # via an unrelated compound store-collection tag); here, the same
        # broadened tags+description signal was checked catalog-wide
        # against the CURRENT Co-ord Set category specifically and found
        # to only ever fire on genuine Eastern ensembles once "waistcoat"
        # was excluded (see EASTERN_TAGS_DESC_RE) and the shirt/trouser
        # heuristic was tightened to the labeled "Fit Type:" convention —
        # a looser version of both false-matched real Western products
        # (Equator's own 3-piece business suits via "waistcoat", Furor's
        # "Resort Co-Ord Set Shirt" line via loose fabric-mention counting).
        eastern_tags_desc_blob = f"{tags} {description}".lower()
        is_eastern_override = (
            EASTERN_TAGS_DESC_RE.search(eastern_tags_desc_blob)
            or UNSTITCHED_RE.search(eastern_tags_desc_blob)
            or _has_structured_shirt_trouser_desc(description)
            # "Prince Suit"/"Prince Coat" is a title-level signal (e.g.
            # "Grey Boys Prince Suit") — unlike the other override signals
            # above, it doesn't need tags/description to reveal it.
            or PRINCE_SET_RE.search(blob)
        )
        if is_eastern_override:
            if UNSTITCHED_RE.search(blob) or UNSTITCHED_RE.search(eastern_tags_desc_blob):
                sub, construction, leaf, pc = "Unstitched", "unstitched_fabric", "Suit", None
            else:
                sub, construction, pc = "Stitched", "ready_to_wear", None
                if "saree" in eastern_tags_desc_blob or "sari" in eastern_tags_desc_blob or "saree" in blob or "sari" in blob:
                    leaf = "Saree"
                else:
                    leaf = _eastern_stitched_leaf(blob, extra_signal=eastern_tags_desc_blob)
            if leaf == "Kurti" and gender in ("Men", "Boys"):
                gender = "Girls" if gender == "Boys" else "Women"
            return dict(gender=gender, branch="Eastern", sub=sub, leaf=leaf,
                        style="eastern", construction=construction, piece_count=pc)
        # A tailored Western 2/3-piece business suit is a distinct product
        # from a casual Co-ord Set — see FORMAL_SUIT_RE's own comment for
        # why this is gated to Men/Boys and why "waistcoat" is trusted here
        # even though it's excluded from the Eastern-override signal above.
        formal_signal_blob = f"{blob} {eastern_tags_desc_blob}"
        if gender in ("Men", "Boys") and (
            FORMAL_SUIT_RE.search(formal_signal_blob)
            or (re.search(r"\bsuits?\b", formal_signal_blob) and FORMAL_SUIT_CHEST_BOILERPLATE_RE.search(formal_signal_blob))
        ):
            return dict(gender=gender, branch="Western", sub="Formalwear", leaf="Formal Suit",
                        style="western", construction="ready_to_wear")
        return dict(gender=gender, branch="Western", sub="Suits & Sets", leaf="Co-ord Set",
                    style="western", construction="ready_to_wear")
    # "Hoodie" checked before the bare "sweat" fallback so a hooded
    # sweatshirt gets its own leaf instead of the generic Sweatshirt one;
    # "sweatshirt" itself now requires the full word, not bare "sweat" (which
    # also matched "sweatpant" before the check above existed).
    # "dress" ahead of "shirt" would wrongly try to route "Dress Shirt" (a
    # men's formal shirt, an adjectival use) to a "Dress" leaf that doesn't
    # exist outside women's/girls' trees — excluded the same way "short
    # sleeve" and "shawl collar" were. Allowing up to one word between
    # "dress" and "shirt" catches the same collision with an intervening
    # fabric-pattern word — a real example, "Purple Dress Stripes Shirt",
    # otherwise still resolved to "Dress" since "shirt" wasn't immediately
    # adjacent.
    # "Sweater" was a leaf defined only in Men's tree but never actually
    # emitted by classify() — real sweaters (a knitted pullover, distinct
    # from a "Sweatshirt") across every gender were all falling through to
    # the generic "Shirt" bucket. 1,482 real products confirmed this
    # ("Basic Textured Sweater", "Crew Neck Knitted Sweater", vendor/
    # product_type literally "SWEATERS" in many cases). No word-boundary
    # collision with "Sweatshirt" — the two words don't share a substring
    # ("sweat-er" vs "sweat-shirt").
    # "tees?" plural was missing — 906 real products (ONE Be-One's/
    # Diners' entire product_type: "Tees" line, "Net Top Yellow",
    # "Soccer Ball Print Tees") never matched the singular-only
    # `\btee\b` and fell to the generic Shirt default. Same class of bug
    # as the fragrance/footwear/accessory plural gaps found earlier this
    # pass — found by extending the full-catalog audit to every leaf.
    def _upperwear_leaf_from(text):
        # "blazer"/bare "coat" fold into the same Jacket leaf —
        # CATEGORY_TREE has no separate Blazer or Coat leaf.
        # "blazer": Engine Clothing's real "Women Shorts Body
        # Blazer"/"...Body Jacket" pair (9 products) would otherwise
        # fall through to the generic Shirt default once the Shorts
        # exclusion above stops sending them to Bottomwear.
        # "coat" (word-boundary, so it doesn't match inside
        # "waistcoat"/"raincoat"): a real, separately-confirmed bug —
        # Charcoal Clothing's "BAN COLLAR LONG COAT"/"SMART FIT LONG
        # COAT" line and Girls Junior's "Basic Button Up Coat"
        # (product_type literally "OUTERWEAR"/"long coats") were all
        # resolving to plain "Shirt" with no coat/jacket-specific
        # handling anywhere in this function.
        if gender in ("Women", "Girls") and DRESS_HEAD_RE.search(text):
            return "Dress"
        if "polo" in text:
            return "Polo"
        if COLLARED_TEE_RE.search(text) and not NON_POLO_COLLAR_RE.search(text):
            return "Polo"
        # Checked ahead of "tee" — "tank top" doesn't collide with the tee
        # pattern, but is a more specific signal whenever both happen to be
        # present. Deliberately does NOT include "sando": that's this
        # catalog's own real word for a men's UNDERGARMENT tank (see
        # VEST_UNDERWEAR_SIGNAL_RE) — a different real garment from an
        # outerwear/activewear tank top, and already correctly routed to
        # Underwear earlier in this function. Real examples landing here:
        # Furor's own product_type literally "Men Tank Tops", Edenrobe
        # "Boys Tank Top" — 476 real products across Men/Women/Boys/Girls
        # had no keyword at all and were falling to Shirt/T-Shirt.
        # Broadened from "tank top(s)" to bare "tank(s)" after backfill
        # verification found real tank tops titled without the word "top"
        # at all — Equator's "Color Block Tank", Breakout's "CARDIO TANK",
        # Monark's "Textured Tank-Shirt", Meme's "TANK T-SHIRT FOR WOMEN",
        # Engine's "Girls Tank Knit Top" — every real "tank"/"tanks" hit
        # checked catalog-wide is a genuine tank top, no collision found.
        if re.search(r"\btanks?\b|\bcamisoles?\b|\bcamis?\b|\bsandos?\s+tops?\b", text):
            return "Tank Top"
        # A quilted or padded shacket is a jacket.
        if re.search(r"\b(?:quilted|padded|puffer|sherpa)\b.*\bshackets?\b", text):
            return "Jacket"
        if re.search(r"\b(?:t[\s-]?shirt|tee)\s+(?:\w+\s+)?dress(?:es)?\b", text):
            return "Dress"
        # "vest" + a tee word together means SLEEVELESS, same as "tank"
        # above — checked before the generic tee check right below so it
        # wins, mirroring that exact precedent. Real example, Engine
        # Clothing's "Boys Vest T Shirt" (a plain graphic tank top, Looney
        # Tunes print, genuinely sleeveless — photo-verified) was resolving
        # T-Shirt instead of Tank Top once the spaced "t shirt" fix below
        # was added, since a bare tee check has no way to know "vest" here
        # means sleeveless rather than being irrelevant noise.
        if "vest" in text and re.search(r"\b(tees?|t[\s-]?shirts?)\b", text):
            return "Tank Top"
        # "t shirt" (space-separated, no hyphen) was missing — the same
        # real example above fell all the way through to the generic Vest
        # catch-all before this, since neither "t-shirt" nor "tshirt"
        # matched the literal spaced phrase.
        if re.search(r"\b(tees?|t[\s-]?shirts?)\b", text):
            return "T-Shirt"
        # "gilet" wins over any hoodie ambiguity below — it's this
        # catalog's most unambiguous sleeveless-outerwear word (see the
        # Vest leaf's own comment). Real example: Furor's "Hooded Puffer
        # Gilet" (no "jacket" word in the title at all) — was landing on
        # Hoodie off the bare "hooded" adjective before this.
        #
        # BUT explicit user decision (2026-09-01, asked directly after
        # two rounds of back-and-forth on this exact question): when
        # "jacket" is ALSO in the title, JACKET WINS OUTRIGHT — title
        # word beats confirmed construction, full stop, even for a
        # product whose description explicitly confirms sleeveless
        # (Cougar's "Hooded Gilet Jacket," Charcoal's "QUILTED SUEDE
        # GILET JACKET SLEEVELESS," Engine Clothing's "Men Gilet
        # Jacket" — all real, verified-sleeveless-via-photo garments
        # that still resolve Jacket per this explicit instruction, not
        # Vest). Do not reintroduce a sleeveless-description exception
        # here without asking again — this was already tried once and
        # reverted at the user's explicit direction.
        if "gilet" in text and "jacket" not in text:
            return "Vest"
        # User-reported: browsing Hoodie turned up real hooded JACKETS —
        # 99 real products, the vast majority Cambridge/Charcoal/Cougar/
        # Diners/Equator/Furor/Lama/Meme/One(Be-One)/Uniworth titled things
        # like "HOODED PUFFER JACKET", "Hooded Denim Jacket", "MEN'S
        # HOODED DUFFLE COAT", "HOODED PUFFER BOMBER JACKET" — "hooded" is
        # an ADJECTIVE describing a feature of the jacket/coat, not the
        # garment's own type, and it was winning outright over the actual
        # garment noun ("jacket"/"coat") appearing later in the same
        # title. Only the literal NOUN "hoodie" is trusted here now — real
        # genuine hoodies verified by description before trusting this:
        # Cambridge's "WAFFLE/OTTOMAN HOODIE ZIPPER JACKET" line (100%
        # soft fleece, cotton-poly blend — a real hoodie despite "jacket"
        # also appearing) and Charcoal's "JACKET FULL SLEEVE KNIT HOODIE"
        # line (100% fleece cotton) both correctly stay Hoodie via this
        # noun-only check. "with...hood(ie)" is stripped first, same class
        # of fix as GARMENT_DETAIL_RE's "with...belt/tie/scarf" (applied
        # locally here since title_blob/blob never go through that
        # stripping — it's only ever applied to accessory_blob elsewhere):
        # real examples, Outfitters' "Faux Leather Jacket With Hoodie"
        # (Synthetic Faux Leather) and "Denim Jacket With Hoodie" (100%
        # Cotton denim), are both real jackets that merely include an
        # attached hood, not hoodies themselves. The weaker bare-"hooded"
        # signal (no "hoodie" noun present) is checked again further down,
        # ONLY as a last resort after jacket/coat/blazer/dress have all
        # had a chance to claim a stronger, more specific noun first.
        hoodie_text = re.sub(r"\bwith\b.{0,20}?\bhood(?:s|ie|ies)?\b", " ", text)
        if "hoodie" in hoodie_text:
            return "Hoodie"
        if "sweatshirt" in text or "sweat shirt" in text:
            return "Sweatshirt"
        # "cardigan" folds into the same Sweater leaf — no separate
        # Cardigan leaf exists, and a cardigan is functionally a knitted
        # button-up sweater. 47 real EXISTING products ("Modal Rib Lace
        # Cardigan") had no keyword at all and were falling to Shirt —
        # found during the Bandana.pk onboarding audit but not specific
        # to that brand.
        # "open knit" is a real, specific knitwear term — always describes
        # sweater-weight fabric (a loose/lacy knit stitch), never a plain
        # jersey tank. User-reported, browsing Men's Vest: Outfitters'
        # "Open Knit Vest" (photo-verified: a thick ribbed knit layering
        # piece worn over a collared shirt, unmistakably a sweater vest,
        # not outerwear) was landing on the generic Vest leaf.
        if "sweater" in text or "cardigan" in text or "turtleneck" in text or "open knit" in text:
            return "Sweater"
        # "tunic" only maps to "Top" for Women/Girls — that's the only
        # gender pair CATEGORY_TREE defines a "Top" leaf for at all (Men/
        # Boys/Unisex Upperwear have no such leaf), and every real tunic
        # checked (538 real Zellbury products, product_type e.g. "Tunic")
        # is a Women's item — a bare gender check here is the correct,
        # narrow guard rather than adding an orphan-prone leaf everywhere.
        # "Top" itself was a real pre-existing bug: the leaf was already
        # defined in CATEGORY_TREE for Women/Girls but no rule anywhere in
        # this function had ever emitted it — dead code until now.
        if "tunic" in text and gender in ("Women", "Girls"):
            return "Top"
        # Blazer has its own leaf since 2026-10-28 (Formalwear for Men/Boys,
        # Upperwear for Women/Girls; see the return below).
        if re.search(r"\bblazers?\b", text):
            return "Blazer"
        if (gender in ("Men", "Boys") and re.search(r"\bcoats?\b", text) and "jacket" not in text
                and not NOT_BLAZER_COAT_RE.search(text)):
            return "Blazer"
        if "jacket" in text or re.search(r"\bcoats?\b", text):
            return "Jacket"
        if re.search(r"\bdress\b(?!\s+(?:\w+\s+)?shirts?\b)|\bfrock\b|\bmaxis?\b|\bgowns?\b", text):
            return "Dress"
        # Last-resort weak signal — a bare "hooded" with no "hoodie" noun,
        # no gilet, and no jacket/coat/blazer/dress noun already claimed
        # above (all real, more specific outerwear types checked first;
        # see the "hoodie" noun check above for why "hooded" alone can't
        # be trusted this early). Also excludes "shirt" — real examples,
        # One (Be-One)'s "Hooded Check Shirt" ("Regular fit short sleeve
        # shirt in check fabrication, featuring... contrasting jersey
        # hood and double pockets"), Meme's "HOODED DENIM SHIRT" ("SLIM
        # FIT SHACKET WITH REGULAR COLLAR FEATURING HOOD. SNAP BUTTON DOWN
        # CLOSURE") — are all genuine collared, buttoned SHIRTS with a
        # hood as a design detail, not hoodies; "shirt" isn't checked
        # elsewhere in this function since it's the caller's own final
        # fallback, so it has to be excluded explicitly here rather than
        # just "already having claimed the return above" like jacket/coat
        # did. A real, genuine hooded sweatshirt with no other garment
        # word still needs to land somewhere.
        if "hooded" in text and not re.search(r"\bshirts?\b", text):
            return "Hoodie"
        # A bare "vest" reaching this point is, by construction, NOT an
        # underwear vest (that's already been ruled out earlier via
        # is_underwear_vest) — real examples confirm it's genuine outerwear/
        # activewear (Engine Clothing's "Active Wear Vest", Cambridge's
        # "Quilted Vest"/"Sherpa Vest"). Checked after "sweater" so a real
        # "Sweater Vest" still resolves Sweater first (already handled by
        # the ordering above), and after "coat"/"jacket" so a real coat
        # whose own description happens to mention "vests" only as a
        # tailoring detail (Charcoal's "Two Back Side Vests" — almost
        # certainly a scrape-source typo for "vents") stays a Jacket: this
        # function only ever sees title_blob/blob (title+product_type),
        # never description, so that case never even reaches here.
        # Own leaf as of 2026-09-01 (user-reported: browsing Women's
        # Jackets turned up real vests) — a sleeveless outer layer is a
        # fundamentally different garment from a jacket (which has
        # sleeves), not just a style variant of one. 156 real products
        # across every gender were previously folding into Jacket here
        # because no separate Vest leaf existed at all — see CATEGORY_TREE's
        # own comment on the "Vest" leaf for the full per-gender breakdown.
        # "gilet"/"bodywarmer" fold into the same new Vest leaf — a
        # sleeveless puffer/quilted layer, same real garment class as
        # "vest" above, just a different regional word for it. 67 real
        # EXISTING products (Furor "Puffer Gilet", "Yellow Down Gilet",
        # "Blue Quilted Gilet") had no jacket/vest/coat word at all and
        # were falling to Shirt/Hoodie — found during the Bandana.pk
        # onboarding audit but not specific to that brand.
        # A "vest" carrying an activewear signal in its own title (gym/
        # training/sports/"active wear"/dry-fit) is a sleeveless ATHLETIC
        # TOP — the same real garment this catalog already calls "Tank
        # Top" for every other brand — not the puffer/quilted/waistcoat
        # OUTERWEAR layer the plain "Vest" leaf above is otherwise full of.
        # User-reported (browsing Men's Vest after the leaf above shipped):
        # "the men vests look very diverse." Real examples, verified via
        # description before ever trusting the title alone: One (Be-One)'s
        # "Gym Vest" ("Gym vest in dry fit fabrication"), Equator's
        # "Training Vest" ("from our Activewear collection...wicks
        # moisture...workouts"), Engine Clothing's "Active Wear Vest"
        # ("activewear vest...Lycra Poly Jersey...workouts, training") —
        # all real athletic tanks, sitting in the same leaf as Cambridge's
        # genuine quilted winter puffer vests and Uniworth's formal
        # Western waistcoats. Checked ahead of the plain vest/gilet/
        # bodywarmer catch-all below so this narrower, stronger signal
        # wins first.
        if re.search(r"\bvests?\b", text) and ACTIVEWEAR_VEST_SIGNAL_RE.search(text):
            return "Tank Top"
        # See PLAIN_RIBBED_KNIT_VEST_RE's own comment for the real
        # examples (Furor's "Ribbed Vest" line, Engine Clothing's "Men
        # Sleeveless Panel Knit Vest") and why VEST_REAL_OUTERWEAR_RE
        # keeps this from ever touching a genuine puffer/quilted/gilet/
        # waistcoat vest.
        if (
            re.search(r"\bvests?\b", text)
            and PLAIN_RIBBED_KNIT_VEST_RE.search(text)
            and not VEST_REAL_OUTERWEAR_RE.search(text)
        ):
            return "Tank Top"
        if re.search(r"\bvests?\b|\bgilets?\b|\bbodywarmers?\b", text):
            return "Vest"
        return None

    # Title-first, full-blob fallback — same precedent as every other
    # title-vs-product_type conflict fixed this session. Real example:
    # Outfitters' "Character Graphic Sweatshirt" has product_type "TEES"
    # (a coarser bucket) — since the old version checked the MERGED
    # blob against a fixed priority order (T-Shirt checked before
    # Sweatshirt), the product_type's "tee" won even though the title
    # itself explicitly says "Sweatshirt". Checking the title alone
    # first means whichever garment word the title itself uses wins,
    # regardless of where it sits in this priority list.
    leaf = _upperwear_leaf_from(title_blob)
    if leaf is None:
        leaf = _upperwear_leaf_from(blob)
        # The title's own "Top"/"Blouse" beats a generic store type like
        # "Tees"; a specific one ("Sweaters") still wins.
        if leaf in (None, "T-Shirt") and gender in ("Women", "Girls") and re.search(r"\b(?:tops?|blouses?)\b", title_blob):
            leaf = "Top"
    if leaf is None and UPPER_WORD_RE.search(title_blob) and not SHIRT_WORD_RE.search(title_blob):
        upper_text = f"{title_blob} {tags or ''} {(description or '')[:300]}".lower()
        leaf = ("Hoodie" if re.search(r"\bhood", upper_text)
                else "Sweater" if re.search(r"\bknit|\bsweater|\bwool", upper_text)
                else "Jacket")
    if leaf is None:
        # No garment word matched. "Shirt" only when the product says so;
        # otherwise Uncategorised, for the LLM run to decide (2026-10-28 —
        # Diners fabric, Cougar "Upper", gloves and towels all used to land
        # in Shirt from here).
        if SHIRT_WORD_RE.search(blob):
            leaf = "Shirt"
        elif TOP_WORD_RE.search(blob) and gender in ("Women", "Girls"):
            leaf = "Top"
        else:
            return dict(gender=gender, branch="Uncategorised", sub=None, leaf="Uncategorised",
                        style="western", construction="ready_to_wear")
    sub = "Formalwear" if leaf == "Blazer" and gender in ("Men", "Boys") else "Upperwear"
    return dict(gender=gender, branch="Western", sub=sub, leaf=leaf,
                style="western", construction="ready_to_wear")


def classify(store, p, title, product_type, tags, vendor, description):
    """The keyword rules above, then category_refine's pass for the Nov 2026 tree."""
    from category_refine import refine
    cls = _classify_rules(store, p, title, product_type, tags, vendor, description)
    return refine(store, p, cls, _fix_vocab(title), _fix_vocab(product_type), tags, description)


def strip_html(html):
    if not html:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()[:2000]


def _load_one_product(conn, cur, bid, native_id, p, title, description, cat_id, cls,
                       tags, images, is_graphql, raw_variants, color_id, fabric_id):
    """Inserts one product row plus its images/variants/fabric pieces using
    the given cursor. Caller is responsible for commit/rollback around this
    call. Returns None if the product already existed (ON CONFLICT DO
    NOTHING — nothing new to count), otherwise a dict of row counts inserted."""
    cur.execute(
        """INSERT INTO products (brand_id, native_product_id, handle, title, description,
            category_id, style_family, construction_status, age_group, piece_count,
            tags, raw_source, is_browsable)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (brand_id, native_product_id) DO NOTHING
           RETURNING id""",
        (bid, native_id, p.get("handle"), title[:500], description, cat_id,
         cls["style"], cls["construction"], "adult", cls.get("piece_count"),
         tags, json.dumps(p), cls.get("browsable", True)),
    )
    row = cur.fetchone()
    if row is None:
        return None
    pid = row[0]

    image_count = 0
    for pos, url_ in enumerate(images[:12]):
        cur.execute(
            "INSERT INTO product_images (product_id, url, position) VALUES (%s,%s,%s)",
            (pid, url_, pos),
        )
        image_count += 1

    # Shopify's more complete per-variant image link: an image in the
    # product's OWN images[] array carries the variant ids it belongs to,
    # and this is populated in real data even when a variant's own
    # "featured_image" field (normalize_variant_fields' fallback) is null —
    # verified directly against real multi-color products across brands.
    # REST only; GraphQL (Cougar) has no equivalent.
    image_by_variant_id = {}
    if not is_graphql:
        for img in (p.get("images") or []):
            for vid in (img.get("variant_ids") or []):
                image_by_variant_id[str(vid)] = img.get("src")

    variant_count = 0
    option_defs = p.get("options") or [] if not is_graphql else []
    for v in raw_variants:
        vf = normalize_variant_fields(v, option_defs, is_graphql)
        native_vid = vf["native_vid"]
        color_name = vf["color_name"]
        size_val = vf["size_val"]
        price = vf["price"]
        compare_at = vf["compare_at"]
        # Store-side override: some products (Cambridge, confirmed) carry a
        # theme tag disabling the buy button independent of raw inventory —
        # see tags_force_unavailable's docstring. The product stays
        # browsable; only the purchasability flag changes.
        available = False if tags_force_unavailable(tags) else vf["available"]
        sku = vf["sku"]
        image_url = image_by_variant_id.get(native_vid) or vf.get("image_url")

        cid_color = None
        if color_name:
            cid_color = color_id.get(color_name.strip().lower())
            if cid_color is None:
                cur.execute(
                    "INSERT INTO colors (canonical_name) VALUES (%s) "
                    "ON CONFLICT (canonical_name) DO UPDATE SET canonical_name=EXCLUDED.canonical_name RETURNING id",
                    (color_name.strip(),),
                )
                cid_color = cur.fetchone()[0]
                color_id[color_name.strip().lower()] = cid_color
                # Committed immediately, independent of this product's own
                # transaction: if this product later fails and rolls back,
                # the color id already cached in the Python-side dict must
                # still exist in the DB, or every future product sharing
                # this color name would fail with a dangling FK reference.
                conn.commit()

        size_system = classify_size_system(size_val)

        cur.execute(
            """INSERT INTO variants (product_id, native_variant_id, color_id, size_label,
                size_system, sku, current_price, current_compare_at, current_available, image_url)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (product_id, native_variant_id) DO NOTHING""",
            (pid, native_vid, cid_color, size_val, size_system, sku,
             price, compare_at, available, image_url),
        )
        variant_count += 1

    piece_count = 0
    if description and cls["construction"] == "unstitched_fabric":
        for m in re.finditer(r"(Shirt|Trouser|Dupatta|Shawl)\s+(?:Fit Type:[^F]*)?Fabric:\s*([A-Za-z]+)(?:\s*\|\s*([\d.]+)\s*Meters?)?", description):
            piece, fab, length = m.group(1), m.group(2), m.group(3)
            fid = fabric_id.get(fab.lower())
            cur.execute(
                "INSERT INTO product_pieces (product_id, piece_name, fabric_id, length_meters, sort_order) VALUES (%s,%s,%s,%s,%s)",
                (pid, piece, fid, float(length) if length else None, piece_count),
            )
            piece_count += 1

    return {"images": image_count, "variants": variant_count, "pieces": piece_count}


def main():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()

    brand_id = {}
    for slug, name, url, platform in BRANDS:
        cur.execute(
            "INSERT INTO brands (slug, name, base_url, platform_type) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name RETURNING id",
            (slug, name, url, platform),
        )
        brand_id[slug] = cur.fetchone()[0]

    fabric_id = {}
    for name in FABRICS:
        cur.execute(
            "INSERT INTO fabrics (name) VALUES (%s) "
            "ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id",
            (name,),
        )
        fabric_id[name.lower()] = cur.fetchone()[0]

    color_id = {}
    for name, hexv in COLORS:
        cur.execute(
            "INSERT INTO colors (canonical_name, hex_approx) VALUES (%s,%s) "
            "ON CONFLICT (canonical_name) DO UPDATE SET canonical_name=EXCLUDED.canonical_name RETURNING id",
            (name, hexv),
        )
        color_id[name.lower()] = cur.fetchone()[0]

    category_id = {}
    def get_or_make_category(parent_id, name, slug):
        key = (parent_id, slug)
        if key in category_id:
            return category_id[key]
        if parent_id is None:
            # A plain UNIQUE(parent_id, slug) constraint never treats two
            # NULL parent_ids as equal (standard SQL null semantics), so
            # ON CONFLICT (parent_id, slug) silently fails to dedupe the 5
            # gender-root rows — every rerun (or, as happened here, a second
            # concurrent run) quietly inserted a whole duplicate category
            # tree instead of reusing the existing one. Fixed at the DB
            # level with a partial unique index restricted to root rows
            # (see db/init/01_schema.sql migration applied via psql:
            # CREATE UNIQUE INDEX idx_categories_root_slug ON categories
            # (slug) WHERE parent_id IS NULL), targeted explicitly here.
            cur.execute(
                "INSERT INTO categories (parent_id, name, slug) VALUES (NULL,%s,%s) "
                "ON CONFLICT (slug) WHERE parent_id IS NULL "
                "DO UPDATE SET name=EXCLUDED.name RETURNING id",
                (name, slug),
            )
        else:
            cur.execute(
                "INSERT INTO categories (parent_id, name, slug) VALUES (%s,%s,%s) "
                "ON CONFLICT (parent_id, slug) DO UPDATE SET name=EXCLUDED.name RETURNING id",
                (parent_id, name, slug),
            )
        cid = cur.fetchone()[0]
        category_id[key] = cid
        return cid

    leaf_lookup = {}  # (gender, branch, sub, leaf_name) -> category_id
    for gender, branches in CATEGORY_TREE.items():
        g_id = get_or_make_category(None, gender, gender.lower())
        for branch, content in branches.items():
            b_id = get_or_make_category(g_id, branch, re.sub(r"[^a-z]+", "-", branch.lower()))
            if isinstance(content, dict):
                for sub, leaves in content.items():
                    s_id = get_or_make_category(b_id, sub, re.sub(r"[^a-z]+", "-", sub.lower()))
                    for name, slug in leaves:
                        l_id = get_or_make_category(s_id, name, slug)
                        leaf_lookup[(gender, branch, sub, name)] = l_id
            else:
                for name, slug in content:
                    l_id = get_or_make_category(b_id, name, slug)
                    leaf_lookup[(gender, branch, None, name)] = l_id

    conn.commit()
    print(f"Seeded: {len(brand_id)} brands, {len(fabric_id)} fabrics, {len(color_id)} colors, {len(category_id)} categories")

    total_products = total_variants = total_images = total_pieces = excluded = skipped_errors = 0
    conn_opened = time.time()

    for slug, name, url, platform in BRANDS:
        path = os.path.join(DATA_DIR, f"{slug}.jsonl")
        if not os.path.exists(path):
            # A brand can be seeded (brands table row above) without ever
            # having a historical JSONL to replay — that's expected for any
            # brand added after the one-time scrape and populated live via
            # db/scraper/run_scrape.py instead. Not an error condition.
            print(f"{name}: no scraped_data/{slug}.jsonl — skipping replay (use run_scrape.py for this brand)")
            continue
        is_graphql = slug == "cougar"
        bid = brand_id[slug]
        brand_products_before = total_products
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # Recycle the connection on a timer, independent of any
                # error — proactively avoids whatever this sandbox's network
                # layer does to long-lived connections after a few minutes.
                if time.time() - conn_opened > RECONNECT_SECONDS:
                    try:
                        cur.close(); conn.close()
                    except Exception:
                        pass
                    conn, cur = connect()
                    conn_opened = time.time()

                p = json.loads(line)
                title = p.get("title") or ""
                nf = normalize_product_fields(p, is_graphql)
                native_id = nf["native_id"]
                product_type = nf["product_type"]
                tags = nf["tags"]
                vendor = nf["vendor"]
                description = strip_html(nf["description_html"])
                images = nf["images"]
                raw_variants = nf["raw_variants"]

                cls = classify(slug, p, title, product_type, ",".join(tags), vendor, description or "")
                if cls is None:
                    excluded += 1
                    continue

                cat_id = leaf_lookup.get((cls["gender"], cls["branch"], cls.get("sub"), cls["leaf"]))
                gender_root_id = category_id.get((None, cls["gender"].lower()))
                if cat_id is None:
                    # Fall back to the branch node itself if the specific
                    # leaf wasn't pre-seeded. Slug must be computed the same
                    # way get_or_make_category built it (special chars ->
                    # "-"), not just .lower() — otherwise e.g. "Fragrance &
                    # Beauty" (stored as slug "fragrance-beauty") never
                    # matches here.
                    branch_slug = re.sub(r"[^a-z]+", "-", cls["branch"].lower())
                    cat_id = category_id.get((gender_root_id, branch_slug))
                if cat_id is None:
                    # CATEGORY_TREE doesn't give every gender every branch
                    # (e.g. "Unisex" only has Accessories) — a Western/
                    # Eastern classification under a gender missing that
                    # branch would otherwise silently leave category_id
                    # NULL. Falling back to the gender root itself keeps
                    # the product browsable (still findable under that
                    # gender) instead of losing its category entirely.
                    cat_id = gender_root_id

                # Everything below (product row + its images + its variants
                # + its fabric pieces) is committed as one atomic unit per
                # product. On a transient connection failure we reconnect
                # and retry the same product from scratch — safe because
                # nothing from a failed attempt was ever committed.
                attempt = 0
                counts = None
                while True:
                    attempt += 1
                    try:
                        counts = _load_one_product(
                            conn, cur, bid, native_id, p, title, description, cat_id, cls,
                            tags, images, is_graphql, raw_variants, color_id, fabric_id,
                        )
                        conn.commit()
                        break
                    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        try:
                            cur.close(); conn.close()
                        except Exception:
                            pass
                        conn, cur = connect()
                        conn_opened = time.time()
                        if attempt >= 5:
                            print(f"  [{slug}] giving up on one product after {attempt} attempts: {e}")
                            skipped_errors += 1
                            break
                        time.sleep(1)
                    except Exception as e:
                        conn.rollback()
                        print(f"  [{slug}] skipping one product due to error: {e}")
                        skipped_errors += 1
                        break
                if counts is not None:
                    total_products += 1
                    total_images += counts["images"]
                    total_variants += counts["variants"]
                    total_pieces += counts["pieces"]

        cur.execute(
            "INSERT INTO scrape_runs (brand_id, started_at, finished_at, product_count, status) "
            "VALUES (%s, now(), now(), (SELECT COUNT(*) FROM products WHERE brand_id=%s), 'completed')",
            (bid, bid),
        )
        conn.commit()
        print(f"{name}: loaded ({total_products - brand_products_before} new products)")

    print(f"\nTOTAL: {total_products} products, {total_variants} variants, {total_images} images, "
          f"{total_pieces} product_pieces rows, {excluded} excluded (gift cards), "
          f"{skipped_errors} skipped after errors")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
