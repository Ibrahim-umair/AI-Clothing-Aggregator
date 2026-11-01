# Next enrichment run: spec (draft, collecting requirements)

Status: requirements agreed with Ibrahim so far (2026-10-28). Nothing here is
built yet. No paid run starts until this spec covers every known problem.

## 1. Closures: quarter-zip, half-zip, full-zip

**Decision: no "Zip" category.** A zip is a closure, not a garment type.
In-stock zip products already sit across many categories (2026-10-28 count:
Hoodie 257, Polo 180, Sweater 160, Shirt 102 (mostly mis-filed "Upper"),
Sweatshirt 97, Jacket 94, Waistcoat 9, Vest 7, Co-ord Set 5, T-Shirt 4).
A quarter-zip knit is still a Sweater, and a quarter-zip fleece is still a
Sweatshirt, so a Zip category would pull products out of the categories
people browse.

**What the run must do:**
- The enrichment prompt tells the model to always name the closure of
  upperwear in both the description and the tags, using these exact words:
  `quarter-zip`, `half-zip`, `full-zip`, `zip-up hood`, `buttoned`, `pullover`
  (no closure). Consistent wording is what makes a search like "quarter zip"
  match across every category.
- The category follows the garment, not the closure:
  - knit or sweater fabric → Sweater
  - fleece or sweat fabric → Sweatshirt
  - with a hood → Hoodie
  - collared jersey → Polo
  - outer layer → Jacket
- The brand word "Upper" (Cougar and others) is resolved by what the photo
  shows: jacket, sweatshirt or sweater. It is never left as Shirt.

**Search:** nothing special. Because "quarter-zip" is in the text and tags,
it is matched by the keyword and vector legs, and the planner can put it in
`must_have`.

## 2. Joggers and trousers are interchangeable in search

**Decision:** shoppers use "joggers", "trousers", "pants" and "bottoms" for the
same things, so this is a search problem, not a categorization problem. A
search that names either one must show both.

- Categories stay as they are (Joggers and Trouser both remain), so browsing
  either still works.
- **Search rule:** when the planner names Joggers or Trouser, search both.
  Products of the exact type the user named rank naturally first, through
  text and vector relevance. They are not separated into an "alternatives"
  group.
- **Make this data, not code:** add a "searched together" link between
  categories in the taxonomy, editable from the review GUI. Search expands
  any category to its linked ones. Joggers ↔ Trouser is the first link;
  later ones are added the same way without code changes.
- Categorization still uses one rule for consistency, but a borderline call
  no longer hurts search:
  - Joggers = sweat, fleece or track fabric, or a cuffed elastic ankle.
  - Trouser = woven fabric with a straight or loose hem, even with a
    drawstring.
- Measured overlap (2026-10-28):
  - 135 products in Joggers look like trousers to the AI.
  - 105 products in Trouser look like joggers to the AI.

## 3. Unisex is shown under both genders

**Decision:** a unisex product (perfume, sunglasses, caps, bags, some tees) is
stored once and appears in Men AND Women search results, filters and category
pages, with a small "Unisex" badge.

**Problem today:**
- A gender filter only looks inside that gender's category tree, so the
  21 Unisex perfumes never appear for "men's perfume".
- The Unisex tree is mostly an "unknown gender" fallback: 305 of 328
  products never say "unisex" anywhere. For example, 56 Edenrobe ties
  (menswear), 67 Zellbury bags and 56 Zellbury shirts.
- Showing that bucket under both genders as-is would leak menswear into
  women's results.

**What to build:**
1. **Separate "unknown" from "unisex"** (keyword rules, before the run). An
   unknown gender goes to the store's default gender. Unisex only when the
   store's own text says unisex.
2. **The run decides who it's for:** in the same enrichment call, the model
   returns `audience` = Men / Women / Unisex (Boys / Girls / Kids for kids'
   stores), with a confidence level and a one-line reason. It uses the
   photos, the store text and the product type. High confidence is applied
   automatically; medium and low go to the review queue. No extra call.
3. **One query rule everywhere** (search v1 and v2, browse, filters): gender
   Men = Men tree + Unisex products of the same type; same for Women. Kids
   work the same way with a kids-unisex group.
4. Known now: 3 perfumes filed under Men say "unisex" in their text.

## 4. Categorization guide for the LLM (grows with every review)

Every review round has two outputs:
1. Keyword-rule fixes (local-notes/catreview/FINDINGS.md), so products the run
   hasn't processed yet start in a better place.
2. Short, general rules that go into the enrichment prompt, next to the
   category tree, so the model avoids the same mistakes.

This section collects (2). Lessons from review-exports/new-categories/
("Download problems & lessons") are added here.

**Keeping the prompt small:**
- Only general rules go in, never lists of products or brands. The
  keyword rules handle brand vocabulary ("Upper", "W/C", "5 Pocket",
  typos).
- The rules below are ~350 tokens and sit in the cached prefix with the
  category tree, so they cost almost nothing per product.
- The keyword-rule category goes in as a one-line hint: "Rules say: X
  (keyword match)", or "Rules: Uncategorised". It is never stated as the
  answer.
- New lessons replace or merge with existing lines; the list should not
  just grow.

**Already in the keyword rules (db/load_data.py):**
- 2026-10-28: 77% of the 2,464 reviewed products came out right, up from 0%.
- 2026-11-01, six rounds checked against the AI's photo label for all 45,693
  in-stock products (db/check_rules_vs_photos.py, no LLM calls):
  - Agree with the photo: 96.5% → 98.4% (rule-writing stores).
  - Held-back stores (Bandana, Furor, Royal Tag): 93.0% → 98.6%. The
    Furor jump came from the "Co-Ord Set Shirt" rule, which Zellbury and
    Cambridge also needed, so Furor is no longer a blind test.
  - Reviewed products right: 77.2% → 91.2%. Uncategorised: 295 → 71.
  - Rules are general naming habits, never store names. Examples: the last
    garment word decides ("Tunic Dress"); a top and a bottom named together
    are a set; women's "2PC/3PC" is an Eastern suit; a store type naming a
    kurti beats a title that only says "Shirt"; "Upper"/"Zipper" is read
    from the description (hood, knit, else jacket); a men's bare "Coat" is
    a blazer; "Co-Ord Set Shirt" is one piece sold on its own.
  - New stores: run the check after the first scrape. The groups it lists
    are the next rule round.
- Unknown products go to "Uncategorised" (not shown in menus), not Shirt.
- The AI call decides those, plus everything the keyword rules can't see:
  - length (tunic vs. dress)
  - "Upper"/"Zipper" (jacket, sweatshirt or hoodie)
  - heels vs. sandals
  - blazer vs. long coat
  - gender from the photo

**How to decide:**
- Decide category and gender from the **photos** first. The store's text
  and our current category are hints that are often wrong, never the
  answer.
- Pick the most specific EXISTING category. Style, fit, fabric or closure
  is never a reason for a new category.
- Name the garment by its head noun; other garment words are modifiers.
  "Pin buckle belt" is a Belt, "brooch heels" are Shoes, "cargo shirt" is a
  Shirt, "denim jacket" is a Jacket, "towel terry joggers" are Joggers.

**Gender:**
- Judge from the cut and fit and from the model wearing it, not from the
  store's category.
- Men / Women / Unisex; for kids, Boys / Girls / Kids.
- "Teens" in Diners titles means girls.

**Sets:**
- Two or more pieces sold together ("X with Y", "+", Set, Combo, 2PC/3PC)
  are a set, never one of the pieces.
- A tie boxed with a pocket square and/or cufflinks is a Gift Set; a tie
  alone is a Tie.

**Specific types:**
- **Blazer:** a tailored jacket sold on its own. With matching trousers it
  is a Formal Suit.
- **Sandals & Slides:** open footwear (sandals, slides, flip-flops,
  chappals, peshawari) is not Shoes.
- **Dupatta:** sold on its own, it is a Dupatta, not a Scarf. As part of
  a suit it is not a separate product.
- **Pajama:** a plain pajama or shalwar sold to wear with a kurta is
  Shalwar & Pajama (Eastern). A printed or matching sleep or lounge set is
  Nightwear & Loungewear.
- **Tracksuit vs. Co-ord Set:** a Tracksuit is activewear, made for
  sport or the gym. It has a technical, sporty fabric, a track-jacket cut
  and is sold as sportswear. A matching top and bottom in soft fleece,
  knit or sweat fabric made for casual or lounge wear is a Co-ord Set,
  even when the store or the AI calls it a "tracksuit". Example: Engine
  "Boys Suit" sets. Tracksuit and Co-ord Set are searched together (same
  idea as Joggers ↔ Trouser, section 2).
- **Suspenders:** a category of their own (Men > Accessories >
  Suspenders), not merged into Belt.
- **Pins & Clips:** lapel pins, tie pins, tie bars, collar bars and
  brooches. Hair clips go to Hair Accessories.
- **Tops vs. upperwear:** "Upper", "Zipper" and "Pullover" are brand words;
  decide jacket / sweatshirt / sweater from the photo. A Zellbury "Tunic"
  that reaches the calf or ankle is a Dress.
- **Fabric:** unstitched fabric is Unstitched (Men or Women Eastern), never
  Shirt.
- **Not apparel:** towels, candles, shoe care, skincare and makeup. Mark
  them as not apparel; they are hidden.

## 5. Also in scope (from earlier decisions; detailed later)

- **Category in the main enrichment call:**
  - full category tree in the prompt
  - high / medium / low confidence, or "none fits" with a proposed new
    category
  - most specific existing category; style, fit, subtype or closure is
    never a new category
- **All photos per product (max 12):**
  - versions and colors per version
  - store color names mapped to versions
  - stock tracked per version
- **Sold-out products:** fully sold-out products get no LLM call and no
  embedding; a product is enriched when it comes back in stock.
- **Scrape pipeline:** small scrape (no LLM) 3–4×/day; heavy processing
  through a queue.
- **Open checks:**
  - Cougar showing 100% in stock
  - ~1,100 photo-less products
  - Monark
  - Cougar fix to master
  - prod migration
- **Manual category review:**
  - rounds 1 and 2 approved, about 1,000 products to apply
  - 380 still open on review-exports/category-decisions-v2/
  - keyword-rule fixes in local-notes/catreview/FINDINGS.md
