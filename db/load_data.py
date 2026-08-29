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

from product_normalize import normalize_product_fields, normalize_variant_fields, classify_size_system

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
DSN = "host=localhost port=5433 dbname=libas user=libas password=libas_dev_password"

BRANDS_ALL = [
    ("outfitters", "Outfitters", "https://outfitters.com.pk", "liquid_rest"),
    ("furor", "Furor", "https://furorjeans.com", "liquid_rest"),
    ("edenrobe", "Edenrobe", "https://edenrobe.com", "liquid_rest"),
    ("one_be-one", "ONE (Be-One)", "https://beoneshopone.com", "liquid_rest"),
    ("equator", "Equator", "https://equatorstores.com", "liquid_rest"),
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
    ("lama", "Lama", "https://lamaretail.com", "liquid_rest"),
]
# NOTE: an earlier run duplicated the category tree (see get_or_make_category
# below) and split ~43k already-loaded products across the two copies, so
# products/variants/images and the duplicate categories were deleted and the
# root-cause fixed (partial unique index on root-level category slugs).
# Starting over from a clean products table — every brand is pending again.
BRANDS = BRANDS_ALL

# gender -> branch -> subbranch (or None) -> [(name, slug)]
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
            "Upperwear": [("T-Shirt","t-shirt"),("Polo","polo"),("Shirt","shirt"),("Jacket","jacket"),("Sweatshirt","sweatshirt"),("Hoodie","hoodie"),("Sweater","sweater"),("Tank Top","tank-top")],
            "Bottomwear": [("Trouser","trouser"),("Jeans","jeans"),("Shorts","shorts"),("Joggers","joggers"),("Tights","tights")],
            "Suits & Sets": [("Co-ord Set","co-ord-set")],
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
            "Upperwear": [("T-Shirt","t-shirt"),("Polo","polo"),("Top","top"),("Shirt","shirt"),("Jacket","jacket"),("Sweatshirt","sweatshirt"),("Hoodie","hoodie"),("Sweater","sweater"),("Dress","dress"),("Tank Top","tank-top")],
            "Bottomwear": [("Trouser","trouser"),("Jeans","jeans"),("Shorts","shorts"),("Joggers","joggers"),("Tights","tights")],
            "Suits & Sets": [("Co-ord Set","co-ord-set")],
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
            "Upperwear": [("T-Shirt","t-shirt"),("Polo","polo"),("Shirt","shirt"),("Sweatshirt","sweatshirt"),("Hoodie","hoodie"),("Sweater","sweater"),("Jacket","jacket"),("Tank Top","tank-top")],
            "Bottomwear": [("Trouser","trouser"),("Shorts","shorts"),("Jeans","jeans"),("Joggers","joggers")],
            "Suits & Sets": [("Co-ord Set","co-ord-set")],
            "Footwear": [("Shoes","shoes")],
        },
        "Eastern": {"Stitched": [("Kurta","kurta"),("Kurta Set","kurta-set"),("Shalwar Kameez","shalwar-kameez"),("Waistcoat","waistcoat"),("Sherwani","sherwani")], "Unstitched": [("2-Piece","2-piece"),("Suit","suit")]},
        "Accessories": [("Cap","cap"),("Bag","bag"),("Underwear","underwear"),("Sunglasses","sunglasses"),("Socks","socks"),("Belt","belt"),("Watch","watch"),("Wallet","wallet"),("Scarf","scarf"),("Pocket Square","pocket-square")],
        "Fragrance & Beauty": [("Perfume","perfume")],
    },
    "Girls": {
        "Western": {
            "Upperwear": [("T-Shirt","t-shirt"),("Polo","polo"),("Top","top"),("Shirt","shirt"),("Sweatshirt","sweatshirt"),("Hoodie","hoodie"),("Sweater","sweater"),("Jacket","jacket"),("Dress","dress"),("Tank Top","tank-top")],
            "Bottomwear": [("Trouser","trouser"),("Shorts","shorts"),("Jeans","jeans"),("Joggers","joggers"),("Tights","tights")],
            "Suits & Sets": [("Co-ord Set","co-ord-set")],
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
            "Upperwear": [("T-Shirt","t-shirt"),("Polo","polo"),("Shirt","shirt"),("Sweatshirt","sweatshirt"),("Hoodie","hoodie"),("Sweater","sweater"),("Jacket","jacket"),("Dress","dress"),("Tank Top","tank-top")],
            "Bottomwear": [("Trouser","trouser"),("Jeans","jeans"),("Shorts","shorts"),("Joggers","joggers")],
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

FABRICS = ["Lawn","Khaddar","Cambric","Cotton","Silk","Chiffon","Denim","Polyester","Linen","Wool","Blended","Organza","Velvet"]

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
                         "monark": "Men", "equator": "Men", "cambridge": "Men"}

UNSTITCHED_RE = re.compile(r"un[\s-]?stitched", re.I)
# Singular-only was the bug: 131 real Outfitters/ONE-Be-One/Lama perfumes
# (product_type literally "FRAGRANCES"/"Perfumes", titles are just scent
# names with no fragrance word at all — "Spiced Rage", "Aqua Bloom",
# "AMALFI ORANGE") never matched `\bfragrance\b` against the plural
# "FRAGRANCES", and fell all the way through to the generic Shirt/T-Shirt
# default. User-reported: "Spiced Rage ... and other perfumes!" was one
# visible symptom of a much larger, previously-unfound gap.
FRAGRANCE_RE = re.compile(r"\b(perfumes?|fragrances?|colognes?)\b", re.I)
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
    r"mocassins?|moccassins?|moccasins?|flip.?flops?)\b"
    r"(?!(?:\s+\w+){0,2}\s+(?:shirts?|tees?|t-shirts?|polos?|hoodies?|sweatshirts?|sweaters?)\b)",
    re.I,
)
# "Sandals" is a real leaf CATEGORY_TREE only defines for Women (Men/
# Boys/Girls only ever had "Shoes") — real sandal-shaped items
# (sandal/slide/khussa/flip-flop/mule) route there for Women instead of
# the generic Shoes leaf; everything else (boot/pump/loafer/sneaker/
# heel/moccasin) still goes to Shoes for every gender.
SANDAL_LEAF_RE = re.compile(r"\b(sandals?|slides?|khussa|flip.?flops?|mules?)\b", re.I)
JOGGERS_RE = re.compile(r"\b(sweatpants?|joggers?|track\s*pants?)\b", re.I)
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
ACCESSORY_RE = re.compile(
    r"\b(belts?|caps?|hats?|beanies?|wallets?|cufflinks?|sunglass(?:es)?|"
    r"jewel(?:l?ery|ry)?|bracelets?|necklaces?|earrings?|handbags?|"
    r"clutch(?:es)?|sock(?:s)?|key\s*chains?|backpacks?|pocket\s*squares?)\b"
    r"|(?<!paper[\s-])(?<!paper)\bbags?\b"
    r"|shawl(?!\s*collar)"
    r"|(?<!black)(?<!black\s)watch(?:es)?(?!\s*maker)"
    r"|(?<!front\s)(?<!hair\s)(?<!waist\s)\btie\b(?!-)(?!\s+up\b)(?!\s*(?:[&]|and)?\s*(?:dye|die)\b)",
    re.I,
)
# "with ... belt/tie" describes a design detail already attached to another
# garment, not a standalone belt/tie being sold — real examples: "Barrel Fit
# Jeans With Belt Detail", "Long Dress With  Waist Belt", "BUTTON DOWN SHIRT
# WITH TIE DETAIL", "GRAPHIC TOP WITH TIE DETAIL". Every one of these had
# "with" somewhere before the belt/tie word, which a real standalone
# accessory listing ("Faux Leather Belt", "Poly Silk Tie") never does.
# Stripped out of the blob before ACCESSORY_RE runs rather than folded into
# that regex, since the gap between "with" and "belt"/"tie" is variable
# width and Python's re module requires fixed-width lookbehind.
GARMENT_DETAIL_RE = re.compile(r"\bwith\b.{0,40}?\b(?:belt|tie)s?\b", re.I)
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
    r"\b(shirts?|tops?|dress(?:es)?|jeans?|trousers?|jumpsuits?|jackets?|"
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
EASTERN_RE = re.compile(r"\b(kurta|kurti|shalwar|kameez|saree|sari|dupatta|sherwani|waistcoat)\b", re.I)

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
UNDERWEAR_RE = re.compile(r"\b(boxers?|briefs?|underwear|innerwear|panties|panty|undergarment)\b", re.I)
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

# "kurta pajama"/"kurta shalwar" is a two-piece SET, not the same product as
# a plain kurta sold alone — the two need different leaves. Checked before
# the bare kurta/kurti fallback so a combo phrase never collapses to "Kurta".
KURTA_COMBO_RE = re.compile(
    r"\bkurt[ai]\b[\s\w]{0,25}\b(pajama|payjama|shalwar)\b|\b(pajama|payjama|shalwar)\b[\s\w]{0,25}\bkurt[ai]\b",
    re.I,
)

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
TROUSER_RE = re.compile(r"\b(trousers?|jeans?|pants?|chinos?)\b", re.I)
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


def classify(store, p, title, product_type, tags, vendor, description):
    if GIFT_CARD_RE.search(title):
        return None  # excluded entirely, not just unbrowsable — not a product at all
    if TEST_PRODUCT_RE.search(title) or SHOPPING_BAG_RE.search(title) or SHOPPING_BAG_RE.search(product_type or ""):
        return None  # QA placeholder or checkout packaging bag, not real merchandise
    gender = guess_gender(store, title, product_type, tags, vendor, p=p, is_graphql=(store == "cougar"))
    blob = f"{product_type} {title}".lower()
    # Title-only view of the same blob — used wherever product_type
    # conflicts with what the title itself says (see its uses below: the
    # joggers-vs-footwear check, and the bottomwear title-first check
    # further down).
    title_blob = (title or "").lower()

    if FRAGRANCE_RE.search(blob):
        return dict(gender=gender, branch="Fragrance & Beauty", sub=None, leaf="Perfume",
                    style="not_applicable", construction="not_applicable")
    vest_blob = f"{vendor or ''} {product_type or ''} {title or ''} {description or ''}".lower()
    is_underwear_vest = (
        VEST_RE.search(blob)
        and VEST_UNDERWEAR_SIGNAL_RE.search(vest_blob)
        and not VEST_OUTERWEAR_SIGNAL_RE.search(vest_blob)
    )
    if (UNDERWEAR_RE.search(blob) or is_underwear_vest) and not EASTERN_RE.search(blob):
        return dict(gender=gender, branch="Accessories", sub=None, leaf="Underwear",
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
            ("Tie", re.compile(r"(?<!front\s)(?<!hair\s)(?<!waist\s)\btie\b(?!-)(?!\s+up\b)(?!\s*(?:[&]|and)?\s*(?:dye|die)\b)")),
            # "hat"/"beanie" fold into the same Cap leaf — no separate Hat
            # leaf exists in CATEGORY_TREE, and 34 real "Hat" + 129 real
            # "Beanie" titles/product_types ("Boonie Hat", "Bucket Hat",
            # "Ribbed Beanie") were landing in the generic Shirt default.
            ("Cap", re.compile(r"\bcaps?\b|\bhats?\b|\bbeanies?\b")),
            ("Cufflink", re.compile(r"\bcufflinks?\b")),
            ("Watch", re.compile(r"(?<!black)(?<!black\s)\bwatch(?:es)?\b(?!\s*maker)")),
            ("Sunglasses", re.compile(r"\bsunglass(?:es)?\b")),
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
            ("Bag", re.compile(r"(?<!paper[\s-])(?<!paper)\bbags?\b|\bhandbags?\b|\bbackpacks?\b|\bclutch(?:es)?\b")),
            ("Wallet", re.compile(r"\bwallets?\b")),
            ("Shawl", re.compile(r"\bshawl\b(?!\s*collar)")),
            ("Socks", re.compile(r"\bsocks?\b")),
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
        return dict(gender=gender, branch="Accessories", sub=None, leaf=leaf,
                    style="western", construction="not_applicable")
    if SCARF_RE.search(blob) and not OTHER_EASTERN_GARMENT_RE.search(blob) and not UNSTITCHED_RE.search(blob):
        return dict(gender=gender, branch="Accessories", sub=None, leaf="Scarf",
                    style="western", construction="not_applicable")
    if EASTERN_RE.search(blob) or UNSTITCHED_RE.search(blob) or SHIRT_TROUSER_SET_RE.search(blob):
        construction = "unstitched_fabric" if UNSTITCHED_RE.search(blob) else "ready_to_wear"
        sub = "Unstitched" if construction == "unstitched_fabric" else "Stitched"

        # Broadened to also catch the bare "-3P"/"-2P" SKU-suffix convention
        # (no trailing "c") that several Edenrobe titles use, on top of the
        # "3PC"/"3 Piece" phrasing the original pattern already covered.
        piece_count = None
        m = re.search(r"\b([1-4])-?p(?:c|ieces?)?\b", blob)
        if m:
            piece_count = int(m.group(1))
        elif sub == "Unstitched":
            # No explicit count stated — many unstitched listings only name
            # their constituent pieces ("Shirt Trouser Dupatta") rather than
            # giving a number. Counting the named pieces is a real, direct
            # signal, not a guess, and lands on the same 1/2/3-Piece leaves.
            named = sum(1 for kw in ("shirt", "trouser", "dupatta", "shawl") if kw in blob)
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
        elif KURTA_COMBO_RE.search(blob):
            # Checked ahead of the standalone sherwani/waistcoat check: a
            # "Kurta Pajama With Waistcoat" is fundamentally a kurta
            # ensemble that happens to include a vest, not a standalone
            # waistcoat suit — the kurta+pajama/shalwar phrase should win.
            leaf = "Kurta Set" if "kurta" in blob else "Shalwar Kameez"
        elif "sherwani" in blob:
            leaf = "Sherwani"
        elif "waistcoat" in blob:
            leaf = "Waistcoat"
        elif "kurti" in blob:
            leaf = "Kurti"
        elif "kurta" in blob:
            leaf = "Kurta"
        elif SHIRT_TROUSER_SET_RE.search(blob):
            # Edenrobe's own description confirms this is a stitched
            # Kurti+Trouser 2-piece ensemble ("Girls' Pret Kurti &
            # Trouser") even though the title itself never says
            # "kurta"/"kurti" — see SHIRT_TROUSER_SET_RE's definition.
            leaf = "Kurta Set"
        else:
            leaf = "Shalwar Kameez"
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
    title_says_footwear_not_joggers = FOOTWEAR_RE.search(title_blob) and not JOGGERS_RE.search(title_blob)
    if JOGGERS_RE.search(blob) and not title_says_footwear_not_joggers:
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
    bare_denim = re.search(r"\bdenim\b", blob) and not re.search(
        r"\b(jackets?|shirts?|dress(?:es)?|polos?|collars?|hoodies?|tees?|t-shirts?|tops?|sweatshirts?|vests?)\b", blob
    )
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
        r"\b(jackets?|shirts?|dress(?:es)?|polos?|collars?|hoodies?|tees?|t-shirts?|tops?|sweatshirts?|vests?)\b", title_blob
    )
    if TROUSER_RE.search(title_blob) or SHORTS_RE.search(title_blob) or bare_denim_title:
        src = title_blob
        leaf = "Shorts" if SHORTS_RE.search(src) else "Jeans" if re.search(r"\bjeans?\b", src) or bare_denim_title else "Trouser"
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
        leaf = "Shorts" if SHORTS_RE.search(blob) else "Jeans" if re.search(r"\bjeans?\b", blob) or bare_denim else "Trouser"
        return dict(gender=gender, branch="Western", sub="Bottomwear", leaf=leaf,
                    style="western", construction="ready_to_wear")
    if FOOTWEAR_RE.search(blob):
        footwear_leaf = "Sandals" if gender == "Women" and SANDAL_LEAF_RE.search(blob) else "Shoes"
        return dict(gender=gender, branch="Western", sub="Footwear", leaf=footwear_leaf,
                    style="western", construction="not_applicable")
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
    if re.search(
        r"\bco-?ord|suit\b"
        r"|\b[1-4]\s*-?\s*(?:pc|pieces?)\b"
        r"|\bcombos?\b(?!\s+(?:hoodies?|tees?|t-shirts?|shirts?|polos?|sweatshirts?|sweaters?|jackets?)\b)",
        blob,
    ):
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
        if "polo" in text:
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
        if re.search(r"\btanks?\b", text):
            return "Tank Top"
        if re.search(r"\b(tees?|t-shirts?|tshirts?)\b", text):
            return "T-Shirt"
        if "hoodie" in text or "hooded" in text:
            return "Hoodie"
        if "sweatshirt" in text or "sweat shirt" in text:
            return "Sweatshirt"
        if "sweater" in text:
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
        if "jacket" in text or "blazer" in text or re.search(r"\bcoat\b", text):
            return "Jacket"
        if re.search(r"\bdress\b(?!\s+(?:\w+\s+)?shirts?\b)|\bfrock\b", text):
            return "Dress"
        # A bare "vest" reaching this point is, by construction, NOT an
        # underwear vest (that's already been ruled out earlier via
        # is_underwear_vest) — real examples confirm it's genuine outerwear/
        # activewear (Engine Clothing's "Active Wear Vest", Cambridge's
        # "Quilted Vest"/"Sherpa Vest") that had no leaf of its own and fell
        # to the generic Shirt default. Checked after "sweater" so a real
        # "Sweater Vest" still resolves Sweater first (already handled by
        # the ordering above), and last among the specific garment checks
        # since a bare vest is the weakest signal of this group.
        if re.search(r"\bvests?\b", text):
            return "Jacket"
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
    leaf = _upperwear_leaf_from(title_blob) or _upperwear_leaf_from(blob) or "Shirt"
    return dict(gender=gender, branch="Western", sub="Upperwear", leaf=leaf,
                style="western", construction="ready_to_wear")


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
            tags, raw_source)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (brand_id, native_product_id) DO NOTHING
           RETURNING id""",
        (bid, native_id, p.get("handle"), title[:500], description, cat_id,
         cls["style"], cls["construction"], "adult", cls.get("piece_count"),
         tags, json.dumps(p)),
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

    variant_count = 0
    option_defs = p.get("options") or [] if not is_graphql else []
    for v in raw_variants:
        vf = normalize_variant_fields(v, option_defs, is_graphql)
        native_vid = vf["native_vid"]
        color_name = vf["color_name"]
        size_val = vf["size_val"]
        price = vf["price"]
        compare_at = vf["compare_at"]
        available = vf["available"]
        sku = vf["sku"]

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
                size_system, sku, current_price, current_compare_at, current_available)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (product_id, native_variant_id) DO NOTHING""",
            (pid, native_vid, cid_color, size_val, size_system, sku,
             price, compare_at, available),
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
