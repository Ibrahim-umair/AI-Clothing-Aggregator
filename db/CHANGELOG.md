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

## 2026-08-30 (fifteenth pass — user reported AI search mixing genuine cargo trousers with
## plain trousers, traced to "cargo" being ranking-only signal rather than a real category)

76. **"Cargo" had no leaf of its own** — it was splitting across Trouser/Jeans/Shirt depending
    on incidental wording, and since none of that was a hard filter, real trousers with a
    totally different silhouette ranked alongside genuine cargo pants in AI search. Root cause
    of the split: "Denim Cargo Trouser" (product_type "Boys Trousers", title explicitly says
    "Trouser") was landing in **Jeans** because bare "denim" outranked the title's own more
    specific word; bare "cargo" alone with no other bottomwear word ("TWILL CARGO", "Men Cargo
    Touser" — a real title typo) had nothing to catch it at all and fell to the generic Shirt
    default. Added a new `Cargo Trouser` leaf (Bottomwear, all 5 genders) and `CARGO_RE`,
    checked ahead of the Jeans/Trouser split but after Shorts/Joggers — "Cargo Shorts"/"Cargo
    Joggers" are real, already-correctly-named garments and were deliberately left alone; only
    the Trouser/Jeans ambiguity needed resolving. 443 real products consolidated across
    Men/Women/Boys/Girls/Unisex; 449 total category_id changes after backfill (a few extra
    Shirt-default catches like the two examples above). Also added `Cargo Trouser` to the AI
    search's `KNOWN_CATEGORIES` (server/search_tool.py) so it's now a real hard SQL filter
    there too, not just a `semantic_query` ranking hint — verified: "cargo trousers under 3000"
    went from mixing in Chinos/training trousers past rank 8 to 32 hard-filtered results, every
    one genuinely a cargo trouser.

289/289 tests pass (13 new). Full 101-query AI-search parity suite still 97.1%, 0 errors, same
two known kids-gender-gap failures — no regression from either change.

## 2026-08-30 (sixteenth pass — user audit of the Western "Co-ord Set" leaf, per-brand: real
## Eastern ensembles mislabeled as Western suits, a regex precedence bug, and a stray
## product_type overriding the title)

77. **A regex alternation precedence bug let bare "suit" match as a suffix inside ANY word.**
    `r"\bco-?ord|suit\b"` parses as `(\bco-?ord)|(suit\b)` — the right-hand alternative has NO
    leading `\b`, so "suit" matched inside jumpsuit/playsuit/bodysuit too. 152 real one-piece
    garments (Girls 97-ish, Women, Boys — jumpsuit/playsuit/bodysuit) were landing in Co-ord
    Set. Fixed to bound both sides (`\bsuits?\b`), added a new `Jumpsuit` leaf (Upperwear,
    Women/Girls/Boys) with its own positive route, and explicitly allow-listed
    tracksuit/pantsuit/nightsuit back in (verified catalog-wide as the complete real
    compound-word list of genuine 2-piece sets; "pantsuit" has zero real matches but is kept
    defensively).
78. **Cougar's own `productType: "2PC"` bucket forced single tops into Co-ord Set** — 93 real
    products (e.g. a plain top, product_type literally "Girl 2PC Top"/"Women Top 2PC") had no
    "2PC"/"co-ord"/"suit" word in the *title* at all, only in product_type. The piece-count
    sub-check is now restricted to the title only (co-ord/suit/tracksuit/pantsuit/nightsuit/
    combo stay checked against the full blob) — same "title beats a conflicting product_type"
    precedent as String Sports Shoes/Basic Denim Jacket elsewhere in this file. ~88 of the 93
    now resolve correctly as Shirt/Jacket; the other 5 happen to also say "kurti"/"kurta" in
    their own title and were unaffected either way.
79. **classify() never read tags or description at all — its only signal was
    `product_type + title`.** This meant several brands' real Eastern ensembles, sold under a
    Western-sounding "Suit"/"Co-Ord Set" title, had no way to be caught: Cambridge's tags
    literally say `"Designer Shalwar Kameez", "Mashriq"` for items titled just "EMBROIDERED
    SUIT"/"Cream Dobby Texture Suit"; Equator's description says "This two-piece suit from our
    Qaftaan collection...includes a kurta..." for an item titled "French Grey Suit"; Zellbury's
    "Wash & Wear Suit" description says "Men Unstitched Shalwar Kameez Fabric" with no Eastern
    word anywhere in title/product_type (so it was resolving Stitched/Western instead of the
    correct Eastern/Unstitched); Edenrobe's/Cambridge's/Diners' real "Co-Ord Set"-titled items
    use their own structured description convention, each piece labeled "Fit Type: ... Fabric:
    ... Style: ..." (e.g. "Shirt Fit Type: Straight Fit Fabric: Organza Style:...Trouser Fit
    Type:..."), with no kurta/kameez/shalwar word in the title itself; a "Frock" variant of the
    same convention exists for girls'-wear. Added a scoped override, checked ONLY for items
    that already look like a coordinated Western set (i.e. only inside the Co-ord Set check
    itself, never widening any other category's classification): a broadened tags+description
    signal (extended `EASTERN_TAGS_DESC_RE`, `UNSTITCHED_RE`, and the new "Fit Type:"-labeled
    shirt/frock+trouser/shalwar heuristic) can downgrade a would-be Co-ord Set match to its real
    Eastern branch/sub/leaf.
    - Two real false positives were caught and excluded *before* shipping this, both found by
      verifying the override against every current Co-ord Set product, not just the reported
      brands: (a) "waistcoat" is excluded from the tags/description signal specifically —
      Equator's own genuine Western 3-piece business suits ("single-breasted jacket, notch
      lapels...finished with a shawl lapel waistcoat...") use that exact word too, so it stays
      trusted only in title/product_type, same as before; (b) the shirt/trouser heuristic
      requires the labeled "Fit Type:" convention specifically, not just two loose mentions of
      "fabric" — a looser version false-matched Furor's own Western "Resort Co-Ord Set Shirt"
      line, whose flowing prose ("Crafted from Soft, Breathable Crochet Fabric...Best Worn with
      Its Matching Trousers...") mentions both words without using this brand's labeled
      convention at all.
    - Also added `sharara|gharara|lehenga|kalidar|pishwas` to `EASTERN_RE` itself (verified
      catalog-wide zero-risk: 81 real matches, all in Co-ord Set/Shirt/Kurta, none elsewhere) —
      resolving to the new shared `_eastern_stitched_leaf` helper's "Kurta Set" default, since
      these styles are distinct from a plain Shalwar Kameez.
    - Real per-brand scale (verified against live Co-ord Set data before shipping): Edenrobe
      1,135, Cambridge 224, Diners 174, Zellbury 24, Cougar 16, Equator 13 — 1,586 total. No
      other brand's Co-ord Set products matched this override at all (Charcoal/Royal Tag stayed
      at 1–2 stray items each; Furor/Monark/Engine Clothing/Outfitters/Meme/ONE (Be-One)/Lama/
      Breakout/Uniworth had zero — their Co-ord Set items really are Western).
80. **Edenrobe's/Diners' "Prince Suit"/"Prince Coat" is a short embroidered Eastern formal coat
    (Sherwani-adjacent), not a Western jacket** — but only when it already carries a coordinated
    Western-set signal (e.g. "Grey Boys Prince Suit", 45 real products across Edenrobe/Diners).
    Added `PRINCE_SET_RE` as another trigger for the same scoped override above, resolving to
    Sherwani. A standalone "Prince Coat" with no set signal at all (52 real products, currently
    Jacket) is a separate, out-of-scope question this audit didn't cover — deliberately left
    untouched.
    - Refactored the duplicated sherwani/waistcoat/kurti/kurta/Kurta-Set leaf-naming chain (used
      both by the main Eastern-branch entry point and this new override) into one shared
      `_eastern_stitched_leaf` helper, so both places agree on what a given set of Eastern words
      resolves to — not a behavior change at the main entry point, just removing duplication
      before adding the second call site.
    - Explicitly NOT fixed, flagged as brand-specific naming ambiguity too narrow for a general
      rule: Zellbury's 9 "Co-Ord Set Shirt" products, 7 of which are genuinely standalone shirts
      ("Matching separate available" in the description — i.e. NOT actually bundled) and only 2
      of which are real Gharara Suits (already caught by the sharara/gharara/etc. fix above).
    - Also flagged, deliberately NOT fixed in this pass (a different bug, out of scope for a
      Co-ord Set audit): ~15+ Meme "PJ SET"/"PYJAMA SET" products currently resolving to Shirt.

313/313 tests pass (24 new). Backfill: 2,018 products recategorized. Net Co-ord Set count:
5,826 -> 4,077 (net -1,749: 152 to the new Jumpsuit leaf, ~88 Cougar 2PC-in-product_type items
to Shirt/Jacket, 1,586 to their real Eastern branch/leaf via the tags/description override, a
handful of others from the Cargo-Trouser-era regex cleanup along the way). New `Jumpsuit` leaf
added to `CATEGORY_TREE` (Women/Girls/Boys) and to the AI search's `KNOWN_CATEGORIES`
(server/search_tool.py).

81. **"Co-ord Set" was hosting two genuinely different product types** — the user pointed out
    that a "co-ord set" is normally a casual matching-separates set (loungewear/resort/
    office-casual), not a tailored Western business suit, and the Co-ord Set audit above had
    left real formal suits and tracksuits inside it. Verified against real data before
    splitting: a strict tailoring-language signal (blazer/lapel/breasted/bespoke/tuxedo/
    waistcoat — checked against product_type+title+tags+description, gated to Men/Boys only)
    found 317 real Western business/formal suits across 8 brands (Equator 64, Edenrobe 55,
    Monark 51, Cambridge 41, Diners 42, Uniworth 35, Charcoal 26, Royal Tag 3). A literal
    "tracksuit" match found 36 more (Furor 23, Equator 5, Meme 5, Charcoal 2, Edenrobe 1).
    Explicitly did NOT move a handful of Women's "Suit"/"Blazer Co-ord Set" titles that use the
    identical tailoring words (Engine Clothing, Meme) — their own real descriptions confirm
    they're genuinely casual separates ("...perfect for casual outings, travel, everyday
    wear"), not formalwear — so the new Formal Suit signal is deliberately gated to Men/Boys
    only, verified against these exact false positives before shipping.
    - Added two new leaves under Western > Suits & Sets: `Formal Suit` (Men, Boys) and
      `Tracksuit` (Men, Women, Girls) — both added to `CATEGORY_TREE` and to the AI search's
      `KNOWN_CATEGORIES`/system prompt (server/search_tool.py), with a new rule + two worked
      examples so query extraction doesn't conflate "Formal Suit" with either "Co-ord Set" or
      the unrelated Eastern Unstitched "Suit" leaf.
    - `TRACKSUIT_RE`/`JUMPSUIT_RE` are both checked ahead of the Suits & Sets block outright
      (unambiguous words, no gating needed); `FORMAL_SUIT_RE` is checked only after the
      Eastern-override check already failed, and only for Men/Boys.

322/322 tests pass (9 new). Backfill: 353 products recategorized (317 to Formal Suit, 36 to
Tracksuit). Idempotency reverified: a second backfill run changed 0 rows.

## 2026-08-30 (seventeenth pass — user follow-up: Furor's "Tracksuit" line names individual
## pieces, not sets; and Formal Suit deserves its own nav group, not a spot inside Suits & Sets)

82. **Furor's own real "Tracksuit" collection name doesn't mean the product is a 2-piece
    set** — 19 real products (e.g. "Quarter-Zip Tracksuit Sweatshirt", product_type "Men
    Sweatshirts"; "Mock Neck Tracksuit Zipper Jacket", product_type "Men Jackets"; "Tracksuit
    Pullover Hoodie"/"Tracksuit Zipper Hoodie", product_type "Men Hoodies") are single garments
    from a tracksuit-themed line, not an actual 2-piece set. The tell, verified against every
    real Tracksuit-category product before shipping: a genuine 2-piece set (Furor's own "Hoodie
    Tracksuit"/"Zipper Jacket Tracksuit", product_type "Woman Track Suit"; Equator/Charcoal/
    Meme's bare "___ Tracksuit"/"Tracksuit Set" titles) never has another garment noun
    immediately AFTER the word "tracksuit" — only before it, or not at all. Added
    `TRACKSUIT_SINGLE_GARMENT_RE` to detect the single-piece pattern (tracksuit followed shortly
    by jacket/hoodie/sweatshirt/sweater/polo/t-shirt/tank top); when it matches, the Tracksuit
    route is skipped and the item falls through to the normal Jacket/Hoodie/Sweatshirt
    resolution instead. Also removed "tracksuit" from the general co-ord/suit candidate regex
    (it now has its own fully-handled earlier check) — leaving it there was silently re-catching
    the excluded single-garment titles and resolving them to the generic Co-ord Set default
    instead of letting them fall through.
83. **"Formal Suit" split out of "Suits & Sets" into its own sub-branch, "Formalwear"** — at the
    user's request: a tailored Western business suit isn't a "set" in the same sense as a
    Co-ord Set/Tracksuit and shouldn't share that nav grouping. `CATEGORY_TREE` now has a
    sibling `Formalwear` sub-branch (Men, Boys) holding just the `Formal Suit` leaf;
    `classify()`'s Formal Suit return now emits `sub="Formalwear"`. `Suits & Sets` keeps
    `Co-ord Set`/`Tracksuit`. Added `Formalwear` to `WESTERN_SUB_ORDER`
    (server/taxonomy_tree.py) so it renders as its own mega-menu column group (right after
    Suits & Sets), and to the AI search's `KNOWN_CATEGORIES` (server/search_tool.py) as a
    grouping name. No frontend code changes were needed — Header.jsx's mega-menu and Shop.jsx's
    filters are both driven entirely by `/api/taxonomy`, which reads the live `categories`
    table, so the new group appears automatically once the table reflects the split.
    - The pre-existing `Formal Suit` rows (created under the old `Suits & Sets` parent by the
      previous pass's reseed) were left behind as empty, unreferenced duplicates once backfill
      re-pointed every product to the new `Formalwear`-parented rows — verified zero products
      referenced them, then deleted directly (`reseed_categories.py`'s `ON CONFLICT
      (parent_id, slug)` creates a new row under a new parent rather than moving the old one,
      so a parent change needs this one-time manual cleanup; adding a leaf under an unchanged
      parent, the normal case, never does).

327/327 tests pass (5 new). Backfill: 336 products recategorized (317 Formal Suit re-parented
to Formalwear, 19 Furor single-garment items moved out of Tracksuit to their real
Jacket/Hoodie/Sweatshirt leaf). 2 orphaned empty `Formal Suit` category rows deleted. Idempotency
reverified: a second backfill run changed 0 rows.

## 2026-08-30 (eighteenth pass — user report: Outfitters' "Faux Leather Cropped Waistcoat"
## resolves Eastern Waistcoat, but it's a Western fashion vest)

84. **A bare "waistcoat" is one of `EASTERN_RE`'s own trigger words, with no exception for a
    Western fashion vest sold under the same word.** Real example: Outfitters' "Faux Leather
    Cropped Waistcoat" (product_type "OUTERWEAR", tags "Jackets"/"Outerwear"/"vest") was
    resolving to Eastern > Stitched > Waistcoat — clearly wrong, it's PU/faux-leather outerwear,
    not a traditional koti. Verified catalog-wide against every current Waistcoat-leaf product
    (1,730) before shipping: a real Western signal (`western`/`outerwear`/`faux leather`/
    `pinstripe`/`denim`/`leather`/`blazer`, checked against product_type+title+tags+description)
    found 21 real products across 5 brands (Uniworth 11 — the brand's own "Western Waistcoat"
    line; Charcoal 4 — denim waistcoats; Lama 4 — "BLAZERS" product_type; Edenrobe 1; Outfitters
    1). A real false positive was caught and excluded before shipping: Edenrobe's "Cotton
    Waistcoat Suit" mentions "Blazer Suiting Fabric"/"Contrast Blazer Collar" as a STYLE DETAIL
    on what its own description confirms is a "Cotton Satin Kurta Pajama" — genuinely Eastern
    despite the word "blazer". The Western signal only wins when no Eastern companion word
    (kurta/kurti/shalwar/kameez/koti/Mashriq) is also present in the same signal — this
    correctly left 18 real Diners/Edenrobe products (Boys Kameez Shalwar + Waistcoat combos, a
    genuine koti) untouched as Eastern. Folds into the existing Western `Jacket` leaf (same as
    "blazer"/bare "coat" elsewhere in this file) — no separate Western Vest leaf exists.

333/333 tests pass (6 new). Backfill: 21 products recategorized (Uniworth 11, Charcoal 4, Lama 4,
Edenrobe 1, Outfitters 1) to Western > Upperwear > Jacket. Idempotency reverified: a second
backfill run changed 0 rows.

## 2026-08-31 (nineteenth pass — onboarding a new brand, Bandana.pk, per the user's explicit
## instruction to read real product descriptions across every category BEFORE writing any
## classify() rule, to catch brand-naming ambiguity and non-Shariah-compliant items up front)

85. **Pre-load audit, not a blind scrape.** Before adding Bandana (an activewear/basics/
    loungewear brand, 201 real Shopify collections, no Eastern wear at all), read 2-5 real
    products with full descriptions across every women's/men's/kids' collection. Found several
    real gaps this surfaced — all fixed BEFORE the brand's first real load, and all verified to
    also retroactively fix real EXISTING products across the other 15 brands (this file's
    vocabulary isn't brand-scoped):
    - **"bra"/"camisole" had no keyword anywhere** — 40 real EXISTING products ("White Glide-Fit
      Sports Bra", "BRA TANK TOP", "Jogger Bra") were scattered across Shirt/Tank Top/T-Shirt/
      Co-ord Set/Joggers instead of Underwear. Added to `UNDERWEAR_RE` (word-boundary anchored,
      verified it doesn't match inside "bralette"/"Cobra"/"Zebra").
    - **"gilet"/"bodywarmer" had no mapping** — 67 real EXISTING products (Furor's "Puffer
      Gilet", "Yellow Down Gilet") had no jacket/vest/coat word and were falling to Shirt/
      Hoodie. Folded into the existing Jacket leaf, same as bare "vest".
    - **"Skirt" never had a leaf or keyword** — 95 real EXISTING products ("WILDFLOWER TIER
      SKIRT", "Denim Skirt With Front Slit") were scattered across Shirt (67)/Jeans (10)/
      Shorts (10)/Co-ord Set (5)/Trouser (3). New `Skirt` leaf added (Women, Girls), checked
      ahead of the Trouser/Jeans/Shorts split so a "Denim Skirt" isn't pulled into Jeans.
    - **"cardigan"/"turtleneck" had no mapping** — 47 real EXISTING cardigans were falling to
      Shirt; turtleneck only resolved correctly by coincidence elsewhere in the catalog and
      would have failed for a brand (like Bandana) whose product_type is a generic bucket
      ("Tops"/"Bottoms"/"Sets") with no useful fallback signal. Both fold into Sweater.
    - **Bandana's "Denim Terry" fabric-line name** ("Men's Denim Terry Pants") means terry cloth
      with a denim-look print, NOT real denim — its own description says so explicitly. Would
      have wrongly resolved Jeans off the bare word "denim". Excluded the adjacent phrase
      "denim terry"/"terry denim" from the bare-denim fallback (both title and full-blob
      variants).
    - **Bandana's "RUH" capsule line is genuinely unisex** — verified the exact same product ID
      appears in both the `ruh-men` and `ruh-women` collections, tagged "RUH Men" AND "RUH
      Women" simultaneously, description literally saying "UNISEX". `guess_gender()`'s own
      priority order (women checked ahead of men/unisex, for a different, deliberate reason)
      would otherwise silently resolve these to Women. Added a narrowly-scoped override in
      `classify()`: only fires when a real "men" AND a real "women" word are BOTH present on
      the same product AND its own description explicitly says "unisex" — never touches a
      product that only ever names one gender.
    - Confirmed safe / no action needed: sub-brand and fabric-line names (B-Fit, CoreFlex,
      Luxelight, LuxeStretch, Luxury Spacer, Pima Cotton, Modal) are consistently pure style
      modifiers in front of a real garment word in every sample read — never disguising a
      different garment type.
86. **Shariah/modesty hide criteria (`hide_categories.py`) tightened** — real gaps found reading
    Bandana's actual descriptions, extended to the whole catalog (this tool's WHERE clause is
    gender+category+text based, never brand-scoped):
    - "Spaghetti strap" added as its own trigger alongside "sleeveless" — a real Bandana product
      ("Modal Rib Lace Tank") says "spaghetti straps" but never the word "sleeveless" itself.
    - The crop-top check was TITLE-ONLY; extended to also scan description/raw_source — 5 real
      Bandana products ("Women's Brushed Spacer Hoodie", "Women's Rib Relaxed Fit Turtleneck")
      say "cropped length" only in the description, never the title.
    - Added a carve-out excluding vest/gilet/bodywarmer titles from the sleeveless trigger — a
      real Bandana "Goose Down Reversible Gilet" says "sleeveless design" in its own
      description, but a gilet is BY DEFINITION a sleeveless outerwear layer worn over other
      clothing, not an exposed-skin modesty concern; the blanket rule would otherwise hide an
      entire legitimate outerwear category.
    - Re-running this tool against the pre-existing 15-brand catalog (before Bandana was even
      loaded) with just these 3 changes hid 279 more real products that the previous, narrower
      version had missed.

349/349 tests pass (16 new). Retroactive backfill against the existing catalog: 278 products
recategorized (bra/gilet/skirt keywords) + 69 more (cardigan/turtleneck) = 347 total, all
verified idempotent. Bandana loaded: 1,049 products, 14,882 variants. Bandana Shariah-hidden:
112 of 526 Women's products (21%) — Boys/Girls/Men/Unisex untouched (112 = 25 wholesale-hidden
Tank Top + 12 wholesale-hidden Tights/leggings + 8 wholesale-hidden Shorts + 7 wholesale-hidden
Underwear/bras + 60 sleeveless/spaghetti-strap/cropped-description matches across Shirt/
T-Shirt/Sweater/Sweatshirt/Hoodie/Dress/Top/Polo).

## 2026-09-01 (twentieth pass — user-reported "saw some women clothing within men", plus a
full audit of Bandana/Lama, the two most-recently-onboarded brands)

87. **A gender word anywhere in the merged tags/title/product_type blob could still override
    an unambiguous title, even after the vendor-priority fix (#27/#34).** Real, high-volume
    example: Bandana tags EVERY "B-Fit" activewear product — men's and women's alike — with a
    shared cross-collection tag literally named `"B-Fit Men Women"`. `vendor` for this line is
    just `"B-Fit"` (no gender word, so the vendor-only check doesn't resolve anything), so this
    fell through to the merged blob, where `\bwomen\b` matched the tag and won outright over
    `\bmen\b` (per `GENDER_PATTERNS`' own deliberate women-before-men ordering — see #1) —
    silently overriding a title that says "Men's B-Fit CoolMax Joggers" in plain English.
    Fixed with a new tier, `TITLE_GENDER_PREFIX_PATTERNS`, checked after vendor but before the
    noisy merged blob: an explicit "Men's"/"Women's"/"Boys'"/"Girls'" at the very START of the
    title is as deliberate and reliable a signal as vendor, anchored so it can't collide with
    an incidental mid-title word the way an unanchored check would (same class of risk as the
    "Spider Man" fix, #54). *53 of 56 real "Men's B-Fit..." products were filed under Women for
    exactly this reason before the fix.*
88. **"Tote(s)" had no keyword or leaf of its own at all** — real Bandana/Lama examples
    ("Women Tote", "Journey Tote", "SUNDAY MARKET TOTE", "GOZO TRAVELER TOTE") had no other
    accessory keyword and fell all the way through to the generic Western→Upperwear→Shirt
    default. Folded into the existing Bag leaf/pattern.
89. **"Cap Sleeve" (a sleeve style — covers just the shoulder) collided with the literal Cap
    headwear keyword.** Real examples: Bandana's "Women's Raglan Cap Sleeve Tee", "Boys'
    Graphic Cap Sleeve Tee". Excluded `caps?(?!\s*sleeves?)`, same class of fix as #10's
    "shawl collar" exclusion.
90. **"Sock-fit" (a real sneaker-construction term — a knit upper built like a sock) collided
    with the literal Socks keyword.** Real example: Lama's "SOCK-FIT CASUAL SNEAKERS" (Rs.
    8,970 — shoe-tier pricing, confirmed against the other 114 genuine Socks products, all
    under Rs. 1,950) was landing on Accessories→Socks instead of Western→Footwear→Shoes.
    Excluded `socks?(?!-fit\b)`.
91. **`GARMENT_DETAIL_RE` ("with...belt/tie" = a design detail on another garment, #60) didn't
    cover "scarf."** Real example: Lama's "CITY DRESS WITH SCARF DETAIL" was landing on
    Accessories→Scarf instead of Dress. Also fixed a second bug in the same area: the
    stand-alone `SCARF_RE` check right after the accessory block was reading the raw
    (unstripped) blob instead of the with-detail-stripped one, so the stripping added for the
    ACCESSORY_RE check above it never actually reached this check.
92. **`GARMENT_NOUN_RE` (the "is there a real garment named here" guard used by the
    with-detail stripping above) only recognized "trousers", not the equally common "pants"
    spelling.** Real example: Lama's "TAPERED COTTON PANTS WITH BELT" was landing on
    Accessories→Belt instead of Trouser for exactly this reason.

360/360 tests pass (10 new). Retroactive backfill against the existing 117,657-product catalog:
100 products recategorized (mostly #87's B-Fit gender fix) + 4 more (#91/#92's scarf/pants
fixes) = 104 total. Re-auditing the full Bandana+Lama catalog (3,879 products, not a sample)
after the backfill: 0 gender mismatches remaining (was 59), category mismatches down from 70
to 48 in the first pass, then to a residue of lower-confidence/ambiguous cases after #88-92
(cargo-pocket-shirt-vs-trouser, tank/turtleneck-vs-dress, and a couple of jacket/hoodie edge
cases were found but NOT fixed here — smaller in volume, higher regression risk to a
heavily-tuned function, reported to the user for a decision rather than rushed in).

## 2026-09-01 (twenty-first pass — two more user reports: "2 pieces were containing 3 pieces",
"women jackets were containing vests")

93. **The piece-count regex required the digit and "p" adjacent — an optional HYPHEN, never a
    literal SPACE — and only ever checked `title+product_type`, never `description`.** Real,
    high-volume bug: 1,796 Zellbury Women's Unstitched products titled "Shirt Shalwar Dupatta"
    (a genuine 3-piece ensemble) whose OWN description says "Buy 3 Piece Printed Lawn Shirt
    Shalwar Dupatta..." / "This elegant 3-piece set..." never matched on either count — the
    space between "3" and "Piece", or the fact it's only ever stated in the description — and
    fell through to the named-piece-counting fallback instead, which (#94, below) undercounted
    them anyway. Widened the regex to `[\s-]?` and added a `description`-inclusive blob for
    this specific check (same class of extension as #79's tags+description override).
94. **The named-piece-counting fallback ("Shirt Trouser Dupatta" → count the named pieces) only
    recognized "shirt"/"trouser"/"dupatta"/"shawl" — not "shalwar," the single most common
    Eastern bottom-piece word, more common in this catalog than "trouser."** Same 1,796 Zellbury
    products: "Shirt Shalwar Dupatta" only counted 2 (shirt, dupatta), landing on "2-Piece"
    instead of "3-Piece," even before the #93 fix above. Added "shalwar" to the keyword list.
95. **No separate "Vest" leaf existed anywhere in `CATEGORY_TREE`** — a sleeveless outer layer
    (vest/gilet/bodywarmer, or a Western "waistcoat" — the identical garment, just a different
    regional word) was folding into the Jacket leaf by default, alongside actual sleeved
    jackets/blazers/coats. User-reported: browsing Women's Jackets turned up real vests. Read
    every one of the 156 real vest/gilet/bodywarmer/Western-waistcoat products already sitting
    in Jacket, across every gender, before making this change — none showed any real Eastern
    signal (no shalwar/kameez/kurta/koti wording anywhere in any of them), so this is purely a
    Western sub-category split, not an Eastern branch move as the user's own report considered
    possible. Added a new "Vest" leaf to `CATEGORY_TREE` (Men/Women/Boys/Girls/Unisex — every
    gender with real vest products) and routed the existing vest/gilet/bodywarmer keyword match
    and the existing Western-waistcoat override to it instead of Jacket. A residual 15 products
    whose titles literally say "Vest Jacket" (Cambridge/Furor/Bandana/Edenrobe) were
    deliberately left as Jacket — descriptions gave genuinely mixed evidence (some explicitly
    say "sleeveless," e.g. Furor's "Tactical Utility Vest Jacket" ("Sleeveless Hunter Jacket"),
    others describe a padded jacket with no sleeveless confirmation at all, e.g. Furor's "Safari
    Vest Jacket" ("Men's Safari Jacket... Snap Button Flap Pockets," no vest/sleeveless word
    anywhere) — not enough of a consistent signal to safely reclassify without risking real
    jackets landing in Vest.

364/364 tests pass (12 new, one set updated for the new expected leaf on 7 existing tests: a
Vest/Gilet/Western-waistcoat product now resolves "Vest," not "Jacket," which is a behavior
CHANGE, not a regression). `reseed_categories.py`'s DSN made env-var-configurable too (same
pattern as backfill_categories.py, #92's own follow-up commit), needed to add the new Vest
category nodes to production without hand-editing the file. Backfill against the existing
117,657-product catalog: 5 new category rows added (Vest × 5 genders) via `reseed_categories.py`,
then 3,297 products recategorized via `backfill_categories.py` (the bulk of it #93/#94's
piece-count fix; 207 of it #95's Vest leaf — Men 130, Women 41, Boys 28, Girls 6, Unisex 2).

## 2026-09-01 (twenty-second pass — user follow-up: "the men vests look very diverse from
actual vests to vest sweater and jackets", then "seeing hooded jackets in hoodies")

96. **A "vest" carrying an activewear signal (gym/training/sports/"active wear"/dry-fit) is a
    sleeveless ATHLETIC TOP, not the outerwear layer the new Vest leaf (#95) was otherwise full
    of.** Read all 130 real Men's Vest products before concluding what was actually wrong.
    Real examples, description verified before trusting the title: One (Be-One)'s "Gym Vest"
    ("Gym vest in dry fit fabrication"), Equator's "Training Vest" ("from our Activewear
    collection...wicks moisture...workouts"), Engine Clothing's "Active Wear Vest" ("activewear
    vest...Lycra Poly Jersey...workouts, training"). These are the same real garment this
    catalog already calls "Tank Top" for every other brand — routed there instead, no new leaf
    needed. Deliberately left Engine Clothing's bare "Men Vest"/"Men Sleeveless Panel Knit Vest"
    (no activewear word in the title) as Vest — not enough signal to move with confidence.
97. **"Hooded" is an ADJECTIVE describing a jacket/coat FEATURE, not the garment's own type — it
    was winning outright over the real garment noun (jacket/coat) appearing later in the same
    title.** 99 real Hoodie-filed products across 10 brands were actually hooded jackets/coats:
    Cambridge/Charcoal/Cougar/Diners/Equator/Furor/Lama/Meme/One(Be-One)/Uniworth's "HOODED
    PUFFER JACKET", "Hooded Denim Jacket", "MEN'S HOODED DUFFLE COAT", "HOODED PUFFER BOMBER
    JACKET". Only the literal NOUN "hoodie" is trusted outright now; a bare "hooded" (no
    "hoodie" noun) is checked again, but only as a LAST RESORT after jacket/coat/blazer/dress
    have all had first claim on a stronger, more specific noun. Real genuine hoodies verified
    by description before keeping them as-is: Cambridge's "WAFFLE/OTTOMAN HOODIE ZIPPER JACKET"
    line (100% soft fleece, cotton-poly blend) and Charcoal's "JACKET FULL SLEEVE KNIT HOODIE"
    line (100% fleece cotton) both contain the literal "hoodie" noun and correctly stay Hoodie
    despite "jacket" also appearing.
98. **"Gilet" wins outright over the hoodie/jacket ambiguity above** — real examples, both
    confirmed genuinely sleeveless via description: Furor's "Hooded Puffer Gilet" ("Gilet
    Jacket... Regular Fit Polyester Fabric") and Cougar's "Hooded Gilet Jacket" ("...sleeveless
    construction and 100% polyester parachute fabric") were landing on Hoodie; now resolve Vest
    (#95's leaf).
99. **"With a hood(ie)" describes an attached-hood DETAIL on another garment, not the garment's
    own type** — same class of fix as `GARMENT_DETAIL_RE`'s existing "with...belt/tie/scarf"
    stripping (#60/#91), applied locally inside the Upperwear leaf-picker since title_blob/blob
    never go through that stripping elsewhere. Real examples: Outfitters' "Faux Leather Jacket
    With Hoodie" (Synthetic Faux Leather) and "Denim Jacket With Hoodie" (100% Cotton denim) are
    both real jackets that merely include an attached hood, landing on Hoodie before this fix.
100. **The last-resort bare-"hooded" fallback (#97) still needed an explicit "shirt" exclusion**
    — "shirt" is never an active check in this function (it's the caller's own final default,
    not a returned leaf here), so it couldn't "already have claimed the return" the way
    jacket/coat do. Real examples: One (Be-One)'s "Hooded Check Shirt" ("Regular fit short
    sleeve shirt in check fabrication, featuring... contrasting jersey hood") and Meme's
    "HOODED DENIM SHIRT" ("SLIM FIT SHACKET WITH REGULAR COLLAR FEATURING HOOD. SNAP BUTTON
    DOWN CLOSURE") are both genuine collared, buttoned shirts with a hood as a design detail —
    were landing on Hoodie, now correctly fall through to the Shirt default.

378/378 tests pass (14 new/updated). Backfill against the existing 117,657-product catalog: 22
products recategorized for #96 (19 Men, 2 Boys, 1 Women — the same bug existed in every
gender's Vest bucket), then 175 more for #97-99 (the vast majority — real hooded jackets/coats
across 10 brands, catalog-wide, not just the two brands #95 was originally scoped to), then 6
more for #100. Idempotency reverified: a second backfill run changed 0 rows.

## 2026-09-01 (twenty-third pass — user-reported Vest sizing looked like jacket sizes; applying
the same size-anomaly-as-signal technique catalog-wide surfaced a real, much larger bug elsewhere)

101. **Investigated first, before touching anything**: user reported Men's Vest showing chest-inch
    sizes (44/46, jacket-style) and asked to fix it. Found the real candidates via a script (29
    Men's Vest products with numeric chest sizing), then — per explicit instruction — read every
    one personally rather than trusting the script's output: downloaded and viewed 10 of the 29
    products' actual photos, spanning every distinct style in the set (Cambridge's quilted/
    padded/sherpa/suede vests, Uniworth's formal Western Waistcoat line). Every single one is a
    real, genuinely sleeveless vest — chest-inch sizing is these brands' own legitimate sizing
    convention for structured vests, not a categorization bug. No change made; a real absence of
    a bug is a valid finding, not a failure to find one.
102. **Applied the same technique across every category, not just Vest** (as asked) — computed
    each (gender, leaf)'s dominant size-system, flagged categories where a numeric-inch minority
    seemed inconsistent with the garment type. Most flags turned out to be other real, legitimate
    alternate conventions (chest sizes for Jacket/Shirt/Waistcoat, waist sizes for Trouser/
    Shorts/Joggers) and were set aside without further action — same discipline as #101, an
    anomaly is a reason to look, not a reason to conclude.
103. **One flag was real and much bigger than the original report**: Men's Co-ord Set had 49% of
    its sized variants using chest-inch sizing — implausible for what's supposed to be casual
    matching separates. Read the actual flagged products (not just their sizes): 393 distinct
    products, dominated by exactly the brands already known to sell formal Western business
    suits (#81) — Uniworth, Monark, Edenrobe, Royal Tag, Cambridge, Equator. Titles/descriptions
    ("Sharp 3 Piece Suit," "SHARP (3PC)," real "Model is 6'2" with a 40" chest, and is wearing a
    size 40" tailoring-fit boilerplate) confirmed these are genuine formal 2/3-piece business
    suits, not casual separates — `FORMAL_SUIT_RE` (#81) missed them because none of them use
    ANY of its trigger words (blazer/lapel/breasted/bespoke/tuxedo/waistcoat) — bare "suit" was
    deliberately excluded from that regex originally (too broad on its own; a casual Co-ord Set
    sometimes loosely uses the same word). Widened the net with two narrower, safe additions
    instead of just adding bare "suit": (a) the PHRASE "formal suit" — unambiguous enough to
    trust outright, since a casual set never calls itself "formal" — which alone caught 112 real
    Edenrobe products literally titled "Formal Suit - EBTCPC..." (only 36 of 148 "Formal
    Suit"-titled products were resolving to the actual Formal Suit leaf before this); and (b)
    "suit" combined with that exact tailoring-fit boilerplate phrase, which catches Cambridge's
    "SHARP"/"LUXER" lines that never say "formal" either. Verified the boilerplate-alone isn't
    itself a safe signal before combining it with anything: it appears on 16 total Co-ord Set
    products, 2 of which ("KNIT & PAJAMA," a genuine loungewear set) don't say "suit" at all —
    requiring both together keeps that one correctly excluded.

381/381 tests pass (5 new). Backfill against the existing 117,657-product catalog: 135 products
recategorized (mostly #103's Formal Suit fix). 148 of 149 "Formal Suit"-titled products now
resolve to the actual Formal Suit leaf (was 36). A smaller, separate residual noted but not
fixed in this pass: 2 Cambridge "Sharp Vest" products (a standalone vest piece from the same
collection, not the full suit) remain in Co-ord Set — different root cause (a vest-vs-Co-ord-Set
boundary question, not formal-suit-related), out of scope for this fix.

## 2026-09-01 (twenty-fourth pass — three rapid user follow-ups on the Vest leaf, each one
found by actually looking, not trusting a title alone)

104. **"Jacket" in the title wins over "gilet"/"vest" outright — no exception, not even for a
    photo-confirmed-sleeveless garment.** Real regression: the prior pass's "gilet wins unless
    'jacket' + no evidence" rule still let a genuinely sleeveless "Gilet Jacket"/"Vest Jacket"
    product stay in Vest whenever its description happened to confirm sleeveless (Cougar's
    "Hooded Gilet Jacket," Charcoal's "QUILTED SUEDE GILET JACKET SLEEVELESS," Engine
    Clothing's "Men Gilet Jacket" — all photo-verified real vests). Asked the user directly via
    AskUserQuestion rather than flip again on a guess: explicit answer was title word wins,
    full stop, regardless of confirmed construction ("logically one would want to see
    sleeveless/vest type jackets in JACKETS SECTION"). Simplified the rule accordingly and
    removed the sleeveless-description exception entirely.
105. **"Open knit" is sweater-weight fabric, never a plain jersey tank.** User-reported directly,
    browsing Men's Vest: "seeing... open knit vest (sweater)." Outfitters' "Open Knit Vest" is
    photo-confirmed a thick ribbed knit layering piece worn over a collared shirt — unmistakably
    a sweater vest. Added "open knit" as its own Sweater trigger.
106. **A plain ribbed/knit "vest" with no other outerwear signal is a basic jersey tank, not
    outerwear and not a sweater** — a different real pattern found in the same sweep. Furor's
    entire "Ribbed Vest" line (6 products, FMTV5/FMTV6/FWTT SKUs, description "Regular Fit Rib
    Fabric") and Engine Clothing's "Men Sleeveless Panel Knit Vest" are both photo-confirmed
    plain scoop-neck/ringer tanks — no padding, quilting, collar, or closure. Routed to Tank
    Top, the same real garment this catalog already uses for every other brand's activewear
    vests. Gated with a new `VEST_REAL_OUTERWEAR_RE` so a genuine quilted/puffer/gilet/
    waistcoat vest whose text merely mentions a ribbed hem/trim as a detail is never caught.
107. **The T-Shirt regex required a hyphen ("t-shirt") or no separator ("tshirt") — never a
    literal space ("t shirt").** Found chasing one specific mislabel (Engine Clothing's "Boys
    Vest T Shirt," a photo-confirmed plain graphic tank landing on the generic Vest leaf) but
    verifying the fix's real scope in Python (not Postgres — its `~*` POSIX regex doesn't
    support `\b` word boundaries the way Python's `re` does, and an initial SQL-side check
    silently under-counted as a result) turned up a much bigger, catalog-wide, previously-
    invisible bug: 2,957 real products titled "Boys T Shirt," "Men T Shirt," "Women T Shirt,"
    "Girls T Shirt," bare "T Shirt," never matched this regex at all and were falling through
    to the generic Shirt default. Also added "vest" + a tee word together as a sleeveless
    signal (mirroring the existing "tank" precedent) so "Vest T Shirt" itself correctly
    resolves Tank Top, not T-Shirt.

388/388 tests pass (11 new/updated). Backfill against the existing 117,657-product catalog: 22
products for #104 (back to Jacket), 8 for #105/#106 (1 to Sweater, 7 to Tank Top), 2,885 for
#107 (the vast majority the spaced-T-Shirt fix, catalog-wide, not Vest-specific). Idempotency
reverified after each.
