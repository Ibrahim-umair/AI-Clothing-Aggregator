# Classifier changelog

Every entry here is a real bug found against real scraped data (not hypothetical), with the
exact example that exposed it. `test_classify.py` has one regression test per entry below —
run it before trusting any future change to `classify()`/`CATEGORY_TREE`/`guess_gender()`.

This log exists specifically because this classifier will run against fresh daily scrapes —
a fix here needs to stay fixed, and a new bug found next month needs a paper trail like this
one, not just a one-off patch.

## 2026-08-23

1. **Gender substring bug** — `"men" in blob` matched inside `"women"`/`"woman"` literally,
   so every women's product silently landed under Men. Fixed with word-boundary regex
   (`\bwomen\b` checked before `\bmen\b`). *Symptom: Women count was exactly 0.*
2. **Unisex had no Western/Eastern branches** in `CATEGORY_TREE` — 20,276 products defaulting
   to Unisex had nowhere to go and got `category_id = NULL`.
3. **Category-card link resolution too strict** — cards link with only `{gender, category}`
   (no branch/sub), but the resolver required contiguous levels and silently dropped the
   category filter, returning every product for that gender. Fixed with a deep-search
   fallback in `server/taxonomyTree.js`.
4. **`\bshort\b` too greedy** — matched "Short Sleeve Shirt/Polo/Henley" (an upperwear
   attribute) as Bottomwear. Fixed: require plural "shorts", or singular "short" not
   immediately followed by "sleeve".
5. **No underwear/innerwear detection** — boxers/briefs/vests fell into the generic
   Western→Upperwear→Shirt bucket. Added `UNDERWEAR_RE`, new "Underwear" leaf under
   Accessories for every gender. *Example: "BOXER (PACK OF TWO)" → was "Shirt".*
6. **"Kurta Pajama"/"Kurta Shalwar" collapsed into plain "Kurta"** — a two-piece set and a
   single top are different products. Added `KURTA_COMBO_RE`, routes combo phrases to
   "Kurta Set" before the bare kurta/kurti fallback.
7. **Boys' tree had "Kurta Shalwar" but classify() emits "Kurta Set"** — name mismatch meant
   every Boys combo kurta fell back to the bare "Eastern" branch node. Renamed for
   consistency with Men's tree.
8. **Girls' Eastern→Stitched had no "Shalwar Kameez" leaf** for kurti+shalwar combos.
9. **Leaf-picking used the category *slug* as the search keyword**, not the actual word root
   — "jewelry"/"sunglasses"/"socks" never literally appear in a title ("jewel"/"sunglass"/
   "sock" do), so these three always silently fell to the "Bag" default.
   *Example: "Jewel - EMUB22S-JEWEL" → was "Bag".*
10. **"shawl" collided with "Shawl Collar Sweater"** — a Western garment named for its collar
    style, not an actual shawl accessory. Excluded `shawl(?!\s*collar)`.
11. **Sherwani/Waistcoat had no branch-routing keyword** — fell into generic Western
    Suits&Sets/Shirt despite "Waistcoat" already existing as a valid Eastern leaf in the
    tree. Added both to `EASTERN_RE` plus explicit leaf handling.
12. **Girls' tree missing Jeans (Bottomwear) and the entire Suits & Sets branch** —
    real Girls' co-ord sets and jeans existed in the data with nowhere valid to land.
13. **Unstitched items with no explicit "2pc/3pc" numeral got no piece-count at all** — many
    Edenrobe titles use a bare `-3P` SKU suffix (no trailing "c"), or only name the pieces
    ("Shirt Trouser Dupatta") without a number anywhere. Broadened the numeral regex and
    added a named-piece-counting fallback (counts shirt/trouser/dupatta/shawl mentions).
14. **No catch-all "Suit" leaf for Unstitched** when truly nothing else can be determined
    (e.g. a bare "Lawn Suit") — added per gender, used only as the last resort.
15. **Bare `"sweat" in blob` matched "Sweatpant" as well as "Sweatshirt"** — compound word,
    no space, so `\bpants?\b` never caught it either; fell through to the Sweatshirt default.
    *Example: "Solid Sweatpant" (Cambridge) → was "Sweatshirt".* Added an explicit
    sweatpants/joggers/track-pants check ahead of the Sweatshirt fallback, and a new
    "Joggers" Bottomwear leaf.
16. **No "Hoodie" category at all** — hoodies fell into the generic Sweatshirt bucket.
    Added as its own Upperwear leaf, checked before the Sweatshirt fallback.
17. **"watch" collided with fabric/pattern names** — "(Watch Maker)" and "Blackwatch" are a
    weave-pattern name and an internal collection label, not wristwatches.
    *Example: "BLENDED TEXTURED (WATCH MAKER)" (Cambridge/Mashriq, an Eastern unstitched
    fabric) → was "Watch".* Excluded `watch(?!\s*maker)` plus a `black watch`/`blackwatch`
    lookbehind.

## 2026-08-23 (second pass — found via `test_classify.py` and a fresh random sample)

18. **Boys' tree had no "Polo" leaf at all** — "Boys Polo Tee" fell to the branch node
    despite "polo" being detected correctly. Added.
19. **Girls'/Boys' Accessories had no "Sunglasses" leaf.**
20. **Girls' Upperwear had no generic "Shirt" leaf** (only T-Shirt/Top/Dress) — anything not
    matching a more specific keyword (blouses, plain shirts) fell to the branch node.
21. **"Dress Shirt" collided with the "Dress" leaf** — a men's formal shirt (adjectival
    "dress"), not a women's one-piece garment, but "dress" was checked before the final
    "Shirt" fallback with no exclusion. Same fix pattern as "short sleeve"/"shawl collar":
    `\bdress\b(?!\s*shirt)`.
22. **No "Tights"/"Leggings" detection or leaf at all.** Added to Bottomwear (this is a
    leg-worn item, not upperwear — caught and fixed before merging into the wrong sub).
23. **"denim" alone (without the word "jean") wasn't a Bottomwear signal** — "Girls Flared
    Denim" fell through entirely.
24. **Regressions caught by the test suite before reaching production data** (this is exactly
    why the suite exists): (a) adding the denim check made "Denim Shorts" resolve to Jeans
    instead of Shorts — fixed by checking Shorts first; (b) `\bsunglass\b` doesn't match the
    actual plural "sunglasses" (same word-boundary class of bug as `tshirt\b`) — fixed to
    `sunglass(?:es)?`; (c) fixing that then broke the *existing* passing "Jewel -> Jewelry"
    case because the same-pass regex edit used `jewel(?:le)?ry?`, which requires a trailing
    "r" and no longer matches bare "jewel" — fixed to `jewel(?:l?ery|ry)?`.

## 2026-08-23 (third pass — kids-gender bug, vendor priority, "frock" domain error, stale API cache)

25. **Kids-range sizing was never checked at all** — items sized "3-4 years"..."9-10 years"
    or toddler codes "T1"-"T4" have nothing to do with adult sizing, but with no textual
    gender word anywhere they fell straight to `STORE_GENDER_DEFAULT`, which is calibrated
    for that store's *adult* catalog. *Example: "Junior Magenta Pajama Suit" (Diners),
    sizes 3-4/5-6/7-8/9-10 years + T1-T4 → was "Men".* Added `KIDS_SIZE_RE` +
    `has_kids_sizing()` as a last-resort check (after every textual signal has already had
    a chance), routing to Unisex rather than guessing a specific gender with no basis.
26. **"Junior"/"toddler"/"infant" were never checked as gender words at all** — only
    "kids" was. The example above also had "Junior" right in the title.
27. **Generic Women/Men patterns checked across the whole noisy tag blob could override a
    reliable vendor signal.** A real Cougar item had vendor `"COUGAR GIRL (S-V2-2026)"`
    (decisive) but also a stray `"Women-Jacquard"` tag (a shared fabric-batch label bleeding
    across genders) — checking "women" before "girls" across the *combined* blob let the
    noise win. Fixed: vendor is now checked in isolation first and wins outright if it
    resolves anything; the full blob (including tags) is only the fallback.
28. **"frock" was wrongly treated as Eastern-specific.** Checked all 11 real Cougar uses
    (their own `productType: "Girl Frock"`) — every single one is a plain Western casual
    dress (Polka Dot Dress, Tie & Dye Dress, Asymmetrical Smocked Dress...) with zero Eastern
    styling. It's generic Pakistani-English for "girl's dress," not a garment type. Removed
    from `EASTERN_RE`, added as a Dress synonym in the Western fallback instead, removed the
    now-dead "Frock" leaf from Girls' Eastern tree.
29. **The API server's category tree was cached in memory with no refresh mechanism at all**
    — every category added via `reseed_categories.py` after the server started (Hoodie, the
    Unstitched "Suit" catch-all, Socks, Sunglasses...) was invisible through the live API and
    frontend even though it existed correctly in the database. Not a classification bug — a
    deployment one, and one that would silently bite an unattended daily pipeline (a cron job
    can't rely on someone noticing "Hoodie is missing" and remembering to restart a Node
    process). Fixed properly, not just documented: `server/taxonomyTree.js` now re-fetches
    the tree if the cache is older than 5 minutes, instead of requiring a manual restart.

## 2026-08-23 (fourth pass — proactive sweep while unattended: "Equator Test"/"Shopping Bags"
report plus a full branch-level-orphan audit of the whole catalog)

30. **QA/placeholder products left live on the storefront.** "Test" (Equator, Rs. 10),
    "Test XPay" (Monark, a payment-gateway test SKU), "MEN T-SHIRT (TEST)" (Breakout, an
    otherwise real-looking Rs. 3499 listing with a stray "(TEST)" suffix) are not real
    merchandise. Added `TEST_PRODUCT_RE`, excluded the same way gift cards are.
31. **Checkout/packaging "Shopping Bag" listings** ("Outfitters Shopping Bag" Rs. 20-40,
    "Shopping Bags" Equator) are add-on packaging, not a fashion accessory. Added
    `SHOPPING_BAG_RE`, excluded.
32. **`backfill_categories.py` never actually removed a newly-excluded product** — when
    `classify()` starts returning `None` for a product that was already loaded with a real
    category (exactly what #30/#31 needed), the script just skipped the category-id update
    and left the stale row in place, so the exclusion silently never took effect on already-
    scraped data. Fixed to `DELETE` the row (cascades to variants/images/pieces), matching
    what the original loader does for a `None` result.
33. **Men's/Unisex Accessories had no "Bag" leaf at all** — real products ("Men Bag",
    "Crossbody Bag", "Duffle Bag") were resolving correctly to leaf="Bag" but landing on the
    bare Accessories branch node since the leaf didn't exist in the tree. Same root cause as
    changelog #7/#9. Found via a full audit: **every product whose resolved category has no
    `parent_id` gap two levels down (i.e. sits on a branch node, not a real leaf) is a tree-
    shape bug** — this pass ran that audit against the whole catalog and fixed every hit
    (over 1000 products total across items #33-45 below), not just the one reported case.
34. **Vendor's age-only word ("junior") could out-rank an explicit gender word found
    elsewhere.** Vendor "CAMBRIDGE JUNIOR" was winning gender resolution outright via the
    vendor-priority fix (#27) and returning Unisex before ever checking that store's own
    tags, which said "BOYS SWEATER" explicitly — 712 real Cambridge Junior products (kurtas,
    shalwar kameez, polos, jeans, sweaters, hoodies) were losing an explicit Boys/Girls
    signal to a strictly weaker age-only one. Fixed by splitting `GENDER_PATTERNS` (explicit
    gender words, eligible for the vendor-wins-outright short-circuit) from a new
    `AGE_ONLY_RE` (kids/junior/toddler/infant — checked only after vendor AND the full blob
    have both had a chance to find something more specific).
35. **The Unisex category node had no Western/Eastern branches at all, only Accessories** —
    genuinely gender-ambiguous kids items (no gender word anywhere, not even in the store
    default) had gender correctly resolving to Unisex but nowhere real to land. Added full
    Western/Eastern/Fragrance & Beauty branches mirroring the other genders.
36. **Boys'/Girls' Western branch had no "Footwear" sub-branch**, Boys'/Girls' Eastern
    Stitched had no "Shalwar Kameez"/"Waistcoat"/"Sherwani"/"Kurta"/"Kurta Set" leaves,
    Men's/Women's/Girls' Accessories were missing various leaves (Shawl for Men; Tights/Polo
    for Women's Western; Jacket/Polo for Girls' Western; Belt/Watch/Wallet/Cap variously
    across Boys/Girls/Women), Men's Western Bottomwear had no "Tights", and Boys/Girls/Men/
    Women were variously missing a "Fragrance & Beauty" branch for real kids'/men's perfume
    products ("BOYS STAR WARS PERFUME", vendor "KIDS"). All real products, all found via the
    same branch-level-orphan audit — each one added to whichever gender's tree was missing
    it.
37. **The leaf-picker for Accessories stripped spaces before substring-matching keywords**,
    with no word-boundary protection — "Women Printed Cape Shawl" resolved to leaf="Cap"
    because bare `"cap"` matches inside `"...printedcapeshawl"` once spaces are gone. Rewrote
    the whole keyword list as proper `\b`-anchored compiled regexes (matched against the
    blob as-is), which also fixed a second latent bug: a generic multi-item product_type
    bucket like "BAGS & WALLETS" (real: "Soccer School Backpack", "Lion Themed Pencil Case")
    was resolving to "Wallet" purely because "wallet" was checked before "bag" in the old
    list — reordered and now checked against the TITLE first, full blob only as a fallback.
38. **"tie" collided with several unrelated real phrases**: "Tie Dye"/"Tie & Dye"/"Tie & Die"
    (a fabric-print name, "die" being a common real misspelling — Furorjeans), "Front Tie"/
    "Tie Up" (a design detail on a top's closure, with or without a hyphen — "Front Tie Top",
    "Tie-Waist Playsuit", "Tie Up Jumpsuit"), and "Hair Tie" (a hair accessory, not a
    necktie). Dozens of real T-shirts/joggers/polos/dresses/jumpsuits were misfiled into
    Accessories>Tie, or stranded on the bare branch node for genders whose tree had no Tie
    leaf at all. Excluded all of the above from the Tie keyword while keeping real neckties
    ("Poly Silk Tie", "Bow Tie", "Tie Pin") working.
39. **"belt"/"tie" as an attached design detail on another garment**, not a standalone
    product — "Barrel Fit Jeans With Belt Detail", "Long Dress With Waist Belt", "BUTTON
    DOWN SHIRT WITH TIE DETAIL" were misfiled into Accessories. Every real example had "with"
    somewhere before the belt/tie word (a real standalone listing never does), so
    `GARMENT_DETAIL_RE` strips a "with ... belt/tie" phrase out of the blob before
    accessory-keyword matching runs, rather than trying to fold a variable-width exclusion
    into the regex itself.
40. **Unstitched fabric with a bare garment-name word resolved to a Stitched-only leaf name**
    — "UNSTITCHED KURTA COLLECTION" (Mashriq) resolved to leaf="Kurta", which isn't a real
    leaf under any gender's Unstitched sub-tree (only piece-count and "Suit" are), stranding
    it on the bare branch node. Reordered so the Unstitched sub short-circuits straight to
    piece-count-or-"Suit" and never runs the Kurta/Kurti/Waistcoat/Sherwani checks at all
    (Saree is the one exception — it's a real Unstitched leaf too).
41. **"Dress...Shirt" collision reappeared with an intervening word** — "Purple Dress
    Stripes Shirt" still resolved to "Dress" since the existing exclusion (#21) only handled
    direct adjacency. Broadened to allow one word between "dress" and "shirt", and fixed a
    self-introduced regression from that same change in the same pass: `shirt\b` doesn't
    match the plural "shirts" (product_type "dress shirts"), the exact word-boundary/plural
    bug class documented in #9/#24 — caught by re-running the full branch-orphan audit after
    the fix and seeing Men>Western jump instead of shrink.
42. **"Kurti" (a girls'/women's-only garment name in this catalog's own taxonomy) could be
    out-voted by a stray tag containing "boys"** — a real Diners/Sohaye item had the compound
    tag `"girls-western&boys-eastern-western"` (containing the literal word "boys") win
    gender resolution over its own clean `"girls-eastern"` tag. Since "Kurti" never applies
    to a boy/man anywhere else in this catalog's taxonomy, `classify()` now corrects gender
    to Girls/Women whenever it's about to emit a Kurti leaf for a Boys/Men-resolved item.

This pass was run proactively (per standing instruction to keep sweeping for errors), not
just against the one reported bug — after each fix, a full "does any product sit on a
branch node instead of a real leaf" audit was re-run against the live database until it
returned zero rows. It went from over 1000 stranded products to 0.

## 2026-08-24 (fifth pass — user-reported "denim terry polo in Jeans")

43. **Bare "denim" is a fabric name, not a bottomwear signal on its own.** It was being
    treated as an unconditional Jeans/Bottomwear trigger regardless of what else was in the
    title — real examples: "DENIM COLLAR POLO", "POLO SHIRT DENIM COLLAR", "DENIM JACKET",
    "DENIM SHIRT - BLUE", "Embroidered Denim Dress" were all resolving to Jeans, when the
    actual garment is a polo/jacket/shirt/dress that merely uses denim fabric or trim. Fixed:
    a bare "denim" mention (no explicit "jean"/"trouser"/"short" word) no longer triggers
    Bottomwear if a stronger upperwear/dress keyword (jacket, shirt, dress, polo, collar,
    hoodie, tee, top, sweatshirt) is also present in the same title. Genuine denim
    bottomwear ("Baggy Fit Denim", "Girls Flared Denim", "Denim Shorts") is unaffected.
    412 products recategorized on backfill.

## 2026-08-27 (sixth pass — user asked "don't we have a sweater category?")

44. **"Sweater" was a leaf defined only in Men's `CATEGORY_TREE` but `classify()` never
    actually emitted it anywhere** — real sweaters (a knitted pullover, distinct from a
    "Sweatshirt") across EVERY gender were falling through to the generic "Shirt" bucket.
    1,482 real products confirmed this via a direct query (title matches `\ysweater\y` but
    not "sweatshirt") — vendor/product_type is literally "SWEATERS" on many of them ("Basic
    Textured Sweater", "Crew Neck Knitted Sweater", Furorjeans product_type "Men Sweaters").
    No word-boundary collision risk with "Sweatshirt" (the words don't share a substring).
    Added an explicit `"sweater" in blob` check to the Western/Upperwear fallback chain, and
    added the "Sweater" leaf to Women's/Boys'/Girls'/Unisex's trees (only Men's had it,
    unreachably). 1,665 products recategorized on backfill — Men 1,199, Boys 196, Women 143,
    Girls 125, Unisex 2.

## 2026-08-28 (seventh pass — user-reported "short sleeves shirts under women shorts", "vest in underwears")

45. **Women's "Shorts" was catching real upperwear, dresses, and outerwear** — user spotted
    this directly by browsing the live site. Four distinct root causes, all in `SHORTS_RE`
    or the bottomwear-resolution logic:
    - The sleeve exclusion only handled a whitespace-separated "sleeve"/"sleeves" — real
      titles use a hyphen ("Short-Sleeve Shirt", "Short-Sleeved Sweater",
      "Textured Short-Sleeved Shirt") or the "-d" adjective suffix, neither of which the old
      `(?!\s*sleeves?)` lookahead matched, so they fell straight into Shorts.
    - Bare singular "short" as a LENGTH ADJECTIVE ahead of another garment noun ("Oversized
      Short Coat", "SHORT DRESS FOR WOMEN", "PRINTED SHORT DRESS FOR WOMEN",
      "Woolen Short Coat") isn't the garment "shorts" at all. Excluded via a lookahead for a
      small, real-example-driven noun list (coat/dress/jacket/blazer) allowing up to two
      intervening words, since Engine Clothing's "Women Shorts Body Blazer"/"...Body Jacket"
      (9 real products — confirmed via vendor/tags that this is a literal line-naming
      convention, not a garment description) has a word between "Shorts" and the noun that
      disambiguates it.
    - Once excluded from Shorts, "blazer" and bare `\bcoat\b` needed to route to the existing
      Jacket leaf (no separate Blazer/Coat leaf exists) — added alongside the existing
      "jacket" check. This incidentally fixed a separate, previously-unnoticed bug found
      while investigating: real coats (Charcoal Clothing's "BAN COLLAR LONG COAT" line, Girls
      Junior's "Basic Button Up Coat", product_type literally "OUTERWEAR"/"long coats") were
      all resolving to the generic "Shirt" leaf with no coat-specific handling anywhere.
    - Shopify's own `product_type` field is sometimes just wrong: ONE Be-One's "Basic Barrel
      Jeans" has `product_type: "Shorts"` (a store-side mislabel — tags say "Women
      Bottoms-Jeans"/"WOMEN_DENIM_JEANS_TWILL_PANTS", nothing about the item is short) and
      since the bottomwear check searched the full `product_type + title` blob, the mislabel
      won over the title's own explicit "Jeans" every time. Fixed by checking the TITLE alone
      first (same title-first/blob-fallback precedent already used for the Accessories leaf
      lookup) — a bottomwear signal in the title now wins outright before `product_type` is
      even consulted; `product_type` is only consulted as a fallback when the title itself
      has no bottomwear word at all (preserves correct behavior for titles like "Striped
      Pleated Jorts", which rely entirely on `product_type: "SHORTS"` since "jorts" doesn't
      contain the substring "short"). 1,806 products recategorized on backfill (this and #46
      combined — see #46 for the larger share).

46. **Bare "vest" was an unconditional Underwear signal — genuinely wrong for most real
    "vest" listings in this catalog.** User spotted a vest under Women's Undergarments;
    querying the live Underwear category turned up ~90 real "vest" titles, and the large
    majority were actual outerwear/activewear/formalwear, not underwear: Cambridge's
    Quilted/Padded/Sherpa/Contrast-Quilted Vest line (vendor "Jackets"), Cougar's Sweater
    Vests, Engine Clothing's Active Wear Vests, Furor's Vest Gilets/Vest Jackets, Equator's
    Training/Sweater Vests, Cambridge's own Suiting Vests, and "Vest T-Shirt" tank tops.
    Removed bare `vests?` from `UNDERWEAR_RE` entirely and replaced it with a signal-gated
    check: a "vest" only resolves to Underwear when an explicit undergarment word ("sando" —
    the real Pakistani-market term for a men's undergarment tank — or "undergarment" itself)
    is present in vendor/product_type/title/**description**, and no outerwear signal
    (jacket/gilet/sweater/hoodie/quilted/puffer/sherpa/suit/activewear/tee/tank top) is also
    present. The description field matters here: Uniworth's 5 real vest listings ("White
    Plain Sleeveless Ribbed Vest", "Black Seamless Vest", etc.) have no undergarment word
    anywhere in vendor/product_type/title, only in the product description itself ("...our
    sporty undergarment will keep you cool...", confirmed against real `raw_source`
    `body_html`) — this is the one place in `classify()` that checks description text, since
    every other pattern only ever needed title/vendor/tags/product_type. A disqualified vest
    (e.g. a puffer/quilted vest with no "jacket"/"blazer"/"coat" word anywhere) now falls to
    the generic Western Upperwear default instead of Underwear — correctly out of the wrong
    category, though not always perfectly leaf-categorized; flagging this honestly as a known
    residual gap rather than claiming full precision. 1,806 products recategorized on
    backfill (combined with #45 above — most of this delta is #46, since it touches ~90 real
    titles across 8+ brands vs. #45's ~26 in one category).

After fixing #45/#46, the standard branch-level-orphan audit (every product whose
`category_id` sits on a branch node instead of a real leaf) was re-run as usual — it isn't
new work triggered by these two fixes specifically, but re-running it after any classify()
change is what has caught every latent gap since the fourth pass. It found 125 products,
all pre-existing and unrelated to #45/#46:

47. **Women's `CATEGORY_TREE` only ever defined a "Kurti" leaf under Eastern/Stitched, never
    "Kurta"** — but `classify()` has always been able to emit `leaf="Kurta"` for a Women's
    product (any title saying "kurta" without "kurti"), with nowhere for it to resolve. Boys/
    Girls/Men's trees all already had both. Latent until Zellbury was added earlier this
    session: its real listings ("Embroidered Kurta - 2274", "Kurta Dupatta Trouser - 0762",
    111 real products) use "Kurta" for women's wear, not "Kurti", and were all stranding on
    the bare Eastern branch node. Added the missing leaf; 124 products recategorized on
    reseed+backfill.
48. **"waist tie" (a garment's self-tie closure detail, e.g. a wrap top or dress) was
    matching the Tie accessory keyword** meant for actual neckties — same collision class as
    the existing "front tie"/"hair tie" exclusions, just not one that had shown up yet. One
    real example, "TEXTURED WAIST TIE TOP" (Breakout, Women) — CATEGORY_TREE has no Tie leaf
    for Women at all (only Men/Unisex), so it was stranding on the bare Accessories branch
    node. Added "waist" to the same lookbehind exclusion.

## 2026-08-28 (eighth pass — user-reported "Furor Jeans Club Keychain in Jeans of men")

49. **"keychain" was never recognized as an accessory anywhere in `classify()`** — 9 real
    Furor products (`product_type` literally "Key Chains") had nowhere to resolve. The 2
    with "jeans" in the title ("Furor Jeans Club Keychain", "Furor Jeans Keychain" — "Jeans"
    here is the brand's own line name, Furor's vendor is literally "Furorjeans") fell through
    to the bare-"jeans" Bottomwear check (`ACCESSORY_RE` ran first but never matched
    "keychain", so it never intercepted them) and landed in Men's Jeans; the other 7 (no
    "jeans" in the title — "Acrylic Keychain", "Fire Keychain", "FJ Keychain", "Insignia
    Keychain", "Leather Keychain") fell through every branch to the generic Western
    Upperwear "Shirt" default. Added "keychain"/"key chain" to `ACCESSORY_RE` and
    `_KEYWORD_LEAVES`, and a new "Keychain" leaf to `CATEGORY_TREE` — recognizing the actual
    accessory type fixes the Jeans collision at the source rather than special-casing "jeans"
    again.
50. **Bare-"denim" exclusion list only had singular garment nouns, no "vest" at all** — real
    example "Hooded Denim Vest" (Furor, `product_type` literally "Men Jackets", **plural** —
    the original singular-only "jacket" in the exclusion regex never matched it) was
    resolving to Jeans purely because of "denim" in the title, same collision class as
    "DENIM JACKET"/"Denim Shirt" (fix #43). Broadened the exclusion list to plural-safe forms
    and added "vest(s)".
51. **Two more real gender-tree gaps, same latent-gap class as #47, found by the same
    branch-level-orphan audit while verifying #49/#50:**
    - Real Zellbury "Kurta Shalwar" combo listings (6 products, e.g. "Kurta Shalwar - 1679")
      hit `KURTA_COMBO_RE` and resolve `leaf="Kurta Set"`, which Men/Boys/Girls already had
      but Women's tree didn't (fix #47 only added plain "Kurta"). Added "Kurta Set" to
      Women's Eastern/Stitched tree.
    - Real Outfitters "Multi-Charm Keychain"/"Crochet Keychain"/"Bear Charm Keychain"/"Ribbon
      Keychain" (5 products, vendor "Women", `product_type` "JEWELLERY") — the "Keychain"
      leaf added for #49 only went to Men's tree. Added "Keychain" to Women's Accessories
      tree too.

    22 products recategorized across #49/#50/#51 combined on reseed+backfill.

## 2026-08-28 (ninth pass — orphans surfaced after the real Zellbury/Lama writes completed)

52. **"SHORT BLOCK HEEL" (Meme)** — a low-heeled shoe, "short" describing heel height —
    matched bare `SHORTS_RE` with 0 intervening words, same collision shape as "Short
    Coat"/"Short Dress" (#45). Added "heel(s)" to the same adjectival-exclusion list, and
    added "heel" to the footwear leaf check (`shoe|sandal|sneaker`) so it resolves to Shoes
    instead of falling through further. Also tightened that regex's word boundaries while
    touching it (`\b(shoe|sandal|sneaker|heels?)\b` — the old version had "sandal" with no
    boundaries at all and "shoe" with only a left one; verified no real title depends on the
    looser match).
53. **Unisex's Western/Upperwear tree had no "Dress" leaf** — `classify()` can emit
    `gender=Unisex` (the honest "no gender signal anywhere" fallback) independent of whether
    the garment is a dress. Real example: Lama's "PETERPAN DRESS" (vendor "LAMA", tags only
    a sale-collection label, nothing gendered anywhere) was stranding on the bare Western
    branch node. Added the leaf.

    Both found by the standard branch-level-orphan audit, re-run after the real (non-dry-run)
    Zellbury and Lama writes fully completed — confirms the audit as the right "did this
    new data add anything the classifier can't place yet" check for every future new-brand
    onboarding, not just Zellbury's Kurta/Kurta Set gaps (#47/#50). 1 product recategorized
    each; orphan count back to 0 across the full 113k-product catalog.

## Known open items (deliberately not fixed yet — flagging, not hiding)

- Multi-fabric-per-piece is only captured when a store's description is structured enough
  to regex-parse (confirmed working for Edenrobe). Other stores' unstitched multi-piece
  fabric breakdowns aren't extracted yet.
- Gender for kids' items relies on explicit "boys"/"girls" wording somewhere in
  vendor/tags/title/product_type — an item with only kids-range sizing (`kids_age_years`)
  and no textual gender signal still defaults to the store-level fallback, not Boys/Girls.
- This is a keyword/regex classifier, not a learned model — new brands or new phrasing
  conventions will keep surfacing cases like the ones above. The process for catching them
  is the branch-level-fallback sweep documented in `README.md`, not a claim of completeness.
  A full branch-level-orphan SQL audit (every product whose category sits on a branch node
  instead of a real leaf) is now the fast way to find a big batch of these at once — see the
  fourth pass above.

## 2026-08-28 (tenth pass — user-reported "BOYS DROP SHOULDER SPIDER" in Men)

54. **"Spider Man" (two words) collided with bare `\bman\b` in `GENDER_PATTERNS`.** With
    "men"/"man" checked before "boys"/"girls" in the pattern list, an incidental "Man" from a
    character name won gender resolution over a product's own explicit "Boys" signal. Real
    example: Breakout's "BOYS DROP SHOULDER SPIDER MAN PRINTED TEE" (vendor "KIDS" — not a
    `GENDER_PATTERNS` word itself, so it doesn't resolve at the vendor-only pass and falls
    through to the full blob) had "BOYS" explicitly in both tags and title, but "SPIDER MAN"
    matched `\bman\b` first and it landed in Men. One-word "Spiderman" never had this
    collision ("man" isn't a separate word in it) — confirms it's specifically the space that
    triggers it, e.g. also "Iron Man"/"Super Man" phrasing. Fixed by reordering `boys`/`girls`
    ahead of `men`/`man` — no equivalent collision exists for boys/girls, so this is a safe
    general fix, not a one-off exclusion for Spider-Man specifically. 8 products
    recategorized on backfill (the reported item plus similar real "[Hero] Man"-phrased boys'
    items elsewhere in the catalog); orphan audit confirmed 0 afterward.

## 2026-08-28 (eleventh pass — user-reported "Spiced Rage ... and other perfumes! saw a
slipper there too", plus an explicit ask for more extensive testing than one-off fixes)

The prior narrow fixes were correctly called out as not thorough enough — this pass audited
the ENTIRE Upperwear branch (every Shirt/T-Shirt/Polo/Jacket/Sweatshirt/Hoodie/Sweater/Top/
Dress product) for two whole classes of "obviously wrong branch" bug, not just the two
examples reported, then re-audited the whole catalog afterward for the same two bug classes
leaking anywhere else.

55. **`FRAGRANCE_RE` was singular-only.** 131 real perfumes — Outfitters' entire
    `product_type: "FRAGRANCES"` line ("Spiced Rage", user-reported, "Aqua Bloom", "Aqua
    Ember", body-mist products), ONE (Be-One)'s and Lama's `"Perfumes"`/`"PERFUMES"`
    product_type — never matched `\bfragrance\b`/`\bperfume\b` against the plural forms
    their own product_type used, and fell through to the generic Shirt/T-Shirt default (these
    titles are just scent names — "Spiced Rage", "AMALFI ORANGE" — with no fragrance word at
    all, so product_type was the ONLY signal available). Fixed: `\b(perfumes?|fragrances?|
    colognes?)\b`. Re-audited the full catalog afterward for any remaining fragrance word
    outside the Perfume leaf — 0.
56. **Footwear detection only ever recognized shoe/sandal/sneaker/heel.** 1,024 real products
    fell through to the generic Upperwear default with no footwear word in that narrow list to
    catch them — Diners/French Emporio's entire "Men Shoes"/"WOMEN SHOES" line (moccasins,
    3 real misspellings: "Mocassins"/"Moccasins"/"Moccassins"), Lama's "PUMPS"/"BOOTS"/
    "SLIDES"/"MULES"/"LOAFERS" product_type buckets, Outfitters' "OPEN SHOES"/"CLOSED
    SHOES", ONE (Be-One)'s "Slip-on"/real "Khussa" (a traditional South Asian sandal)
    listings, Furor's/Engine's real "Sneakers"/"Loafers" titles — this is what the
    user-reported slipper was part of. Broadened `FOOTWEAR_RE` to cover all of these.
    Additionally: "Sandals" is a real leaf `CATEGORY_TREE` only ever defined for Women (Men/
    Boys/Girls only had "Shoes") — real sandal-shaped words (sandal/slide/khussa/flip-flop/
    mule) now route Women specifically to that dedicated leaf instead of the generic Shoes one
    real Women's khussa/sandal/slide listings were resolving to before this pass (they were
    reaching Shoes correctly enough, just not the more specific leaf that already existed for
    them). Unisex's Western tree had no Footwear branch at all — 4 real gender-less footwear
    products (Lama's "LEATHER COWBOY BOOTS", "MADDIE MAMA LOAFERS", Zellbury's "Slides -
    5001") were stranding on the bare branch node; added the leaf. 1,787 products
    recategorized on reseed+backfill across both #55 and #56 combined.
57. **A store's `product_type` can be a merged/shared collection bucket naming more than one
    category at once** — Cougar's real `productType: "Men Joggers Shoes"` (5 products,
    "Mesh Lace-Up Trainers", "Suede Mesh Trainers", etc. — genuine sneakers, no jogger/
    sweatpant/track-pant word anywhere in their own titles) was resolving to Joggers because
    that check ran before the footwear one and the shared product_type contained both words.
    Found by re-auditing the WHOLE catalog (not just Upperwear) for the same two bug classes
    after #55/#56 landed — this is exactly the kind of thing a narrower, single-branch audit
    would have missed. Fixed with the same "title beats a shared/conflicting product_type
    bucket" reasoning already established for the Basic Barrel Jeans fix (#45d): only trust
    the product_type-level Joggers match if the title itself doesn't look like footwear
    instead. A genuine jogger whose own title happens to also say "Trainers" (Engine
    Clothing's "Men Trainers Jogger" — "trainers" used as a style qualifier there, not the
    shoe) is unaffected, since ITS title contains "Jogger" too. 5 products recategorized.

Final state after all three: 0 fragrance words outside the Perfume leaf, 0 footwear words
outside Shoes/Sandals, catalog-wide (checked directly, not sampled) — branch-level-orphan
audit confirmed 0 across the full 113,322-product catalog.

## 2026-08-28 (twelfth pass — user asked directly whether T-Shirts/Shirts/Jeans had actually
been checked across Men/Women/Boys/Girls, not just the two bug classes already found)

Ran the same audit technique explicitly against T-Shirt, Shirt, and Jeans — every gender each
leaf exists under (confirmed coverage first: Boys/Girls/Men/Unisex/Women all present in each).
T-Shirt came back clean. Shirt and Jeans did not:

58. **`ACCESSORY_RE`'s outer gate was singular-only for belt/cap/wallet/cufflink/bracelet/
    necklace/earring/clutch/watch** — even though some of these were ALREADY plural-safe in
    the leaf-picking regex one level down (`_KEYWORD_LEAVES`), the plural form never got past
    this outer gate to reach them. Real, large scale: 361 "Belts", 546 "Caps", 156 "Wallets",
    752 "Cufflinks", 86 "Bracelets", 40 "Necklaces", 230 "Earrings", 25 "Watches", 4
    "Clutches" — e.g. Cambridge/Diners/Furor's entire "Belts - CBT-4901"-style listings and
    "CUFFLINKS"/"Caps For Men" lines were landing in the generic Shirt default. Also folded
    "hat"/"beanie" into the Cap leaf (34 + 129 real products, no separate Hat leaf exists) and
    "bracelet"/"necklace"/"earring" into the Jewelry leaf (no separate leaves for those
    either). 1,127 products recategorized on backfill.
59. **A store's `product_type` can be wrong the other direction too** — ONE (Be-One)'s
    "String Sports Shoes" has `product_type: "Jeans"` (a genuine mislabel; tags say "Girls
    Footwear"/"KIDS_FOOTWEAR") and was resolving to Jeans because that check runs before the
    footwear one. Same "title beats a conflicting product_type" fix as Basic Barrel Jeans
    (#45d), this time protecting footwear instead of bottomwear.
60. **`GARMENT_DETAIL_RE` ("with...belt/tie" = a design detail on another garment, not a
    standalone accessory) was unconditional.** Equator's "Black With Brown Contrast Leather
    Belt" (tags explicitly "Accessories"/"BELT") is a genuine standalone belt describing its
    OWN two-tone color, not a garment with a belt detail — it has no garment noun anywhere in
    its title, unlike every genuine "with...belt" example ("Barrel Fit Jeans With Belt
    Detail", "Long Dress With Waist Belt", both name their garment). Stripping the phrase
    unconditionally left nothing for `ACCESSORY_RE` to match. Fixed: only strip when a real
    garment noun is also present in the same text.

Also spot-checked "Boot Cut Jeans"/"Boot Cut Denim" (a real fit descriptor, not footwear) and
"Cufflink Tie Set" combo listings (161 real products, correctly resolving to the primary item,
Tie) to confirm they were NOT false positives before concluding Jeans/Tie were clean — this
audit technique throws up real noise (a bare keyword match isn't proof of a bug) and each hit
was checked against real vendor/tags/product_type before being treated as a fix or dismissed.

Final state: Shirt, T-Shirt, and Jeans all confirmed clean across every gender via direct
query (not sampled); branch-level-orphan audit confirmed 0 across the full catalog.

## 2026-08-28 (thirteenth pass — user asked to try the same audit against EVERY category)

Extended the cross-leaf audit technique catalog-wide: for every leaf currently in use, checked
whether the products sitting in it also matched a STRONG signal word belonging to a different
leaf family (fragrance/footwear/underwear/eastern-wear/accessories/bottomwear/each specific
Upperwear leaf), reusing the actual compiled regexes from `classify()` rather than a separate
ad-hoc word list, so results stay consistent with the real classifier. This produced several
hundred raw hits — the overwhelming majority were false positives of the audit script itself
(it doesn't replicate `classify()`'s real priority order, e.g. "Kurta Trouser" correctly stays
Kurta because the Eastern-branch check runs before Bottomwear is ever considered, or "Boxer
Shorts" correctly stays Underwear because that check runs before Bottomwear). Every candidate
was re-verified directly against `classify()` itself before being treated as a bug — six were
real:

61. **`\btee\b` (the T-Shirt leaf trigger) was singular-only** — 906 real products (ONE
    Be-One's/Diners' entire `product_type: "Tees"` line, "Net Top Yellow", "Soccer Ball Print
    Tees") never matched and fell to the generic Shirt default.
62. **"Paper bag"/"paperbag" is a bottomwear FIT STYLE (a waist silhouette), not an actual
    bag** — 23 real products (Outfitters' "High-Waist Paper Bag Jeans", Meme's "PAPER BAG
    DENIM JEANS FOR GIRLS", Charcoal's "LINEN PAPERBAG PANTS") were resolving to the Bag
    accessory leaf, since that check runs before Bottomwear. Fixed with a lookbehind exclusion
    on the `bags?` pattern (both in `ACCESSORY_RE`'s outer gate and the `Bag` leaf-picker).
63. **"jorts" (an unambiguous portmanteau for jean shorts) wasn't recognized as a bottomwear
    word at all.** Real examples "Baggy Denim jorts"/"Denim Bermuda Jorts" have no literal
    "short(s)" word, and the bare "denim" they do have defaults to Jeans via the title-first
    bottomwear check (#45d) — never reaching a correct `product_type: "SHORTS"` fallback.
    Added `jorts?` to `SHORTS_RE` directly (no exclusion logic needed — it doesn't share the
    "short sleeve"/"short coat" collision shape). Deliberately did NOT add bare "bermuda" —
    it also names an unrelated real product line, "Blissful Bermuda Blue Drop Earrings".
64. **A footwear word immediately followed by an Upperwear garment noun is a themed PRINT,
    not an actual shoe** — real example, Cougar's "Flip Flops T-Shirt" (same naming pattern
    as "Spider Man Printed Tee"), was resolving to Shoes. Added the same kind of lookahead
    exclusion already used for `_SHORTS_ADJ_EXCLUDE`.
65. **Another product_type-mislabel case, this time Jeans-vs-Jacket** — ONE (Be-One)'s "Basic
    Denim Jacket" has `product_type: "Jeans"` and was resolving to Jeans for the identical
    reason as String Sports Shoes (#59). Added the same title-first guard, this time
    protecting Jacket.
66. **The final Upperwear leaf ternary checked a MERGED product_type+title blob against a
    fixed priority order** (T-Shirt checked before Sweatshirt, etc.), so a coarser
    product_type bucket could silently outrank the title's own, more specific word — real
    example, Outfitters' "Character Graphic Sweatshirt" has `product_type: "TEES"`, and "tee"
    won despite the title explicitly saying "Sweatshirt". This is the same root cause as #59/
    #65/#45d, just never generalized to the WHOLE final leaf-resolution step before now.
    Refactored into a small helper (`_upperwear_leaf_from`) and applied title-first/blob-
    fallback the same way as everywhere else — this one fix's backfill (117 products) also
    silently absorbed other title-vs-product_type Upperwear conflicts beyond the two examples
    that surfaced it, which the previous six more narrowly-scoped fixes did not.

245/245 tests pass. Combined backfill impact across #61-#66: several hundred products
recategorized; branch-level-orphan audit confirmed 0 across the full 113,322-product catalog
afterward. This is now the sixth distinct real instance this session of the same underlying
class of bug (a store's `product_type` bucket conflicting with what its own title says) —
#45d, #57, #59, #65, and #66 are all the same root cause applied to a different leaf pair each
time; worth remembering as a standing category of risk for any future store onboarding, not
just something to re-discover per-brand.

## 2026-08-29 (fourteenth pass — four parallel category audits, prompted by real tank tops/
## pocket squares/vests found in the live Men's Shirt listing while browsing outside AI search)

The user found real non-shirts (tank tops, a pocket square, activewear vests) sitting in the
live Men's Shirt category by browsing the site directly, and asked for a systematic audit of
every category rather than another one-off fix. Ran four parallel audits (Western Upperwear;
Bottomwear/Footwear/Suits; Eastern; Accessories/Fragrance), each checking every leaf currently
in use against every OTHER leaf family's own real regex, verifying every candidate directly
against `classify()` before treating it as a bug. Confirmed: **"Shirt" has been acting as the
Western branch's silent catch-all** — any garment type `classify()` has no keyword for lands
there by default, and this was the root cause behind nearly everything found.

67. **Pocket Square had no leaf or keyword at all** — 305 real products (Uniworth "100% Silk
    Pocket Square", Cambridge/Equator formal accessories) were falling to Shirt. Added a
    `Pocket Square` leaf (Accessories, all genders) and a keyword check.
68. **Tank Top had no leaf or keyword at all** — 458 real products across Men/Women/Boys/Girls
    (Furor's own product_type is literally "Men Tank Tops" and still resolved to Shirt) were
    falling to Shirt/T-Shirt. Added a `Tank Top` leaf (Upperwear, all genders) and a keyword
    check, broadened from "tank top(s)" to bare "tank(s)" after backfill verification found
    real tank tops titled without the word "top" at all (Equator's "Color Block Tank",
    Breakout's "CARDIO TANK", Monark's "Textured Tank-Shirt", Meme's "TANK T-SHIRT FOR
    WOMEN") — every real "tank" hit checked catalog-wide is a genuine tank top, no collision
    found. Deliberately excludes "sando" — this catalog's own real word for a men's
    UNDERGARMENT tank, a different real garment, already handled by the existing
    `VEST_UNDERWEAR_SIGNAL_RE` logic (bare "sando" with no "vest" word is a separate,
    pre-existing gap — still falls to Shirt, out of scope for this pass, not newly broken).
69. **Scarf/Muffler/Stole had no leaf or keyword at all** — 1,013 real products (mostly
    Men/Women; Uniworth "Aqua Wool Scarf"/"Men Muffler") were falling to Shirt. Worse, a
    standalone Dupatta/Duppatta was falling even further wrong, into **Shalwar Kameez** — the
    Eastern branch's own silent final-else fallback — since "dupatta" is itself one of
    `EASTERN_RE`'s trigger words (needed so a real "Shirt Trouser Dupatta" 3-piece unstitched
    set still counts it as a named piece). Added a `Scarf` leaf (Accessories, all genders)
    and a dedicated early check (`SCARF_RE`, gated on no OTHER real Eastern garment word being
    present) checked ahead of the Eastern-branch entry.
70. **Outerwear vests had nowhere to land once ruled out as underwear** — ~60 real products
    (Engine Clothing's "Active Wear Vest", Cambridge's "Quilted Vest"/"Sherpa Vest") were
    falling to Shirt. Folded bare "vest(s)" into the existing Jacket leaf, checked last among
    the specific garment words so a real "Sweater Vest" still resolves Sweater first.
71. **Diners' bare piece-count ("2PC"/"3PC") and "combo" naming for a coordinated Western
    set, with no "suit"/"co-ord" word at all** — real body_html confirms these are genuine
    "ready-to-wear 2-piece set"/"Top Bottom Set" listings, not Eastern ensembles (EASTERN_RE/
    UNSTITCHED_RE have both already failed to match by this point in the function) — ~1,015
    real products across Women/Girls/Boys/Teens/Infant sub-lines were falling to Shirt.
    Broadened the existing Suits & Sets check to also match a bare `[1-4] pc`/`piece(s)`
    marker and "combo", with two guards found necessary by checking every catalog-wide hit
    before enabling this broadly: the piece-count marker requires the literal "pc"/"piece(s)"
    suffix, NOT a bare trailing "p" — Edenrobe's "Varsity Jacket - EBTJP5-001-2P" is a SKU
    suffix, not a piece count, and would otherwise have been wrongly pulled out of Jacket;
    "combo" excludes an immediately-following Upperwear garment noun — Equator's "Green &
    Black Combo Hoodie"/"Tri-Color Combo Tee" use "combo" to describe a COLOR combination,
    not a multi-piece set, and must keep resolving to their own garment leaf. One narrow
    residual left unfixed (1 real product, "Batman Graphic Boys Sweatshirt Trouser," product_
    type "Boys Combo"): its title itself contains "Trouser," so the earlier, well-established
    title-first bottomwear check wins before this combo check is ever reached — not worth
    reordering that priority chain for a single product.
72. **Edenrobe's stitched "Shirt Trouser" 2-piece sets had no Eastern word anywhere in the
    title** — 399 real products (product_type "Woman Pret Embroidered"/"Girls Eastern") were
    falling to plain Western Trouser. Real body_html confirms these are a stitched Kurti+
    Trouser ensemble ("Girls' Pret Kurti & Trouser"). The UNSTITCHED version of the same title
    pattern (670 real products) already resolved correctly, independently, via
    `UNSTITCHED_RE` matching "Un Stitched" in that version's own product_type. Added
    `SHIRT_TROUSER_SET_RE` as an Eastern-branch entry trigger (verified exclusive to
    Edenrobe, 1,069 total real matches, before enabling) resolving to `Kurta Set`.
73. **Zellbury's "Top" leaf existed in `CATEGORY_TREE` for Women/Girls but no rule had ever
    emitted it — dead code.** 538 real Women's "Tunic" products (Zellbury's own naming) were
    falling to Shirt instead. Added a gender-gated "tunic" -> "Top" check (only for
    Women/Girls, the only genders this leaf is defined for).
74. **Zellbury's "Chino" line had no keyword at all** — 84 real products ("Signature Chino")
    were falling to Shirt. Added "chino(s)" to `TROUSER_RE` — every real hit checked
    catalog-wide (1,200+ products across Edenrobe/Furor/Zellbury) unambiguously names a
    trouser.
75. **A mislabeled product_type outranked an unambiguous title, again** — Outfitters'
    "Multi-Functional Backpack"/"Faux Leather Backpack" (product_type literally "WALLETS")
    and Breakout's "CROCHET CLUTCH" (product_type "WALLET") had no keyword of their own, so
    the title-first check found nothing and fell back to the mislabeled product_type's
    "wallet(s)" match instead — same conflict class as String Sports Shoes (#59) and Basic
    Denim Jacket (#65). Folded "backpack(s)"/"clutch(es)" into the existing Bag leaf trigger
    (both the outer `ACCESSORY_RE` gate and the inner leaf-picker).

277/277 tests pass (32 new). Backfill: 4,335 products recategorized across two runs (4,290
initial + 45 from broadening the Tank Top regex after backfill verification surfaced the bare
"tank" cases). New leaves added: Tank Top (458 products), Scarf (1,013), Pocket Square (305),
and Top (541 — previously dead code, now finally reachable). Two items flagged during the
audits but deliberately left as-is, not bugs: a "Waistcoat Suit" line (236 products, Boys/Men)
that does contain a real waistcoat and has no cleaner leaf to move to; an orphaned "Kurta
Shalwar" tree node (0 products — everything consistently consolidates into "Kurta Set"
instead, the correct behavior, just leaving that one specific node unused).
