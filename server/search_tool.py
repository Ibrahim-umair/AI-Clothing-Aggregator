"""The OpenAI tool-call schema + system prompt for the search-filter
extraction step. Port of the SEARCH_TOOL/KNOWN_CATEGORIES/system-prompt
portion of server/search.js — copied verbatim, not paraphrased, since the
exact wording (worked examples especially) is what earlier real-query
testing tuned to fix specific extraction bugs.
"""

# Every real leaf category name in the live taxonomy (47, as of this
# writing) plus the 11 non-leaf grouping nodes (Upperwear, Bottomwear,
# Western, Accessories, ...) — refresh this list if CATEGORY_TREE changes
# (db/load_data.py). Added after a real, verified failure: without this,
# "furor jeans" ranked a keychain above real jeans, because NOTHING
# excluded the Accessories/Keychain leaf before ranking ever ran. This is
# now a hard SQL filter, same as gender — see rag.py.
KNOWN_CATEGORIES = [
    "1-Piece", "2-Piece", "3-Piece", "Bag", "Belt", "Cap", "Cargo Trouser", "Co-ord Set",
    "Cufflink", "Dress", "Formal Suit", "Frock", "Hoodie", "Jacket", "Jeans", "Jewelry",
    "Joggers", "Jumpsuit", "Keychain", "Kurta", "Kurta Set", "Kurta Shalwar", "Kurti",
    "Perfume", "Pocket Square", "Polo", "Sandals", "Saree", "Scarf", "Shalwar Kameez", "Shawl",
    "Sherwani", "Shirt", "Shoes", "Shorts", "Skirt", "Socks", "Suit", "Sunglasses", "Sweater",
    "Sweatshirt", "Tank Top", "Tie", "Tights", "Top", "Tracksuit", "Trouser", "T-Shirt",
    "Underwear", "Waistcoat", "Wallet", "Watch",
    "Upperwear", "Bottomwear", "Footwear", "Suits & Sets", "Formalwear", "Stitched", "Unstitched",
    "Western", "Eastern", "Accessories", "Fragrance & Beauty",
]

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_filters",
        "description": (
            "Extract structured shopping filters and the remaining semantic intent from a "
            "natural-language product search query for a Pakistani apparel marketplace."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "gender": {
                    "type": ["string", "null"],
                    "enum": ["Women", "Men", "Boys", "Girls", "Unisex", None],
                    "description": "Who the product is for, if stated or clearly implied. null if not mentioned.",
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string", "enum": KNOWN_CATEGORIES},
                    "description": (
                        "Every product TYPE the query asks for. Include MULTIPLE when the query names more "
                        "than one ('polos and tees' -> ['Polo','T-Shirt']). Use a broad grouping name "
                        "('Upperwear', 'Western', 'Accessories') when the query asks broadly rather than for "
                        "one specific garment ('upperwear under 2000' -> ['Upperwear']). Only include a name "
                        "if the query is genuinely about that type of product, not merely mentioning the word "
                        "in passing — e.g. an accessory whose name happens to contain a garment word must NOT "
                        "be treated as that garment. EMPTY ARRAY if the query names no product type at all "
                        "('grey clothes', 'something for a wedding') — that searches everything, which is correct."
                    ),
                },
                "minPrice": {"type": ["number", "null"], "description": "Minimum price in PKR, if a lower bound is stated. null otherwise."},
                "maxPrice": {
                    "type": ["number", "null"],
                    "description": (
                        "Maximum price in PKR, if an upper bound or budget is stated (e.g. 'under 5000', "
                        "'cheap' does NOT count as a number — leave null for vague budget words). null otherwise."
                    ),
                },
                "brand": {
                    "type": ["string", "null"],
                    "description": (
                        "One of the known brand names, ONLY if the user names a real brand explicitly. Known "
                        "brands: Breakout, Cambridge, Charcoal, Cougar, Diners, Edenrobe, Engine Clothing, "
                        "Equator, Furor, Lama, Meme, Monark, ONE (Be-One), Outfitters, Royal Tag, Uniworth, "
                        "Zellbury. null otherwise — never invent a brand name."
                    ),
                },
                "sizes": {"type": "array", "items": {"type": "string"}, "description": "Sizes explicitly requested (e.g. ['M'], ['L','XL']). Empty array if none."},
                "colors": {"type": "array", "items": {"type": "string"}, "description": "Colors explicitly requested, lowercase canonical English names (e.g. ['blue']). Empty array if none."},
                "onSale": {"type": "boolean", "description": "true only if the user explicitly asks for sale/discounted items."},
                "semantic_query": {
                    "type": "string",
                    "description": (
                        "ONLY the leftover descriptive words — fabric, style, occasion, mood, cut — after "
                        "removing everything already captured in the fields above. This is matched against "
                        "product text directly, so restating the category/price/gender/brand actively HURTS: "
                        "those are already enforced as exact filters, and repeating them drowns out the words "
                        "that actually distinguish one product from another. Write bare keywords, not a "
                        "sentence, and never a preamble like 'Searching for...'. Examples: 'Polos / Tees under "
                        "3000 knitted wear' -> 'knitted'; 'cozy warm sweaters for women under 5000' -> 'cozy "
                        "warm'; 'formal kurta for a wedding, men, under 8000' -> 'formal wedding'; 'furor "
                        "jeans' -> '' (nothing left over). Empty string is correct and expected whenever the "
                        "query is fully captured by the structured fields."
                    ),
                },
                "response_text": {
                    "type": "string",
                    "description": (
                        "A short, natural one-sentence confirmation of what's being searched for, written in "
                        "present tense as if results are being shown now (e.g. 'Here are cozy sweaters for "
                        "women under Rs. 5,000.'). Do NOT mention a specific count — that gets filled in separately."
                    ),
                },
                "suggested_refinements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "2-4 short SUBTYPE/STYLE/FIT keywords that would meaningfully narrow THIS specific "
                        "result set further — shown to the shopper as clickable next-query chips, so each one "
                        "must read naturally appended to the original query (e.g. for 'jeans under 3000': "
                        "['Slim fit','Relaxed fit','Ripped','High-waist']; for 'kurta for eid': "
                        "['Formal','Embroidered','Cotton']; for 'sneakers': ['Running','High-top','Slip-on']). "
                        "Never repeat the gender/category/price/brand/color already captured above — those are "
                        "already applied, a chip must add NEW information. Empty array when the query is "
                        "already narrow enough that no useful subtype distinction exists (e.g. a specific "
                        "brand+category+price combo, or a query with no clear category at all like 'grey clothes')."
                    ),
                },
            },
            "required": [
                "gender", "categories", "minPrice", "maxPrice", "brand", "sizes", "colors",
                "onSale", "semantic_query", "response_text", "suggested_refinements",
            ],
            "additionalProperties": False,
        },
        "strict": True,
    },
}

SYSTEM_PROMPT = "\n".join([
    "You extract search filters for a Pakistani apparel marketplace.",
    "",
    "Rules for `semantic_query`, which are strict:",
    "- It holds ONLY the words left over after everything captured by the other fields is removed.",
    "- It is matched directly against product text, so repeating a category, price, gender or brand that is already in another field actively degrades results.",
    "- Write bare keywords. Never a sentence. Never a preamble such as 'Searching for'. Never the original query verbatim.",
    "- An empty string is correct and expected whenever the structured fields already capture the whole query.",
    "",
    "Rules for `categories`:",
    "- Use the MOST SPECIFIC matching leaf(s) only. Never also include a broader grouping name (e.g. 'Upperwear', 'Western', 'Unstitched') alongside a specific leaf that already sits under it — the grouping adds nothing and only widens the result set.",
    "- Only fall back to a grouping name (e.g. 'Upperwear', 'Footwear') when the query genuinely has no more specific leaf in mind (e.g. 'any upperwear under 2000').",
    "- 'Unstitched'/'Stitched' describe Eastern fabric/garments only. An 'unstitched suit' or 'unstitched 3-piece' means the Eastern leaves ('1-Piece'/'2-Piece'/'3-Piece'/'Suit'), never 'Co-ord Set' or 'Suits & Sets' — those are Western, always ready-to-wear/stitched by definition, and must not be combined with 'unstitched' intent.",
    "- A tailored Western business/formal suit (blazer, lapels, waistcoat) is its own leaf, 'Formal Suit' — never 'Co-ord Set' (that's specifically a casual matching separates set — loungewear, resort wear, athleisure) and never 'Suit' (that's the unrelated Eastern Unstitched leaf). An athletic tracksuit is likewise its own leaf, 'Tracksuit', not 'Co-ord Set'.",
    "",
    "Rules for `suggested_refinements`: real, concrete SUBTYPES/FITS/STYLES of the category just matched (think of how a shopper would narrow down within these exact results), never a restatement of gender/price/brand/color. Bad: ['Men','Under 3000'] (already applied). Good, for 'jeans': ['Slim fit','Straight fit','Ripped'].",
    "",
    "Worked examples:",
    'query "Polos / Tees under 3000 knitted wear" -> categories ["Polo","T-Shirt"], maxPrice 3000, semantic_query "knitted"',
    'query "cozy warm sweaters for women under 5000" -> gender "Women", categories ["Sweater"], maxPrice 5000, semantic_query "cozy warm"',
    'query "furor jeans" -> brand "Furor", categories ["Jeans"], semantic_query ""',
    'query "formal kurta for a wedding, men, under 8000" -> gender "Men", categories ["Kurta"], maxPrice 8000, semantic_query "formal wedding"',
    'query "grey clothes" -> categories [], colors ["grey"], semantic_query ""',
    'query "unstitched 3 piece suits" -> categories ["3-Piece"], semantic_query "" (NOT ["3-Piece","Unstitched"] — Unstitched is 3-Piece\'s own parent and adds nothing)',
    'query "yellow lawn suits unstitched" -> categories ["Suit"], colors ["yellow"], semantic_query "lawn" (the Eastern Unstitched "Suit" leaf, NOT "Suits & Sets" — that\'s the Western, always-stitched grouping)',
    'query "off white tunics for women" -> gender "Women", categories ["Top"], colors ["off white"], semantic_query "" ("tunic" is this catalog\'s own "Top" leaf, not "T-Shirt")',
    'query "cargo trousers under 3000" -> categories ["Cargo Trouser"], maxPrice 3000, semantic_query "" ("Cargo Trouser" is its own real leaf now, NOT ["Trouser"] + semantic_query "cargo" — that used to let plain trousers rank alongside genuine cargo pants)',
    'query "formal 3 piece suit for men" -> gender "Men", categories ["Formal Suit"], semantic_query "" (a tailored Western business suit, NOT "Co-ord Set" — that\'s casual separates — and NOT "Suit", the unrelated Eastern Unstitched leaf)',
    'query "matching co-ord set for lounging" -> categories ["Co-ord Set"], semantic_query "lounging" (casual separates, distinct from "Formal Suit"/"Tracksuit")',
])
