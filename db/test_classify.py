"""
Regression tests — one per entry in CHANGELOG.md, using the real title/vendor/
product_type/tags that exposed each bug. Run this after ANY change to
classify(), guess_gender(), or CATEGORY_TREE, before trusting it against the
full catalog:

    python test_classify.py

This is the guardrail for the classifier that will run against every future
daily scrape — a change that "fixes" one thing but silently re-breaks an
earlier fix should fail here, not get discovered by a user three weeks later.
"""
from load_data import classify, guess_gender, CATEGORY_TREE

FAILURES = []
PASSED = 0


def check(label, title, product_type="", vendor="", tags="", store="test", description="",
          expect_gender=None, expect_branch=None, expect_sub=None, expect_leaf=None):
    global PASSED
    result = classify(store, {}, title, product_type, tags, vendor, description)
    problems = []
    if result is None:
        problems.append("classify() returned None (treated as excluded)")
    else:
        if expect_gender and result["gender"] != expect_gender:
            problems.append(f"gender: expected {expect_gender!r}, got {result['gender']!r}")
        if expect_branch and result["branch"] != expect_branch:
            problems.append(f"branch: expected {expect_branch!r}, got {result['branch']!r}")
        if expect_sub is not None and result.get("sub") != expect_sub:
            problems.append(f"sub: expected {expect_sub!r}, got {result.get('sub')!r}")
        if expect_leaf and result["leaf"] != expect_leaf:
            problems.append(f"leaf: expected {expect_leaf!r}, got {result['leaf']!r}")

    if problems:
        FAILURES.append(f"[{label}] {title!r}\n    " + "\n    ".join(problems))
    else:
        PASSED += 1


def check_leaf_exists(gender, branch, sub, leaf):
    """Guards against fixes #7/#9-style bugs: classify() can emit a leaf name
    that doesn't actually exist in CATEGORY_TREE for that gender, which
    silently falls back to the branch node instead of erroring."""
    global PASSED
    branches = CATEGORY_TREE.get(gender, {})
    content = branches.get(branch)
    if content is None:
        FAILURES.append(f"[tree] {gender}/{branch} branch does not exist at all")
        return
    if isinstance(content, dict):
        leaves = content.get(sub, [])
    else:
        leaves = content
    names = [n for n, _ in leaves]
    if leaf not in names:
        FAILURES.append(f"[tree] {gender}/{branch}/{sub} has no leaf {leaf!r} (has {names})")
    else:
        PASSED += 1


# 1. Gender substring bug
check("gender: women not swallowed by men", "Women Printed Lawn Shirt",
      product_type="Woman Pret", expect_gender="Women")
check("gender: men still works", "Men Straight Trouser", product_type="Men",
      expect_gender="Men")

# 4. "short" too greedy
check("short sleeve != Shorts", "Men Off-White Color PQ Solid Short Sleeve Polo Tee",
      expect_branch="Western", expect_sub="Upperwear", expect_leaf="Polo")
check("real shorts still Bottomwear", "Denim Shorts", expect_branch="Western",
      expect_sub="Bottomwear", expect_leaf="Shorts")

# 5. Underwear
check("boxer -> Underwear", "BOXER (PACK OF TWO)", product_type="UNDERWEARS/VESTS",
      expect_branch="Accessories", expect_leaf="Underwear")

# 6/7. Kurta combo sets
check("kurta pajama -> Kurta Set (Men)", "M Grey Texture Smart Fit Kurta Pajama",
      vendor="Men", expect_gender="Men", expect_branch="Eastern", expect_leaf="Kurta Set")
check("boys kurta pajama -> Kurta Set (Boys)", "Light Purple Boys Kurta Pajama With Waistcoat",
      vendor="D-Juniors Boys", expect_gender="Boys", expect_branch="Eastern", expect_leaf="Kurta Set")
check("plain kurta stays Kurta", "Blended Kurta - EBTK19-3597", vendor="D-Juniors Boys",
      expect_gender="Boys", expect_leaf="Kurta")

# 9. Leaf-picking slug/keyword mismatch
check("jewel -> Jewelry not Bag", "Jewel - EMUB22S-JEWEL", product_type="Men Un Stitched",
      vendor="Blended", expect_branch="Accessories", expect_leaf="Jewelry")

# 10. shawl collar false positive
check("shawl collar sweater is not an accessory", "Shawl Collar Color-Block Sweater",
      vendor="Boys", expect_branch="Western", expect_sub="Upperwear")

# 11. Sherwani / Waistcoat
check("sherwani -> Eastern", "Sherwani Suit - ECBTSS5-008", vendor="Boys",
      expect_branch="Eastern", expect_leaf="Sherwani")
check("waistcoat suit -> Eastern", "Embroidered Silk Waistcoat Suit - ECBTWCS6-106",
      vendor="Boys", expect_branch="Eastern", expect_leaf="Waistcoat")

# 13/14. Unstitched piece-count fallback
check("SKU -3P suffix counted", "Embroidered Lawn Suit - EWU5V1-31244-3P",
      product_type="Woman Un Stitched", vendor="Women", expect_branch="Eastern",
      expect_sub="Unstitched", expect_leaf="3-Piece")
check("named pieces counted (Shirt Trouser)", "Printed Khaddar Shirt Trouser - EWU24A3-29303ST",
      product_type="Woman Un Stitched", vendor="Women", expect_branch="Eastern",
      expect_sub="Unstitched", expect_leaf="2-Piece")
check("no signal at all falls to Suit not branch", "Embroidered Lawn Suit",
      product_type="Woman Un Stitched", vendor="Women", expect_branch="Eastern",
      expect_sub="Unstitched", expect_leaf="Suit")

# 15. sweatpants vs sweatshirt
check("sweatpant -> Bottomwear not Sweatshirt", "Solid Sweatpant", vendor="Men",
      expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Joggers")
check("real sweatshirt still Sweatshirt", "Crew Neck Sweatshirt", vendor="Men",
      expect_branch="Western", expect_sub="Upperwear", expect_leaf="Sweatshirt")

# 16. Hoodie
check("hoodie gets its own leaf", "Pullover Hoodie", vendor="Men",
      expect_branch="Western", expect_sub="Upperwear", expect_leaf="Hoodie")

# 17. watch maker / blackwatch false positive
check("watch maker fabric != Watch accessory", "BLENDED TEXTURED (WATCH MAKER)",
      product_type="UNSTITCHED", vendor="Mashriq", expect_branch="Eastern")
check("real watch still Watch", "Men's Analog Wrist Watch", vendor="Men",
      expect_branch="Accessories", expect_leaf="Watch")

# 18. Boys missing Polo leaf entirely
check("boys polo tee -> Polo", "Boys Polo Tee", vendor="Boys",
      expect_gender="Boys", expect_branch="Western", expect_leaf="Polo")

# 19. Girls missing Sunglasses leaf entirely
check("girls sunglasses -> Sunglasses", "Square-Framed Sunglasses", vendor="Girls",
      expect_gender="Girls", expect_branch="Accessories", expect_leaf="Sunglasses")

# 20. Girls missing a plain "Shirt" leaf (only had T-Shirt/Top/Dress)
check("girls solid shirt -> Shirt", "SOLID SHIRT FOR GIRLS", vendor="Girls",
      expect_gender="Girls", expect_branch="Western", expect_leaf="Shirt")

# 21. "Dress Shirt" collision (dress as adjective, not the garment)
check("dress shirt != Dress", "DRESS SHIRT BEIGE", vendor="Men",
      expect_gender="Men", expect_branch="Western", expect_leaf="Shirt")
check("real dress still Dress", "Floral Summer Dress", vendor="Women",
      expect_gender="Women", expect_branch="Western", expect_leaf="Dress")

# 22. Tights/leggings had no leaf and no keyword at all
check("tights -> Bottomwear", "Solid Tight", vendor="Girls",
      expect_gender="Girls", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Tights")

# 23. "denim" without the word "jean" still Bottomwear/Jeans
check("flared denim -> Jeans", "Girls Flared Denim", vendor="Girls",
      expect_gender="Girls", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Jeans")

# 25. Vendor must win over a noisy stray tag ("Women-Jacquard" on a girls' item)
check("vendor beats noisy tag", "Striped Dress", vendor="COUGAR GIRL (S-V2-2026)",
      tags="dresses,FROCK,girl-dress,Girls Dresses,Junior Girls,Women-Jacquard",
      expect_gender="Girls", expect_branch="Western", expect_leaf="Dress")

# 26. "Junior" text signal, previously not checked at all
check("junior text -> Unisex not store default Men", "Junior Magenta Pajama Suit",
      store="diners", expect_gender="Unisex")

# 28. "frock" is not Eastern-specific — checked all 11 real Cougar uses,
# every one is a plain Western casual dress
check("cougar Girl Frock -> Western Dress, not Eastern", "Striped Dress",
      product_type="Girl Frock", vendor="COUGAR GIRL (S-V2-2026)",
      expect_gender="Girls", expect_branch="Western", expect_leaf="Dress")
check("edenrobe frock also treated as a dress, not assumed Eastern",
      "Frock - EGTF18W-0812", product_type="Girls Winter Frocks", vendor="Girls",
      expect_gender="Girls", expect_branch="Western", expect_leaf="Dress")

# 27. Kids sizing with zero textual signal anywhere — check() doesn't thread
# raw variant data through classify(), so this calls guess_gender() directly.
import load_data as _ld
_kids_variants_rest = {
    "options": [{"name": "Size", "values": ["5-6 Years", "7-8 Years", "9-10 Years"]}],
    "variants": [{"option1": "5-6 Years"}, {"option1": "7-8 Years"}, {"option1": "9-10 Years"}],
}
_gender = _ld.guess_gender("diners", "Plain Dress", "", "", "", p=_kids_variants_rest, is_graphql=False)
if _gender != "Unisex":
    FAILURES.append(f"[kids sizing, no text signal] expected Unisex, got {_gender!r}")
else:
    PASSED += 1

# 30. QA/placeholder test products and checkout packaging bags are not real
# merchandise and must be excluded entirely, not misfiled into Upperwear.
for label, title, ptype, vendor in [
    ("bare 'Test' placeholder excluded", "Test", "", "Equator"),
    ("payment-gateway test SKU excluded", "Test XPay", "", "Monark Clothing"),
    ("(TEST) suffix excluded even on real-looking title", "MEN T-SHIRT (TEST)", "", "Breakout"),
    ("Outfitters checkout shopping bag excluded", "Outfitters Shopping Bag", "SHOPPING BAGS", "Outfitters"),
    ("Equator shopping bag excluded", "Shopping Bags", "", "Equator Stores"),
]:
    result = classify("test", {}, title, ptype, "", vendor, "")
    if result is not None:
        FAILURES.append(f"[{label}] {title!r} expected excluded (None), got {result}")
    else:
        PASSED += 1

# 31. "bag"/"handbag" plural word-boundary bug (same class as jewelry/
# sunglasses/socks) — a real bag product must still resolve to Accessories,
# not fall through since "bags" (plural) never matched bare \bbag\b.
check("plural 'Bag' -> Accessories", "Men Bag", vendor="Men",
      expect_branch="Accessories", expect_leaf="Bag")
check("Crossbody Bag -> Accessories", "Crossbody Bag", vendor="Men",
      expect_branch="Accessories", expect_leaf="Bag")

# 32. Vendor's age-only word ("junior") must not out-rank an explicit gender
# word found in tags/product_type — vendor "CAMBRIDGE JUNIOR" was winning
# outright and returning Unisex before ever checking tags that said "BOYS
# SWEATER" explicitly.
check("vendor 'junior' doesn't override explicit tag gender", "Clever Breton Stripes",
      product_type="HALF ZIPPER SWEATER", vendor="CAMBRIDGE JUNIOR",
      tags="Blessed Friday 22,BOYS SWEATER,CAMBRIDGE JUNIOR",
      expect_gender="Boys", expect_branch="Western", expect_sub="Upperwear")
check("age-only word with genuinely no gender signal still falls to Unisex",
      "Junior Kurta Pajama Suit", product_type="JUNIOR SHALWAR SUIT", vendor="Mashriq",
      tags="2024,junior-shalwar-suit", expect_gender="Unisex", expect_branch="Eastern",
      expect_leaf="Kurta Set")

# 33. Unisex needs real Western/Eastern branches, not just Accessories —
# genuinely gender-ambiguous kids items still need somewhere to land.
check_leaf_exists("Unisex", "Western", "Upperwear", "Shirt")
check_leaf_exists("Unisex", "Eastern", "Stitched", "Shalwar Kameez")
check_leaf_exists("Unisex", "Eastern", "Unstitched", "Suit")

# 34. Boys/Girls Western branch was missing Footwear entirely even though
# classify() can emit Footwear>Shoes for any gender.
check_leaf_exists("Boys", "Western", "Footwear", "Shoes")
check_leaf_exists("Girls", "Western", "Footwear", "Shoes")

# 35. Boys/Girls perfumes ("BOYS STAR WARS PERFUME" etc, vendor "KIDS",
# product_type "PERFUMES") had no Fragrance & Beauty branch at all.
check("boys perfume -> Fragrance & Beauty", "BOYS STAR WARS PERFUME",
      product_type="PERFUMES", vendor="KIDS", expect_gender="Boys",
      expect_branch="Fragrance & Beauty", expect_leaf="Perfume")
check("girls perfume -> Fragrance & Beauty", "GIRLS HELLO KITTY PERFUME",
      product_type="PERFUMES", vendor="KIDS", expect_gender="Girls",
      expect_branch="Fragrance & Beauty", expect_leaf="Perfume")

# 36. Boys' Eastern tree missing Shalwar Kameez/Waistcoat leaves
check("boys shalwar suit -> Shalwar Kameez", "Boys Shalwar Suit",
      product_type="Boys Shalwar Kameez", vendor="D-Juniors Boys",
      expect_gender="Boys", expect_branch="Eastern", expect_leaf="Shalwar Kameez")

# 37. Men's Accessories missing Shawl leaf (Women's tree already had it)
check("men shawl -> Shawl", "Black Plain Wool Blend Men Shawl", product_type="simple",
      vendor="Saqafat", expect_gender="Men", expect_branch="Accessories", expect_leaf="Shawl")

# 38. Women's tree missing Tights and Polo leaves
check("women tights -> Tights", "Women Solid Tights", product_type="Women", vendor="ENGINE",
      expect_gender="Women", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Tights")
check("women polo -> Polo", "POLO SHIRT FOR WOMEN", product_type="T-Shirts For Women", vendor="MEME",
      expect_gender="Women", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Polo")

# 39. "tie dye"/"front tie" false positives on the Tie accessory keyword —
# real garments were being misfiled into Accessories>Tie or, for Boys/Girls
# (whose tree had no Tie leaf at all), stranded on the bare Accessories
# branch node.
check("tie dye t-shirt is not a Tie accessory", "TIE DYE T-SHIRT FOR MEN", vendor="Men",
      expect_gender="Men", expect_branch="Western", expect_leaf="T-Shirt")
check("tie dye joggers is not a Tie accessory", "TIE DYE JOGGER PANT FOR MEN", vendor="Men",
      expect_gender="Men", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Joggers")
check("front tie top is not a Tie accessory", "Front Tie Top", vendor="COUGAR GIRL (S-V3-2026)",
      expect_gender="Girls", expect_branch="Western", expect_leaf="Shirt")
check("real necktie still Tie", "Poly Silk Tie", vendor="Men",
      expect_gender="Men", expect_branch="Accessories", expect_leaf="Tie")
check("real bow tie still Tie", "Bow Tie", vendor="Men",
      expect_gender="Men", expect_branch="Accessories", expect_leaf="Tie")

# 40. Ambiguous "BAGS & WALLETS" product_type bucket must not force a
# specific bag/case product into a nonexistent "Wallet" leaf just because
# "wallet" also appears in that shared bucket label.
check("backpack under 'BAGS & WALLETS' bucket -> Bag not Wallet", "Soccer School Backpack",
      product_type="BAGS & WALLETS", vendor="Boys", expect_gender="Boys",
      expect_branch="Accessories", expect_leaf="Bag")
check("pencil case under 'BAGS & WALLETS' bucket -> Bag not Wallet", "Lion Themed Pencil Case",
      product_type="BAGS & WALLETS", vendor="Boys", expect_gender="Boys",
      expect_branch="Accessories", expect_leaf="Bag")

# 41. Boys/Girls Accessories missing Belt/Watch/Wallet/Cap leaves
check("boys belt -> Belt", "Textured Faux Leather Belt", product_type="BELTS & BRACES",
      vendor="Boys Junior", expect_gender="Boys", expect_branch="Accessories", expect_leaf="Belt")
check("boys watch -> Watch", "Digital Watch With Silicone Strap", product_type="WATCHES",
      vendor="Boys Junior", expect_gender="Boys", expect_branch="Accessories", expect_leaf="Watch")
check("girls watch -> Watch", "Digital LED Watch", product_type="WATCHES", vendor="Girls Junior",
      expect_gender="Girls", expect_branch="Accessories", expect_leaf="Watch")
check("girls cap -> Cap", "GIRLS CAP", product_type="CAP", vendor="KIDS",
      expect_gender="Girls", expect_branch="Accessories", expect_leaf="Cap")

# 42. "Cap" leaf-picker substring collision — space-stripped bare substring
# matching let "cap" match inside "cape", misfiling a real shawl as a cap.
check("cape shawl is Shawl not Cap", "Women Printed Cape Shawl", product_type="Women",
      vendor="ENGINE", expect_gender="Women", expect_branch="Accessories", expect_leaf="Shawl")

# 43. Boys' Eastern tree missing Sherwani leaf entirely
check("boys sherwani suit -> Sherwani", "Sherwani Suit - EBTCSS5-004",
      product_type="Boys Sherwani Suit", vendor="edenrobe Pakistan",
      expect_gender="Boys", expect_branch="Eastern", expect_leaf="Sherwani")

# 44. "with ... belt/tie" describes an attached design detail on another
# garment, not a standalone belt/tie product.
check("jeans with belt detail stay Jeans", "Barrel Fit Jeans With Belt Detail",
      product_type="JEANS", vendor="Women", expect_gender="Women",
      expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Jeans")
check("shirt with tie detail stays Shirt", "BUTTON DOWN SHIRT WITH TIE DETAIL",
      product_type="WOVEN", vendor="BREAKOUT", expect_branch="Western", expect_leaf="Shirt")
check("dress with waist belt stays Dress", "Long Dress With  Waist Belt",
      vendor="COUGAR WOMEN (S-V3-2026)", expect_gender="Women",
      expect_branch="Western", expect_leaf="Dress")
check("real standalone belt still Belt", "Faux Leather Belt", product_type="BELTS & BRACES",
      vendor="Women", expect_gender="Women", expect_branch="Accessories", expect_leaf="Belt")

# 45. Women's Accessories missing Belt/Cap/Wallet leaves
check("women cap -> Cap", "Embroidered Cap", product_type="CAPS & HATS", vendor="Women",
      expect_gender="Women", expect_branch="Accessories", expect_leaf="Cap")

# 46. "Kurti" is exclusively a girls'/women's garment name in this catalog's
# own taxonomy — a real Diners/Sohaye item had the compound tag
# "girls-western&boys-eastern-western" (containing the literal word "boys")
# outrank its own clean "girls-eastern" tag during gender resolution.
check("kurti forces gender to Girls even if a stray tag said boys",
      "Pink Embroidered Teens Kurti", product_type="Teens 2 Piece", vendor="Sohaye",
      tags="2 Piece,cotton jacquard,D-Juniors,girls-eastern,girls-western&boys-eastern-western,Teens",
      store="diners", expect_gender="Girls", expect_branch="Eastern", expect_leaf="Kurti")

# 47. Unstitched fabric with a bare garment-name word must not resolve to a
# Stitched-only leaf name ("Kurta") that doesn't exist under any gender's
# Unstitched sub-tree — falls to the generic "Suit" catch-all instead.
check("unstitched kurta collection -> Suit not Kurta", "UNSTITCHED KURTA COLLECTION",
      product_type="UNSTITCHED", vendor="Mashriq", expect_branch="Eastern",
      expect_sub="Unstitched", expect_leaf="Suit")

# 48. "Dress...Shirt" with an intervening word (fabric-pattern name) is the
# same men's-formal-shirt collision as bare "Dress Shirt".
check("dress stripes shirt != Dress", "Purple Dress Stripes Shirt",
      product_type="Premium Egyptian Cotton", vendor="Formal Shirt",
      expect_branch="Western", expect_leaf="Shirt")
check("plural 'dress shirts' product_type bucket != Dress", "DRESS SHIRT BLUE",
      product_type="dress shirts", vendor="Charcoal Clothing",
      expect_branch="Western", expect_leaf="Shirt")

# 49. Hyphenated "Tie-X" compounds are a design detail, not a necktie — same
# collision class as "Tie Dye"/"Front Tie" but written without a space.
check("tie-waist playsuit is not a Tie accessory", "Tie-Waist Playsuit",
      vendor="COUGAR GIRL (S-V1-2026)", expect_gender="Girls", expect_branch="Western")
check("tie-up jumpsuit is not a Tie accessory", "Tie-Up Jumpsuit White/Blue",
      product_type="Jump Suits", vendor="Girls", expect_gender="Girls", expect_branch="Western")
check("hair tie -> Jewelry not Tie", "Pack of 3 Bow Hair Tie", product_type="JEWELLERY",
      vendor="Women", expect_gender="Women", expect_branch="Accessories", expect_leaf="Jewelry")
check("'tie up' with a space is not a Tie accessory", "Tie Up Jumpsuit White/Blue",
      product_type="Jump Suits", vendor="Girls", expect_gender="Girls",
      expect_branch="Western", expect_sub="Upperwear", expect_leaf="Jumpsuit")
check("'tie & die' misspelling of dye is not a Tie accessory",
      "Tie & Die Viscose Dress - FWTD24-009", vendor="Furorjeans",
      expect_branch="Western", expect_leaf="Dress")

# 50. Women's/Girls' Eastern trees missing Waistcoat; Girls' missing
# Kurta/Kurta Set entirely (only had Kurti).
check("women waistcoat -> Waistcoat", "Waistcoat - ELTWC19-66953",
      product_type="Woman Waist Coat", vendor="Lawn", expect_gender="Women",
      expect_branch="Eastern", expect_leaf="Waistcoat")
check("girls waistcoat -> Waistcoat", "Green Infant Girl Waistcoat",
      product_type="Infant Kurti", vendor="D-Juniors Girls", expect_gender="Girls",
      expect_branch="Eastern", expect_leaf="Waistcoat")
check("girls kurta -> Kurta", "Kurta", product_type="Girls", vendor="ENGINE",
      expect_gender="Girls", expect_branch="Eastern", expect_leaf="Kurta")

# 51. Men's Western Bottomwear missing Tights (athletic compression wear)
check("men compression tights -> Tights", "Compression Tights", product_type="Tights",
      vendor="Men", expect_gender="Men", expect_branch="Western", expect_sub="Bottomwear",
      expect_leaf="Tights")

# 52. Bare "denim" is a fabric name, not a bottomwear signal on its own —
# real jackets/shirts/dresses/polos made of or trimmed with denim were
# resolving to Jeans purely because "denim" appeared anywhere in the title.
check("denim collar polo stays Polo, not Jeans", "DENIM COLLAR POLO GREY", vendor="Men",
      expect_branch="Western", expect_leaf="Polo")
check("polo shirt denim collar stays Polo", "POLO SHIRT DENIM COLLAR GREEN", vendor="Men",
      expect_branch="Western", expect_leaf="Polo")
check("denim jacket stays Jacket, not Jeans", "DENIM JACKET", vendor="Men",
      expect_branch="Western", expect_leaf="Jacket")
check("denim shirt stays Shirt, not Jeans", "DENIM SHIRT - BLUE", vendor="Men",
      expect_branch="Western", expect_leaf="Shirt")
check("denim dress stays Dress, not Jeans", "Embroidered Denim Dress", vendor="Women",
      expect_branch="Western", expect_leaf="Dress")
check("bare denim with no other garment word still Jeans", "Baggy Fit Denim", vendor="Men",
      expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Jeans")

# 53. "Sweater" leaf existed only in Men's tree but classify() never
# actually emitted it — real sweaters across every gender were falling
# through to the generic "Shirt" bucket (1,482 real products confirmed).
check("sweater -> Sweater not Shirt", "Basic Textured Sweater", product_type="SWEATERS",
      vendor="Men", expect_gender="Men", expect_branch="Western", expect_leaf="Sweater")
check("girls sweater -> Sweater", "Girls Cable Knit Sweater", vendor="Girls",
      expect_gender="Girls", expect_branch="Western", expect_leaf="Sweater")
check("sweatshirt still Sweatshirt, not confused with Sweater", "Crew Neck Sweatshirt",
      vendor="Men", expect_branch="Western", expect_leaf="Sweatshirt")

# Tree-shape guards: every leaf classify() can possibly emit must exist for
# every gender it can be emitted under.
for gender in ("Men", "Women", "Boys", "Girls"):
    check_leaf_exists(gender, "Accessories", None, "Underwear")
check_leaf_exists("Men", "Eastern", "Stitched", "Sherwani")
check_leaf_exists("Boys", "Eastern", "Stitched", "Kurta Set")
check_leaf_exists("Girls", "Eastern", "Stitched", "Shalwar Kameez")
check_leaf_exists("Girls", "Western", "Bottomwear", "Jeans")
check_leaf_exists("Girls", "Western", "Suits & Sets", "Co-ord Set")
for gender in ("Men", "Women", "Boys", "Girls"):
    check_leaf_exists(gender, "Eastern", "Unstitched", "Suit")
    check_leaf_exists(gender, "Western", "Upperwear", "Hoodie")
    check_leaf_exists(gender, "Western", "Bottomwear", "Joggers")
    check_leaf_exists(gender, "Western", "Upperwear", "Shirt")
check_leaf_exists("Boys", "Western", "Upperwear", "Polo")
check_leaf_exists("Girls", "Accessories", None, "Sunglasses")
check_leaf_exists("Boys", "Accessories", None, "Sunglasses")
check_leaf_exists("Girls", "Western", "Bottomwear", "Tights")
for gender in ("Men", "Women", "Boys", "Girls", "Unisex"):
    check_leaf_exists(gender, "Accessories", None, "Bag")
check_leaf_exists("Men", "Accessories", None, "Shawl")
check_leaf_exists("Women", "Western", "Bottomwear", "Tights")
check_leaf_exists("Women", "Western", "Upperwear", "Polo")
check_leaf_exists("Boys", "Eastern", "Stitched", "Shalwar Kameez")
check_leaf_exists("Boys", "Eastern", "Stitched", "Waistcoat")
for gender in ("Boys", "Girls"):
    check_leaf_exists(gender, "Accessories", None, "Belt")
    check_leaf_exists(gender, "Accessories", None, "Watch")
    check_leaf_exists(gender, "Accessories", None, "Wallet")
check_leaf_exists("Girls", "Accessories", None, "Cap")
for gender in ("Men", "Women", "Boys", "Girls"):
    check_leaf_exists(gender, "Fragrance & Beauty", None, "Perfume")
check_leaf_exists("Women", "Western", "Bottomwear", "Tights")
check_leaf_exists("Women", "Accessories", None, "Belt")
check_leaf_exists("Women", "Accessories", None, "Cap")
check_leaf_exists("Women", "Accessories", None, "Wallet")
check_leaf_exists("Girls", "Western", "Upperwear", "Jacket")
check_leaf_exists("Girls", "Western", "Upperwear", "Polo")
check_leaf_exists("Boys", "Eastern", "Stitched", "Sherwani")
check_leaf_exists("Women", "Eastern", "Stitched", "Waistcoat")
check_leaf_exists("Girls", "Eastern", "Stitched", "Waistcoat")
check_leaf_exists("Girls", "Eastern", "Stitched", "Kurta")
check_leaf_exists("Girls", "Eastern", "Stitched", "Kurta Set")
check_leaf_exists("Men", "Western", "Bottomwear", "Tights")
for gender in ("Men", "Women", "Boys", "Girls", "Unisex"):
    check_leaf_exists(gender, "Western", "Upperwear", "Sweater")

# 45. Women's "Shorts" catching real upperwear/dresses/outerwear —
# three distinct real collisions found while browsing the live catalog:
#
# (a) "short-sleeve"/"short-sleeved" (hyphenated) never excluded — the
# sleeve lookahead only handled a whitespace separator.
check("hyphenated short-sleeve shirt stays Shirt, not Shorts", "Short-Sleeve Shirt",
      vendor="cougar", expect_branch="Western", expect_leaf="Shirt")
check("hyphenated short-sleeve button-down stays Shirt", "Short-Sleeve Button-Down",
      vendor="cougar", expect_branch="Western", expect_leaf="Shirt")
check("hyphenated short-sleeved sweater stays Sweater, not Shorts", "Short-Sleeved Sweater",
      vendor="cougar", expect_branch="Western", expect_leaf="Sweater")
check("textured short-sleeved shirt stays Shirt", "Textured Short-Sleeved Shirt",
      vendor="cougar", expect_branch="Western", expect_leaf="Shirt")
# (b) bare singular "short" as a length ADJECTIVE ahead of another garment
# noun (coat/dress/jacket/blazer), not the garment "shorts" itself.
check("'short coat' is a Jacket, not Shorts", "Oversized Short Coat",
      vendor="cougar", expect_branch="Western", expect_leaf="Jacket")
check("'woolen short coat' is a Jacket, not Shorts", "Woolen Short Coat - FWTSC24-001",
      vendor="furor", product_type="Woman Coats", expect_branch="Western", expect_leaf="Jacket")
check("'short dress' is a Dress, not Shorts", "SHORT DRESS FOR WOMEN",
      vendor="meme", product_type="Dresses For Women", expect_branch="Western", expect_leaf="Dress")
check("'printed short dress' is a Dress, not Shorts", "PRINTED SHORT DRESS FOR WOMEN",
      vendor="meme", product_type="Dresses For Women", expect_branch="Western", expect_leaf="Dress")
# genuine bare-singular "short" (no excluded noun following) must still
# resolve to Shorts — the adjective exclusion must not overreach.
check("bare 'short for women' with no following noun stays Shorts", "SHORT FOR WOMEN",
      vendor="meme", product_type="Shorts For Women", expect_branch="Western", expect_leaf="Shorts")
check("'casual short for women' stays Shorts", "CASUAL SHORT FOR WOMEN",
      vendor="meme", product_type="Shorts For Women", expect_branch="Western", expect_leaf="Shorts")
# (c) Engine Clothing's "Shorts Body Blazer/Jacket" line-naming
# convention — "Shorts" here is a literal product-line prefix, never the
# garment; vendor/tags confirm these are real winter blazers/jackets, no
# field anywhere says "short" in the length sense.
check("Engine 'Women Shorts Body Blazer' is a Jacket, not Shorts", "Women Shorts Body Blazer",
      vendor="ENGINE", product_type="Women", expect_branch="Western", expect_leaf="Jacket")
check("Engine 'Women Shorts Body Jacket' is a Jacket, not Shorts", "Women Shorts Body Jacket",
      vendor="ENGINE", product_type="Women", expect_branch="Western", expect_leaf="Jacket")
# (d) store's own product_type mislabeled "Shorts" on a real pair of
# jeans — title is the more reliable signal and must win over a
# conflicting product_type bucket.
check("title 'Jeans' wins over mislabeled product_type 'Shorts'", "Basic Barrel Jeans",
      vendor="Women", product_type="Shorts", expect_branch="Western", expect_leaf="Jeans")
# a product_type-only Shorts signal (no conflicting bottomwear word in the
# title at all) must still fall back to Shorts correctly.
check("product_type Shorts with no title signal still resolves Shorts", "Striped Pleated Jorts",
      vendor="Women", product_type="SHORTS", expect_branch="Western", expect_leaf="Shorts")
# real coat line (unrelated to the Shorts collision) that was separately
# found falling through to the generic Shirt bucket while investigating.
check("'long coat' is a Jacket, not Shirt", "BAN COLLAR LONG COAT BLACK",
      vendor="Charcoal Clothing", product_type="long coats",
      expect_branch="Western", expect_leaf="Jacket")
check("waistcoat is unaffected by the new bare-coat check", "Ash Grey Waistcoat",
      vendor="D Man", product_type="Waist Coat", expect_branch="Eastern", expect_leaf="Waistcoat")

# 46. Bare "vest" wrongly treated as an unconditional Underwear signal —
# ~90 real products under the live Underwear category were actually
# outerwear/activewear/formalwear vests, not undergarments. Fixed by
# requiring an explicit undergarment signal (sando/undergarment, possibly
# only in the description) with no outerwear signal present.
check("sando vest is Underwear", "MEN'S COTTON SANDO VEST",
      vendor="Accessories- undergarments", product_type="Undergarments",
      expect_branch="Accessories", expect_leaf="Underwear")
check("undergarment product_type vest is Underwear", "MEN'S SEAMLESS COTTON VEST",
      vendor="Accessories- undergarments", product_type="VEST",
      expect_branch="Accessories", expect_leaf="Underwear")
check("boxer still Underwear, unaffected by removing bare 'vest'", "BOXER (PACK OF TWO)",
      vendor="Cambridge", product_type="UNDERWEARS/VESTS",
      expect_branch="Accessories", expect_leaf="Underwear")
# Not asserting an exact leaf here: with no "jacket"/"blazer"/"coat" word
# in product_type+title, this falls to the generic Shirt default — a
# known, honestly-flagged residual gap (not perfectly categorized), but
# the bug that mattered (wrongly landing in Underwear) is fixed.
check("quilted vest is NOT Underwear (falls to Western default)", "Quilted Vest",
      vendor="Cambridge jackets", product_type="Vest", expect_branch="Western")
check("sweater vest is a Sweater, not Underwear", "Argyle Pattern Sweater Vest",
      vendor="COUGAR MEN (WINTER-2025)", expect_branch="Western", expect_leaf="Sweater")
check("active wear vest is not Underwear", "Active Wear Vest",
      vendor="ENGINE", product_type="Men", expect_branch="Western")
check("vest gilet resolves its own Vest leaf, not Underwear", "Vest Gilet",
      vendor="Quilted", product_type="Men Jackets", expect_branch="Western", expect_leaf="Vest")
check("suiting vest is not Underwear", "MENS SUITING VEST",
      vendor="Suits", product_type="3 PC SUIT", expect_branch="Western")
check("description-only undergarment signal still resolves Underwear", "White Plain Sleeveless Ribbed Vest",
      vendor="Uniworth", product_type="configurable",
      description="This amazing sleeveless vest is made with an ultra-fitting for active "
                   "performance. our sporty undergarment will keep you cool fresh and comfortable",
      expect_branch="Accessories", expect_leaf="Underwear")

# 47. Women's CATEGORY_TREE only ever had a "Kurti" leaf under
# Eastern/Stitched, never "Kurta" — but classify() has always been able
# to emit leaf="Kurta" for a Women's product (any title saying "kurta"
# without "kurti"), with nowhere for it to resolve. Found via the
# branch-level-orphan audit after adding Zellbury, whose real listings
# ("Embroidered Kurta - 2274", "Kurta Dupatta Trouser - 0762", 111 real
# products) use "Kurta" for women's wear.
check("women's 'Kurta' (not Kurti) resolves to its own Kurta leaf", "Embroidered Kurta - 2274",
      vendor="ZELLBURY WOMEN", product_type="Essential Pret",
      expect_gender="Women", expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Kurta")
check("women's 'Kurti' still resolves Kurti, unaffected by the new Kurta leaf", "Printed Kurti",
      vendor="Women", expect_gender="Women", expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Kurti")
check_leaf_exists("Women", "Eastern", "Stitched", "Kurta")

# 48. "waist tie" (a garment's self-tie closure detail) was matching the
# Tie ACCESSORY_RE/leaf check meant for actual neckties — same collision
# class as the existing "front tie"/"hair tie" exclusions. Real example
# found by the same branch-level-orphan audit: "TEXTURED WAIST TIE TOP"
# (Breakout, Women) — CATEGORY_TREE has no Tie leaf for Women at all
# (only Men/Unisex), so this was stranding on the bare Accessories branch
# node.
check("'waist tie top' is a Shirt, not a Tie accessory", "TEXTURED WAIST TIE TOP",
      vendor="BREAKOUT", product_type="WOVEN", tags="WOMEN,WOVEN,WOVEN SHIRT",
      expect_gender="Women", expect_branch="Western", expect_leaf="Shirt")
check("real necktie still resolves Tie, unaffected by the waist exclusion", "Poly Silk Tie",
      vendor="Men", expect_gender="Men", expect_branch="Accessories", expect_leaf="Tie")

# 49. "keychain" was never recognized as an accessory anywhere in
# classify() — 9 real Furor products (product_type literally "Key
# Chains") had nowhere to resolve. The 2 with "jeans" in the title
# ("Furor Jeans Club Keychain", "Furor Jeans Keychain" — "Jeans" here is
# the brand's own line name, Furor's vendor is literally "Furorjeans")
# fell through to the bare-"jeans" Bottomwear check and landed in Men's
# Jeans; the other 7 (no "jeans" in the title) fell through every branch
# to the generic Western Upperwear "Shirt" default. Added "keychain" to
# ACCESSORY_RE/_KEYWORD_LEAVES and a new "Keychain" leaf to Men's
# CATEGORY_TREE — recognizing the actual accessory type fixes the Jeans
# collision at the source rather than special-casing "jeans" again.
check("'Furor Jeans Club Keychain' is a Keychain, not Jeans", "Furor Jeans Club Keychain - FAKC24-009",
      vendor="Furorjeans", product_type="Key Chains", tags="Men,Men_Accessories",
      expect_gender="Men", expect_branch="Accessories", expect_leaf="Keychain")
check("'Furor Jeans Keychain' is a Keychain, not Jeans", "Furor Jeans Keychain - FAKC24-002",
      vendor="Furorjeans", product_type="Key Chains", tags="Men,Men_Accessories",
      expect_gender="Men", expect_branch="Accessories", expect_leaf="Keychain")
check("plain 'Acrylic Keychain' (no jeans collision) also resolves Keychain", "Acrylic Keychain - FAKC24-005",
      vendor="Furorjeans", product_type="Key Chains", tags="Men,Men_Accessories",
      expect_gender="Men", expect_branch="Accessories", expect_leaf="Keychain")
check_leaf_exists("Men", "Accessories", None, "Keychain")
check("real jeans still Jeans, unaffected by the Keychain leaf", "Loose Fit Jeans - FMBP6-034",
      vendor="Furorjeans", product_type="Men Denim Jeans", tags="Men,Men_Bottoms",
      expect_gender="Men", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Jeans")

# 50. "vest" and plural garment nouns ("jackets", not just singular
# "jacket") missing from the bare-"denim" exclusion list — real example
# "Hooded Denim Vest" (Furor, product_type literally "Men Jackets",
# PLURAL — the original singular-only "jacket" never matched it) was
# resolving to Jeans purely because of "denim" in the title, same
# collision class as "DENIM JACKET"/"Denim Shirt" (fix #43).
check("'Hooded Denim Vest' is not Jeans", "Hooded Denim Vest - FMTJD21-018",
      vendor="Furorjeans", product_type="Men Jackets", tags="Men,Men_Winter_Wear,winter",
      expect_gender="Men", expect_branch="Western", expect_sub="Upperwear")

# 51. Two more real evidence-driven CATEGORY_TREE gender-tree gaps found
# by the same branch-level-orphan audit while verifying #49/#50, both the
# same latent-gap class as #47 (a leaf classify() can emit for a gender
# but that gender's tree never defined):
# (a) real Zellbury "Kurta Shalwar" combo listings (6 products) hit
# KURTA_COMBO_RE and resolve leaf="Kurta Set", which Men/Boys/Girls
# already had but Women's tree didn't (only added plain "Kurta" in #47).
check("women's 'Kurta Shalwar' combo resolves Kurta Set", "Kurta Shalwar - 1679",
      vendor="ZELLBURY WOMEN", product_type="Essential Pret",
      expect_gender="Women", expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Kurta Set")
check_leaf_exists("Women", "Eastern", "Stitched", "Kurta Set")
# (b) real Outfitters "Multi-Charm Keychain"/"Crochet Keychain"/etc. (5
# products, vendor "Women", product_type "JEWELLERY") — the "Keychain"
# leaf added for #49 only went to Men's tree.
check("women's 'Multi-Charm Keychain' resolves Keychain, not stranded", "Multi-Charm Keychain",
      vendor="Women", product_type="JEWELLERY",
      expect_gender="Women", expect_branch="Accessories", expect_leaf="Keychain")
check_leaf_exists("Women", "Accessories", None, "Keychain")

# 52. "SHORT BLOCK HEEL" (Meme) — a low-heeled shoe, "short" describing
# heel height, was matching bare SHORTS_RE with 0 intervening words (same
# collision shape as "Short Coat"/"Short Dress"). Excluded "heel(s)" the
# same way, and added "heel" to the footwear leaf check so it lands on
# Shoes instead of falling through further.
check("'short block heel' is a Shoe, not Shorts", "SHORT BLOCK HEEL",
      vendor="Women", expect_gender="Women", expect_branch="Western",
      expect_sub="Footwear", expect_leaf="Shoes")

# 53. Unisex's Western/Upperwear tree had no "Dress" leaf — classify() can
# emit gender=Unisex (the honest "no gender signal anywhere" fallback)
# independent of whether the garment is a dress. Real example: Lama's
# "PETERPAN DRESS" (vendor "LAMA", no gendered tag/vendor/product_type
# anywhere) was stranding on the bare Western branch node.
check("gender-less 'Peterpan Dress' resolves Dress under Unisex", "PETERPAN DRESS",
      vendor="LAMA", product_type="DRESSES", tags="collection-last-chance",
      expect_gender="Unisex", expect_branch="Western", expect_leaf="Dress")
check_leaf_exists("Unisex", "Western", "Upperwear", "Dress")

# 54. "Spider Man" (two words) collided with bare `\bman\b` in
# GENDER_PATTERNS, and with "men"/"man" checked before "boys"/"girls" in
# the list, the incidental "Man" from the character name won over a real
# product's own explicit "BOYS" signal. Real example: Breakout's "BOYS
# DROP SHOULDER SPIDER MAN PRINTED TEE" (vendor "KIDS", tags include
# "BOYS") was resolving to Men. Reordered boys/girls ahead of men/man —
# no equivalent collision exists for boys/girls.
check("'Spider Man' doesn't override an explicit BOYS signal", "BOYS DROP SHOULDER SPIDER MAN PRINTED TEE",
      vendor="KIDS", product_type="WOVEN", tags="100% Cotton,25-SUM,BOYS,FLAT50,H/S,Kids Top,KNIT,SALE",
      expect_gender="Boys", expect_branch="Western", expect_leaf="T-Shirt")
check("real 'FOR MEN' item still resolves Men, unaffected by the reorder", "BATMAN T-SHIRT FOR MEN",
      vendor="MEME", tags="Batman,Character Shop",
      expect_gender="Men", expect_branch="Western", expect_leaf="T-Shirt")
check("one-word 'Spiderman' never collided in the first place, still Boys", "BOYS SPIDERMAN PRINT SHORTS",
      vendor="KIDS", tags="BOYS", expect_gender="Boys", expect_branch="Western",
      expect_sub="Bottomwear", expect_leaf="Shorts")

# 55/56. Full audit (prompted directly by user feedback that fixes were
# too narrow and testing needed to be more thorough) of everything sitting
# under an Upperwear leaf for two more classes of real "obviously wrong
# branch" bug — perfumes and footwear, 131 + 1,024 real products.
#
# 55. FRAGRANCE_RE was singular-only — plural product_type "FRAGRANCES"
# (Outfitters) / titles that are just scent names with no fragrance word
# at all ("Spiced Rage", user-reported) never matched.
check("plural product_type 'FRAGRANCES' resolves Perfume, not Shirt", "Spiced Rage",
      vendor="Men", product_type="FRAGRANCES", tags="Fragrances,Perfumes",
      expect_branch="Fragrance & Beauty", expect_leaf="Perfume")
check("perfume with a bare scent-name title, no gender word", "AMALFI ORANGE",
      vendor="LAMA", product_type="PERFUMES", expect_gender="Unisex",
      expect_branch="Fragrance & Beauty", expect_leaf="Perfume")

# 56. Footwear detection only ever recognized shoe/sandal/sneaker/heel —
# every other real footwear word in this catalog (boots, pumps, slippers,
# slides, loafers, trainers, mules, khussa, 3 real moccasin misspellings)
# fell through to the generic Shirt/T-Shirt default. Real examples across
# Diners/French Emporio, Lama, Outfitters, ONE (Be-One), Furor, Engine.
check("'Black Formal Shoes For Men' resolves Shoes, not Shirt", "Black Formal Shoes For Men",
      vendor="French Emporio", product_type="Men Shoes",
      expect_gender="Men", expect_branch="Western", expect_sub="Footwear", expect_leaf="Shoes")
check("'AXL BIKER BOOTS' resolves Shoes", "AXL BIKER BOOTS", vendor="LAMA", product_type="BOOTS",
      expect_branch="Western", expect_sub="Footwear", expect_leaf="Shoes")
check("'ANYA MAMA FLATS' (PUMPS product_type) resolves Shoes", "ANYA MAMA FLATS",
      vendor="LAMA", product_type="PUMPS", expect_branch="Western", expect_sub="Footwear", expect_leaf="Shoes")
check("real misspelling 'Mocassins' resolves Shoes", "Black Casual Mocassins Shoes",
      vendor="French Emporio", product_type="Men Shoes",
      expect_branch="Western", expect_sub="Footwear", expect_leaf="Shoes")
check("'Men Loafers' resolves Shoes", "Men Loafers", vendor="ENGINE",
      expect_gender="Men", expect_branch="Western", expect_sub="Footwear", expect_leaf="Shoes")
# Sandal-shaped words route Women specifically to the dedicated Sandals
# leaf (CATEGORY_TREE only defines it for Women); everything else,
# including for Women, still goes to the generic Shoes leaf.
check("women's 'Bejewelled Sandals' resolves the dedicated Sandals leaf", "Bejewelled Sandals",
      vendor="Women", product_type="Sandals",
      expect_gender="Women", expect_branch="Western", expect_sub="Footwear", expect_leaf="Sandals")
check("women's Khussa (traditional sandal) resolves Sandals leaf", "Black Ladies Casual Khussa",
      vendor="French Emporio", product_type="WOMEN SHOES", tags="Women",
      expect_gender="Women", expect_branch="Western", expect_sub="Footwear", expect_leaf="Sandals")
check("men's boots stay on the generic Shoes leaf (no Sandals leaf for Men)", "AXL BIKER BOOTS",
      vendor="Men", product_type="BOOTS",
      expect_gender="Men", expect_branch="Western", expect_sub="Footwear", expect_leaf="Shoes")
# sanity: a real upperwear item with an unrelated "flat" (fabric texture,
# not "ballet flats") must not be caught by the new footwear list.
check("'flat knit' fabric texture is not footwear", "Black Flat Knit Polo",
      vendor="D Man", product_type="T-Shirt", expect_branch="Western", expect_leaf="Polo")
# Unisex's Western tree had no Footwear branch at all — real gender-less
# footwear (Lama's "LEATHER COWBOY BOOTS"/"MADDIE MAMA LOAFERS", vendor
# just the store name) was stranding on the bare Western branch node.
check("gender-less boots resolve Shoes under Unisex", "LEATHER COWBOY BOOTS",
      vendor="LAMA", product_type="BOOTS", expect_gender="Unisex",
      expect_branch="Western", expect_sub="Footwear", expect_leaf="Shoes")
check_leaf_exists("Unisex", "Western", "Footwear", "Shoes")

# 57. Found while auditing the whole catalog (not just Upperwear) for the
# same two bug classes: Cougar's shared product_type bucket "Men Joggers
# Shoes" (5 real products) named both categories at once, and since the
# Joggers check ran before the Footwear check, real shoes with no
# jogger/sweatpant/track-pant word anywhere in their own title ("Mesh
# Lace-Up Trainers", "Suede Mesh Trainers") landed in Joggers. Fixed the
# same way as the Basic Barrel Jeans case: trust the title over a shared
# product_type bucket when they conflict.
check("Cougar's merged 'Men Joggers Shoes' bucket: title wins, resolves Shoes", "Mesh Lace-Up Trainers",
      vendor="COUGAR MEN (S-V3-2026)", product_type="Men Joggers Shoes",
      expect_branch="Western", expect_sub="Footwear", expect_leaf="Shoes")
check("genuine jogger pants whose OWN title says 'Trainers' stays Joggers", "Men Trainers Jogger",
      vendor="ENGINE", product_type="Men",
      expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Joggers")

# 58. ACCESSORY_RE's outer gate was singular-only for belt/cap/wallet/
# cufflink/bracelet/necklace/earring/clutch/watch — even though some of
# these were ALREADY plural-safe in _KEYWORD_LEAVES further down, the
# plural form never got past this gate to reach them. Found by a
# user-requested full audit of the T-Shirt/Shirt leaf across every
# gender (not just the two categories reported before this). Real,
# large-scale: 361 "Belts", 546 "Caps", 156 "Wallets", 752 "Cufflinks",
# 86 "Bracelets", 40 "Necklaces", 230 "Earrings", 25 "Watches",
# 4 "Clutches" — real product lines (Cambridge/Diners/Furor's entire
# "Belts - CBT-4901"-style listings, "CUFFLINKS", "Caps For Men") were
# landing in the generic Shirt default.
check("plural 'Belts' resolves the Belt leaf, not Shirt", "Belts - CBT-4901",
      vendor="Men", product_type="Belts", expect_branch="Accessories", expect_leaf="Belt")
check("plural 'CUFFLINKS' resolves Cufflink, not Shirt", "CUFFLINKS",
      vendor="Men", product_type="CUFF LINKS", expect_branch="Accessories", expect_leaf="Cufflink")
check("plural 'Caps For Men' resolves Cap, not Shirt", "Caps For Men",
      vendor="Men", product_type="Accessories", expect_branch="Accessories", expect_leaf="Cap")
check("plural 'Watches' resolves Watch, not Shirt", "Analog Watches Collection",
      vendor="Men", product_type="Watches", expect_branch="Accessories", expect_leaf="Watch")
# "hat"/"beanie" fold into the same Cap leaf (no separate Hat leaf exists)
check("'Boonie Hat' resolves the Cap leaf", "Boonie Hat - FAH21-001",
      vendor="Men", product_type="Men Caps", expect_branch="Accessories", expect_leaf="Cap")
check("'Ribbed Beanie' resolves the Cap leaf", "Ribbed Beanie",
      vendor="Boys", product_type="CAPS & HATS", expect_gender="Boys",
      expect_branch="Accessories", expect_leaf="Cap")
# "bracelet"/"necklace"/"earring" fold into the same Jewelry leaf
check("'Gold Bracelet' resolves Jewelry, not Shirt", "Gold Bracelet",
      vendor="Women", product_type="Jewellery", expect_branch="Accessories", expect_leaf="Jewelry")
check("'Crystal Earrings' resolves Jewelry", "Crystal Earrings",
      vendor="Women", product_type="Jewellery", expect_branch="Accessories", expect_leaf="Jewelry")

# 59. Found while finishing the Jeans-leaf audit: ONE (Be-One)'s "String
# Sports Shoes" has product_type literally "Jeans" (a store mislabel —
# tags say "Girls Footwear"/"KIDS_FOOTWEAR") and was resolving to Jeans
# because that check runs before the footwear one. Same "title beats a
# conflicting product_type" fix as Basic Barrel Jeans (#45d), applied in
# the other direction (footwear over bottomwear this time).
check("product_type mislabeled 'Jeans' loses to a title that says Shoes", "String Sports Shoes",
      vendor="Girls", product_type="Jeans", tags="Girls Footwear,KIDS_FOOTWEAR",
      expect_gender="Girls", expect_branch="Western", expect_sub="Footwear", expect_leaf="Shoes")
check("'Boot Cut Jeans' (a real fit descriptor) still resolves Jeans", "Relaxed Boot Cut Jeans",
      vendor="Men", product_type="Jeans", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Jeans")

# 60. GARMENT_DETAIL_RE ("with...belt/tie" = a design detail on another
# garment, not a standalone accessory) was unconditional — Equator's
# "Black With Brown Contrast Leather Belt" (tags explicitly "Accessories"/
# "BELT") is a genuine standalone belt describing its OWN two-tone color
# ("black, with brown contrast"), not a garment with a belt detail, and
# had no garment noun anywhere in its title. Stripping "with...belt" from
# it left nothing for ACCESSORY_RE to match, so it fell to the generic
# Shirt default. Fixed: only strip when a real garment noun (shirt/top/
# dress/jeans/etc.) is also present in the same text — every genuine
# "with...belt/tie" garment-detail example already names its garment.
check("belt describing its own color ('With Brown...') is a real Belt, not stripped", "Black With Brown Contrast Leather Belt",
      vendor="Equator", tags="Accessories,BELT", expect_branch="Accessories", expect_leaf="Belt")
check("genuine 'Jeans With Belt Detail' still excluded, stays Jeans", "Barrel Fit Jeans With Belt Detail",
      vendor="Women", product_type="Jeans", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Jeans")
check("genuine 'Dress With Waist Belt' still excluded, stays Dress", "Long Dress With  Waist Belt",
      vendor="Women", product_type="Dress", expect_branch="Western", expect_leaf="Dress")

# 61-62. Full catalog-wide leaf-cross-check (every leaf against every
# other leaf's signal words) found two more real bugs among a lot of
# noise (most hits were false positives — combo-naming that classify()
# already resolves correctly via its priority order, e.g. "Kurta
# Trouser" correctly staying Kurta via the Eastern-branch check that
# runs before Bottomwear is ever considered — each candidate was
# verified against classify() itself before being treated as a bug).
#
# 61. `\btee\b` (T-Shirt leaf trigger) was singular-only — 906 real
# products (ONE Be-One's/Diners' entire product_type: "Tees" line, "Net
# Top Yellow", "Soccer Ball Print Tees") fell to the generic Shirt
# default.
check("plural product_type 'Tees' resolves T-Shirt, not Shirt", "Net Top Yellow",
      vendor="Unisex", product_type="Tees", expect_branch="Western", expect_leaf="T-Shirt")
check("plural 'Tees' in the title resolves T-Shirt", "Soccer Ball Print Tees",
      vendor="Boys", product_type="Boys T-Shirts", expect_gender="Boys",
      expect_branch="Western", expect_leaf="T-Shirt")
# 62. "Paper bag"/"paperbag" is a bottomwear FIT STYLE (a waist
# silhouette), not an actual bag — 23 real products (Outfitters' "High-
# Waist Paper Bag Jeans", Meme's "PAPER BAG DENIM JEANS FOR GIRLS",
# Charcoal's "LINEN PAPERBAG PANTS") were resolving to the Bag accessory
# leaf, since that check runs before Bottomwear.
check("'Paper Bag Fit Jeans' resolves Jeans, not Bag", "Paper Bag Fit Jeans",
      vendor="Women", product_type="JEANS", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Jeans")
check("one-word 'Paperbag Pants' resolves Trouser, not Bag", "LINEN PAPERBAG PANTS",
      vendor="Women", product_type="PANTS", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Trouser")
check("real handbag is unaffected by the paper-bag exclusion", "Leather Handbag",
      vendor="Women", product_type="Bags", expect_branch="Accessories", expect_leaf="Bag")

# 63. "jorts" (an unambiguous portmanteau for jean shorts) wasn't
# recognized at all — real examples "Baggy Denim jorts"/"Denim Bermuda
# Jorts" have no literal "short(s)" word, and the bare "denim" they do
# have defaults to Jeans via the title-first bottomwear check, never
# reaching a correct product_type "SHORTS" fallback.
check("'jorts' resolves Shorts even with no literal 'short' word", "Baggy Denim jorts",
      vendor="Unisex", product_type="Shorts", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Shorts")
check("'Denim Bermuda Jorts' resolves Shorts, not Jeans", "Denim Bermuda Jorts",
      vendor="Unisex", product_type="SHORTS", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Shorts")

# 64. A footwear word immediately followed by an Upperwear garment noun
# is a themed PRINT on that garment, not an actual shoe — real example,
# Cougar's "Flip Flops T-Shirt" (a t-shirt with a flip-flops print, same
# naming pattern as "Spider Man Printed Tee"), was resolving to Shoes.
check("'Flip Flops T-Shirt' is a T-Shirt, not footwear", "Flip Flops T-Shirt",
      vendor="COUGAR WOMEN", expect_branch="Western", expect_leaf="T-Shirt")
check("real khussa sandals unaffected by the flip-flops-print exclusion", "Black Ladies Casual Khussa",
      vendor="Women", product_type="WOMEN SHOES", expect_branch="Western", expect_sub="Footwear", expect_leaf="Sandals")

# 65. product_type mislabeled "Jeans" losing to a title that unambiguously
# says Jacket — same pattern as String Sports Shoes (#59), applied to
# Jacket instead of Footwear. Real example: ONE (Be-One)'s "Basic Denim
# Jacket".
check("product_type mislabeled 'Jeans' loses to a title that says Jacket", "Basic Denim Jacket",
      vendor="Unisex", product_type="Jeans", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Jacket")
check("real denim jacket (no product_type conflict) still resolves Jacket", "Denim Jacket",
      vendor="Men", product_type="Men", expect_branch="Western", expect_leaf="Jacket")

# 66. The final Upperwear leaf ternary checked a MERGED product_type+
# title blob against a fixed priority order (T-Shirt before Sweatshirt),
# so a coarser product_type bucket could outrank the title's own, more
# specific word. Real example: Outfitters' "Character Graphic Sweatshirt"
# has product_type "TEES" — the title explicitly says "Sweatshirt", but
# "tee" (from product_type) was checked first in the priority list and
# won. Fixed the same way as every other leaf resolution this session:
# title alone is checked first, full blob (product_type included) only
# as a fallback.
check("title's own 'Sweatshirt' wins over product_type 'TEES'", "Character Graphic Sweatshirt",
      vendor="Unisex", product_type="TEES", expect_branch="Western", expect_leaf="Sweatshirt")

# 2026-08-29 — 14th pass, prompted by the user finding real tank tops/
# pocket squares/vests in the live Men's Shirt listing while testing outside
# the AI search. Four parallel category-by-category audits (every leaf
# currently in use, checked against every OTHER leaf family's own regex)
# confirmed several thousand more real products sharing the same root
# cause: "Shirt" is the Western branch's silent catch-all, and any garment
# type classify() has no keyword for lands there by default.

# 67. Pocket Square had no leaf/keyword at all — 323 real Men's, 7 Unisex.
check("'Pocket Square' is an accessory, not a Shirt", "100% Silk Pocket Square",
      product_type="simple", vendor="Uniworth", expect_branch="Accessories", expect_leaf="Pocket Square")

# 68. Tank Top had no leaf/keyword at all — 476 real products across
# Men/Women/Boys/Girls. Furor's own product_type is literally "Men Tank
# Tops" and still resolved to Shirt.
check("Furor's own product_type 'Men Tank Tops' resolves Tank Top", "All-Over Print Tank Top - FMTT18-002",
      product_type="Men Tank Tops", vendor="Furor", expect_branch="Western", expect_leaf="Tank Top")
check("bare 'sando' (a real undergarment word, distinct from a Tank Top) is NOT pulled into Tank Top", "Navy Sando",
      vendor="Men", expect_branch="Western", expect_leaf="Shirt")

# 69. Scarf/Muffler/Stole had no leaf/keyword at all — ~731 real products,
# mostly Men/Women. A standalone Dupatta/Duppatta was falling even further
# wrong, into Shalwar Kameez (EASTERN_RE's own silent final-else fallback),
# since "dupatta" is itself one of EASTERN_RE's trigger words.
check("'Scarf' is an accessory, not a Shirt", "Aqua Wool Scarf",
      product_type="SCARVES", vendor="Men", expect_branch="Accessories", expect_leaf="Scarf")
check("'Muffler' folds into the same Scarf leaf", "Men Muffler",
      product_type="Men Mufflers", vendor="Men", expect_branch="Accessories", expect_leaf="Scarf")
check("standalone 'Dupatta' is a Scarf, not Shalwar Kameez", "Printed Dupatta",
      product_type="Stoles/Dupatta", vendor="Diners", expect_branch="Accessories", expect_leaf="Scarf")
check("'Duppatta' misspelling still resolves Scarf", "Dyed Duppatta",
      product_type="Stoles/Dupatta", vendor="Diners", expect_branch="Accessories", expect_leaf="Scarf")
check("a dupatta bundled into a real kurta ensemble still resolves Eastern", "Kurta With Dupatta",
      vendor="Women", expect_branch="Eastern", expect_leaf="Kurta")

# 70. Outerwear vests (quilted/padded/sherpa) had no leaf of their own
# once ruled out as underwear — ~60 real products were falling to Shirt
# instead of their own Vest leaf (folded into Jacket until 2026-09-01 —
# see CATEGORY_TREE's own comment on the Vest leaf). "Active Wear Vest"
# itself moved to the Tank Top test below on 2026-09-01 (see
# ACTIVEWEAR_VEST_SIGNAL_RE's own comment) — a real activewear vest
# resolves Tank Top now, not Vest.
check("a plain outerwear 'Vest' resolves its own Vest leaf, not Shirt", "Suede Padded Vest",
      product_type="Men Jackets", vendor="Cambridge", expect_branch="Western", expect_leaf="Vest")
check("a real Sweater Vest still resolves Sweater ahead of the Vest fallback", "Cougar Sweater Vest",
      vendor="Cougar Women", expect_branch="Western", expect_leaf="Sweater")
check("a real underwear vest (sando signal) still resolves Underwear, unaffected", "Sporty Vest",
      product_type="Undergarment", vendor="Uniworth", description="our sporty undergarment will keep you cool",
      expect_branch="Accessories", expect_leaf="Underwear")
# User-reported (browsing Men's Vest after the leaf above shipped): "the
# men vests look very diverse... vest sweater and jackets" — read every
# one of the 130 real Men's Vest products before concluding what was
# actually wrong: a genuine second garment class, sleeveless ATHLETIC
# tops, was hiding in the same leaf as Cambridge's real quilted puffer
# vests and Uniworth's formal Western waistcoats. Real examples,
# descriptions verified before trusting the title: One (Be-One)'s "Gym
# Vest" ("Gym vest in dry fit fabrication"), Equator's "Training Vest"
# ("from our Activewear collection...wicks moisture...workouts"), Engine
# Clothing's "Active Wear Vest" ("activewear vest...Lycra Poly
# Jersey...workouts, training"). These are the same real garment this
# catalog already calls "Tank Top" for every other brand, not an
# outerwear layer — routed there instead of the plain Vest leaf.
check("a 'Gym Vest' resolves Tank Top, not the outerwear Vest leaf", "Regular Fit Gym Vest",
      vendor="One (Be-One)", description="Regular fit sleeveless vest in textured dry fit fabrication, featuring crew neck",
      expect_branch="Western", expect_leaf="Tank Top")
check("a 'Training Vest' resolves Tank Top too", "Grey Training Vest",
      vendor="Equator", description="This training vest from our Activewear collection is made with ultimate comfort in mind.",
      expect_branch="Western", expect_leaf="Tank Top")
check("'Active Wear Vest' resolves Tank Top, not Vest", "Men Active Wear Vest",
      product_type="Men", vendor="Engine Clothing", expect_branch="Western", expect_leaf="Tank Top")
check("a 'Sports Vest' resolves Tank Top too", "Boys Panel Sports Vest",
      vendor="Engine Clothing", expect_gender="Boys", expect_branch="Western", expect_leaf="Tank Top")

# 71. Diners' bare piece-count ("2PC"/"3PC") and "combo" naming for a
# coordinated Western set, with no "suit"/"co-ord" word at all — real
# body_html confirms these are genuine "ready-to-wear 2-piece set"/"Top
# Bottom Set" listings, not Eastern ensembles. ~970 real products across
# Women/Girls/Boys/Teens/Infant sub-lines were falling to Shirt.
check("bare '2PC' resolves Co-ord Set", "Printed 2PC",
      product_type="2 Piece Stitched", vendor="Diners", expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Co-ord Set")
check("'Boys Combo' resolves Co-ord Set", "Graphic Printed Boys Combos",
      product_type="Boys Combo", vendor="Diners", expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Co-ord Set")
check("bare '3-Piece...Set' resolves Co-ord Set even with a T-Shirt-mislabeled product_type", "Boys 3-Piece Suiting Set in Fawn",
      product_type="Boys T-Shirts", vendor="Diners", expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Co-ord Set")
check("'Combo' immediately before a garment noun is a COLOR combo, not a set", "Green & Black Combo Hoodie",
      vendor="Unisex", expect_branch="Western", expect_leaf="Hoodie")
check("a real jacket SKU suffix ('-2P', no C) is NOT mistaken for a piece-count", "Varsity Jacket - EBTJP5-001-2P",
      product_type="Boys Jackets", vendor="Edenrobe", expect_branch="Western", expect_leaf="Jacket")
check("a real Trouser with '(2 PC)' in its own title still resolves Trouser, not Co-ord Set", "SHARP (2 PC) TROUSER - BLACK",
      vendor="Cambridge", expect_branch="Western", expect_leaf="Trouser")

# 72. Edenrobe's stitched "Shirt Trouser" 2-piece sets (399 real products)
# had no Eastern word anywhere in the title — real body_html confirms
# "Girls' Pret Kurti & Trouser". The UNSTITCHED version of the same title
# pattern (670 real products) already resolved correctly via UNSTITCHED_RE
# independently.
check("stitched 'Shirt Trouser' resolves Kurta Set via product_type-confirmed Eastern naming", "Printed Cambric Shirt Trouser - EGTKP23-70343ST",
      product_type="Girls Eastern", vendor="Edenrobe", expect_branch="Eastern", expect_leaf="Kurta Set")
check("the unstitched version of the same title pattern is unaffected, still 2-Piece", "Printed Khaddar Shirt Trouser - EWU5A3-36000ST",
      product_type="Woman Un Stitched Allure Khaddar", vendor="Edenrobe", expect_branch="Eastern", expect_sub="Unstitched", expect_leaf="2-Piece")

# 73. Zellbury's "Top" leaf existed in CATEGORY_TREE for Women/Girls but no
# rule ever emitted it — 538 real Women's "Tunic" products were falling to
# Shirt instead.
check("'Tunic' resolves the previously-dead 'Top' leaf for Women", "Tunics - 2820",
      product_type="Essential Pret", vendor="ZELLBURY WOMEN", expect_branch="Western", expect_leaf="Top")

# 74. Zellbury's "Chino" line had no keyword at all — 84 real products
# (Zellbury's own "Signature Chino" naming) were falling to Shirt.
check("'Chino' resolves Trouser", "Signature Chino - S003",
      vendor="Zellbury", expect_branch="Western", expect_leaf="Trouser")

# 75. Outfitters'/Breakout's own mislabeled product_type ("WALLETS"/
# "WALLET") was outranking a title that unambiguously says backpack/clutch
# — same title-vs-product_type conflict class as String Sports Shoes (#59)
# and Basic Denim Jacket (#65).
check("title 'Backpack' wins over mislabeled product_type 'WALLETS'", "Multi-Functional Backpack",
      product_type="WALLETS", vendor="Men", expect_branch="Accessories", expect_leaf="Bag")
check("title 'Clutch' wins over mislabeled product_type 'WALLET'", "CROCHET CLUTCH",
      product_type="WALLET", vendor="Women", expect_branch="Accessories", expect_leaf="Bag")

check_leaf_exists("Men", "Western", "Upperwear", "Tank Top")
check_leaf_exists("Women", "Western", "Upperwear", "Tank Top")
check_leaf_exists("Boys", "Western", "Upperwear", "Tank Top")
check_leaf_exists("Girls", "Western", "Upperwear", "Tank Top")
check_leaf_exists("Men", "Accessories", None, "Scarf")
check_leaf_exists("Men", "Accessories", None, "Pocket Square")
check_leaf_exists("Women", "Accessories", None, "Scarf")
check_leaf_exists("Women", "Accessories", None, "Pocket Square")
check_leaf_exists("Women", "Western", "Upperwear", "Top")

# 76. "Cargo" was splitting across Trouser/Jeans/Shirt depending on
# incidental wording — real Jeans/Trousers with a totally different
# silhouette ranking alongside genuine cargo pants in AI search. 443 real
# products across Men/Women/Boys/Girls/Unisex consolidated into one leaf.
check("bare 'Cargo' with no other bottomwear word still resolves Cargo Trouser", "TWILL CARGO",
      product_type="Relaxed Fit", vendor="Men", expect_branch="Western", expect_leaf="Cargo Trouser")
check("a real title typo ('Touser') still resolves via bare 'cargo'", "Men Cargo Touser",
      vendor="Men", expect_branch="Western", expect_leaf="Cargo Trouser")
check("'Denim Cargo Trouser' resolves Cargo Trouser, not Jeans (bare-denim no longer wins)", "Denim Cargo Trouser - EBBT22-010",
      product_type="Boys Trousers", vendor="Boys", expect_branch="Western", expect_leaf="Cargo Trouser")
check("'Cargo Fit Jeans' resolves Cargo Trouser too — same real silhouette regardless of fabric name", "Cargo Fit Jeans",
      product_type="JEANS", vendor="Men", expect_branch="Western", expect_leaf="Cargo Trouser")
check("'Cargo Shorts' is untouched — stays Shorts, not pulled into Cargo Trouser", "Boys Cargo Shorts",
      vendor="Boys", expect_branch="Western", expect_leaf="Shorts")
check("'Cargo Joggers' is untouched — stays Joggers, not pulled into Cargo Trouser", "Cargo Joggers",
      vendor="Men", expect_branch="Western", expect_leaf="Joggers")
check("a plain 'Trouser' with no cargo word is unaffected", "Men Formal Trouser",
      vendor="Men", expect_branch="Western", expect_leaf="Trouser")
check_leaf_exists("Men", "Western", "Bottomwear", "Cargo Trouser")
check_leaf_exists("Women", "Western", "Bottomwear", "Cargo Trouser")
check_leaf_exists("Boys", "Western", "Bottomwear", "Cargo Trouser")
check_leaf_exists("Girls", "Western", "Bottomwear", "Cargo Trouser")
check_leaf_exists("Unisex", "Western", "Bottomwear", "Cargo Trouser")


# --- Co-ord Set audit (2026-08-30) ---------------------------------------
# The regex precedence bug: `\bco-?ord|suit\b` parsed as `(\bco-?ord)|(suit\b)`,
# so bare "suit" matched as a suffix inside ANY word — jumpsuit/playsuit/
# bodysuit were all wrongly landing in Co-ord Set.
check("jumpsuit is its own leaf, not Co-ord Set", "Ruffled Jumpsuit",
      product_type="Girls Jumpsuits", vendor="Girls",
      expect_gender="Girls", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Jumpsuit")
check("playsuit is its own leaf, not Co-ord Set", "Floral Playsuit",
      vendor="Women", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Jumpsuit")
check("bodysuit is its own leaf, not Co-ord Set", "Ribbed Bodysuit",
      vendor="Women", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Jumpsuit")
check_leaf_exists("Women", "Western", "Upperwear", "Jumpsuit")
check_leaf_exists("Girls", "Western", "Upperwear", "Jumpsuit")
check_leaf_exists("Boys", "Western", "Upperwear", "Jumpsuit")
# Real compounds that legitimately ARE 2-piece sets must still resolve
# under Suits & Sets after the boundary fix — verified catalog-wide as the
# complete real compound-word list (pantsuit has zero real occurrences
# but is kept as a defensive allow anyway). Tracksuit gets its own leaf
# (added 2026-08-30, see CATEGORY_TREE comment) rather than Co-ord Set.
check("tracksuit is its own leaf, not Co-ord Set", "Men Tracksuit", vendor="Men",
      expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Tracksuit")
check("pantsuit is still Co-ord Set (defensive, no real catalog matches)", "Women Pantsuit",
      vendor="Women", expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Co-ord Set")
check("nightsuit is still Co-ord Set", "Tee Pajama Nightsuit", vendor="Women",
      expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Co-ord Set")

# Cougar's own `productType: "2PC"` bucket wrongly pulled single tops (no
# matching bottom at all) into Co-ord Set purely because product_type said
# "2PC" — the title never does. Piece-count is now title-only.
check("product_type-only '2PC' (Cougar) no longer forces Co-ord Set on a plain top", "Ribbed Knit Top",
      product_type="2PC", vendor="Women", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Shirt")
check("a real title-stated piece count still resolves Co-ord Set (Diners)", "Printed 2PC",
      product_type="Girls 2 Piece", vendor="Girls",
      expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Co-ord Set")

# Cambridge: tags alone reveal a "Suit"-titled item is really a Shalwar
# Kameez — classify() never used to read tags/description at all.
check("Cambridge tags reveal a real Shalwar Kameez under a 'Suit' title", "Cream Dobby Texture Suit",
      tags="2023,Blended,Designer Shalwar Kameez,Mashriq,RTW,Sale,Summer", vendor="Women",
      expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Shalwar Kameez")
# Equator: description alone reveals a "Suit"-titled item is really a kurta
# ensemble from their own Qaftaan collection.
check("Equator description reveals a real kurta ensemble under a 'Suit' title", "French Grey Suit",
      tags="Kurta Trouser,Qaftaan", vendor="Women",
      description="This two-piece suit from our Qaftaan collection will ensure your comfort and style. "
                   "It includes a kurta featuring a band collar with a button placket and cuff sleeves.",
      expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Kurta")
# Zellbury: description alone reveals a "Suit"-titled item is UNSTITCHED
# fabric, not a ready-to-wear Western set.
check("Zellbury description reveals real unstitched fabric under a 'Suit' title", "Marvel - Wash & Wear Suit - 2526",
      product_type="Blended Collection", vendor="Men",
      description="4.25 meter Men Unstitched Shalwar Kameez Fabric",
      expect_branch="Eastern", expect_sub="Unstitched", expect_leaf="Suit")
# Zellbury/Cougar: sharara/gharara/lehenga/kalidar/pishwas are their own
# Eastern vocabulary now, resolving to Kurta Set (not the generic Shalwar
# Kameez default, and not Western Co-ord Set).
check("Gharara Suit resolves Eastern Kurta Set, not Western Co-ord Set", "Embroidered Gharara Suit - 1512",
      vendor="Women", expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Kurta Set")
check("Jamawar Sharara Set resolves Eastern Kurta Set", "Jamawar Sharara Set",
      vendor="Women", expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Kurta Set")
check("a stray 'Girls Gharara Set' outside Co-ord Set is also caught", "Girls Gharara Set",
      vendor="Girls", expect_gender="Girls", expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Kurta Set")

# Edenrobe's/Cambridge's real structural convention for a stitched
# shirt/frock + trouser/shalwar 2-piece set, labeled with "Fit Type:" per
# piece — needed because these titles just say "Co-Ord Set", with no
# Eastern word anywhere for EASTERN_RE to catch directly.
check("Edenrobe structured Shirt+Trouser description resolves Kurta Set", "Printed Raw Silk Co-Ord Set - EGTKP6-74006ST",
      vendor="Women",
      description="Shirt Fit Type: Straight Fit Fabric: Raw Silk Style: Floral Printed Shirt with Lace Detailing "
                   "Shalwar Fit Type: Straight Fit Fabric: Raw Silk Style: Printed Shalwar with Lace Detailing",
      expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Kurta Set")
check("the 'Frock' variant of the same structured convention also resolves Kurta Set", "Girls Co-Ord Set",
      vendor="Girls",
      description="Frock Fit Type: Relaxed Fit Fabric: Lawn Style: Printed Frock "
                   "Trouser Fit Type: Relaxed Fit Fabric: Lawn Style: Plain Trouser",
      expect_gender="Girls", expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Kurta Set")
# A real Edenrobe 3-piece variant of the same convention (adds a Dupatta)
# resolves Kurta Set too, not just the bare 2-piece case.
check("a Gharara Suit with the structured convention still resolves via its own word first", "Embroidered Organza Gharara Suit - EGTPLED5-50058-3P",
      vendor="Women",
      description="Shirt Fit Type: Straight Fit Fabric: Organza Style: Embroidered Shirt "
                   "Gharara Fit Type: Straight Fit Fabric: Organza Style: Banarsi Work Gharara "
                   "Dupatta Fabric: Organza Type: Embellished Dupatta with Lace Work",
      expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Kurta Set")

# A "Prince Suit"/"Prince Coat" is a short embroidered Eastern formal coat
# (Sherwani-adjacent), not a Western jacket — scoped to items that already
# look like a coordinated set (a standalone "Prince Coat" with no set
# signal is a separate, out-of-scope case, deliberately left as Jacket).
check("'Boys Prince Suit' resolves Eastern Sherwani, not Western Co-ord Set", "Grey Boys Prince Suit",
      vendor="Boys", expect_gender="Boys", expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Sherwani")
check("a standalone 'Prince Coat' (no set signal) is untouched, stays Jacket", "Embroidered Karandi Prince Coat",
      product_type="Jacket", vendor="Men", expect_branch="Western", expect_leaf="Jacket")

# Regression guards: the broadened tags/description signal must NOT
# reclassify genuine WESTERN suits/sets just because of an incidental word.
check("a real Western 3-piece suit stays Western (not Eastern) despite 'waistcoat' in its own description, "
      "and now resolves its own Formal Suit leaf rather than Co-ord Set", "Light Grey Three Piece Suit",
      vendor="Men",
      description="Build your power outfit wardrobe with this suit for formal gatherings. Featuring a "
                   "single-breasted jacket, notch lapels, two-button fastening. The straight trousers have "
                   "classic loops for the belt, finished with a shawl lapel waistcoat featuring four-button detail.",
      expect_branch="Western", expect_sub="Formalwear", expect_leaf="Formal Suit")
# The same description's "waistcoat" must NOT push a Women's version of
# this into Formal Suit — a handful of real Women's "Suit"/"Blazer Co-ord
# Set" titles use identical tailoring words but are genuinely casual
# separates (Engine Clothing, Meme), verified via their own real
# descriptions ("...perfect for casual outings, travel, everyday wear").
check("the identical formal-suit description does NOT apply to Women — stays Co-ord Set", "Light Grey Three Piece Suit",
      vendor="Women",
      description="Build your power outfit wardrobe with this suit for formal gatherings. Featuring a "
                   "single-breasted jacket, notch lapels, two-button fastening. The straight trousers have "
                   "classic loops for the belt, finished with a shawl lapel waistcoat featuring four-button detail.",
      expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Co-ord Set")
check("Furor's Western resort Co-ord Set Shirt stays Co-ord Set despite 2 loose 'fabric' mentions", "Crochet Resort Co-Ord Set Shirt - FMTCS6-105",
      tags="Co-Ord_Set,Men,Men_Tops,Shirt_Set", vendor="Men",
      description="Men's Co-ord Set Shirt Relaxed Fit Crochet Fabric. Relaxed Fit Co-ord Set Shirt Crafted "
                   "from Soft, Breathable Crochet Fabric. Best Worn with Its Matching Trousers for a Complete "
                   "Resort Look.",
      expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Co-ord Set")

# Formal Suit / Tracksuit split (2026-08-30) — a tailored Western 2/3-piece
# business suit and an athletic tracksuit are both a different product
# from a casual matching Co-ord Set.
check("a plain '2 Piece Suit' title with formal signal in description resolves Formal Suit (Boys)", "Boys Navy Blue Double-Breasted Suit Set",
      vendor="Boys", expect_gender="Boys", expect_branch="Western", expect_sub="Formalwear", expect_leaf="Formal Suit")
check("a bare 'Suit' title with tuxedo in description resolves Formal Suit", "Formal Suit - EMTCPC20-6697",
      vendor="Men", description="Notch Collar Tuxedo Suit, single-breasted, comes with a matching waistcoat.",
      expect_branch="Western", expect_sub="Formalwear", expect_leaf="Formal Suit")
check("a plain co-ord set with no formal signal at all still resolves Co-ord Set (Men)", "Men Co-ord Set",
      vendor="Men", expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Co-ord Set")
check_leaf_exists("Men", "Western", "Formalwear", "Formal Suit")
check_leaf_exists("Boys", "Western", "Formalwear", "Formal Suit")
check_leaf_exists("Men", "Western", "Suits & Sets", "Tracksuit")
check_leaf_exists("Women", "Western", "Suits & Sets", "Tracksuit")
check_leaf_exists("Girls", "Western", "Suits & Sets", "Tracksuit")

# Furor's "Tracksuit <single garment>" collection-naming pattern (2026-08-30)
# — "Tracksuit" describes the LINE, not the product; the actual garment
# noun that follows is what the product really is.
check("'Tracksuit Sweatshirt' is a Sweatshirt, not Tracksuit", "Quarter-Zip Tracksuit Sweatshirt - FMTTKS24-012",
      product_type="Men Sweatshirts", vendor="Men",
      expect_branch="Western", expect_sub="Upperwear", expect_leaf="Sweatshirt")
check("'Tracksuit Zipper Jacket' is a Jacket, not Tracksuit", "Mock Neck Tracksuit Zipper Jacket - FMTTKS24-003",
      product_type="Men Jackets", vendor="Men",
      expect_branch="Western", expect_sub="Upperwear", expect_leaf="Jacket")
check("'Tracksuit Pullover Hoodie' is a Hoodie, not Tracksuit", "Tracksuit Pullover Hoodie - FMTTKS5-006",
      product_type="Men Hoodies", vendor="Men",
      expect_branch="Western", expect_sub="Upperwear", expect_leaf="Hoodie")
check("a genuine 2-piece tracksuit SET (garment word BEFORE 'Tracksuit') still resolves Tracksuit", "Hoodie Tracksuit - FWTCSK24-005",
      product_type="Woman Track Suit", vendor="Women",
      expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Tracksuit")
check("a bare 'Tracksuit' with nothing following it still resolves Tracksuit", "Everyday Gents Tracksuit",
      vendor="Men", expect_branch="Western", expect_sub="Suits & Sets", expect_leaf="Tracksuit")

# A Western fashion waistcoat/vest is not the same product as a real
# Eastern koti (2026-08-30 user report), and — as of 2026-09-01 — resolves
# its own Vest leaf rather than Jacket, since a waistcoat IS a vest, just
# a different regional word for the identical sleeveless garment.
check("Outfitters' faux leather waistcoat is Western Vest, not Eastern Waistcoat", "Faux Leather Cropped Waistcoat",
      product_type="OUTERWEAR", tags="Jackets,Outerwear,vest,waist coat", vendor="Women",
      description="The name says it all the right size slightly snugs the body leaving enough room for "
                   "comfort in the sleeves and waist. PU Machine wash.",
      expect_branch="Western", expect_sub="Upperwear", expect_leaf="Vest")
check("Uniworth's own 'Western Waistcoat' line resolves Western Vest", "Charcoal Check Western Waistcoat",
      vendor="Men", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Vest")
check("a denim waistcoat resolves Western Vest", "Waistcoat Denim Blue",
      vendor="Men", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Vest")
# Regression guard: a "blazer"-worded STYLE DETAIL on a genuinely Eastern
# kurta pajama ensemble must NOT get pulled into Western — real false
# positive caught during verification (Edenrobe's "Cotton Waistcoat Suit").
check("a 'blazer collar' detail on a real kurta pajama waistcoat stays Eastern", "Cotton Waistcoat Suit - EMTCS20-99011",
      product_type="Men Waist Coat Suit", vendor="Men",
      description="Men's Waistcoat Suit Blazer Suiting Fabric Cotton Satin Kurta Pajama Contrast Blazer "
                   "Collar Fancy Buttons Decorative Chain & Brooch.",
      expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Waistcoat")
check("a plain Eastern koti waistcoat with no Western signal at all stays Eastern", "Waistcoat - ELTWC19-66953",
      product_type="Woman Waist Coat", vendor="Women",
      description="Fabric: Lawn stylized printed koti with pockets and accent lining",
      expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Waistcoat")
check("a Boys waistcoat paired with Kameez Shalwar stays Eastern despite generic wording", "Boys Kameez Shalwar with waistcoat",
      vendor="Boys", expect_gender="Boys", expect_branch="Eastern", expect_sub="Stitched", expect_leaf="Waistcoat")

# --- Bandana.pk onboarding audit (2026-08-31) ---------------------------
# "bra"/"camisole" had no keyword anywhere — 40 real products across
# OTHER brands too (not just Bandana) were scattered across Shirt/Tank
# Top/T-Shirt/Co-ord Set/Joggers instead of Underwear.
check("Sports Bra resolves Underwear, not Tank Top", "White Glide-Fit Sports Bra",
      vendor="Women", expect_branch="Accessories", expect_leaf="Underwear")
check("'Jogger Bra' resolves Underwear, not Joggers", "Jogger Bra",
      vendor="Women", expect_branch="Accessories", expect_leaf="Underwear")
check("a bare Camisole resolves Underwear", "Reversible Camisole",
      vendor="Women", expect_branch="Accessories", expect_leaf="Underwear")
check("'bra' doesn't false-match inside 'bralette' boundary check", "Cobra Print Shirt",
      vendor="Men", expect_branch="Western", expect_leaf="Shirt")
# "gilet"/"bodywarmer" fold into the Vest leaf (Jacket until 2026-09-01 —
# see CATEGORY_TREE's own comment) — 67 real EXISTING products across
# other brands (Furor's "Puffer Gilet", "Yellow Down Gilet") had no
# jacket/vest/coat word and were falling to Shirt/Hoodie.
check("a bare 'Gilet' with no other outerwear word resolves Vest", "Yellow Down Gilet",
      vendor="Men", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Vest")
check("'Bodywarmer' resolves Vest too", "Quilted Bodywarmer",
      vendor="Women", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Vest")
# "Skirt" never had a leaf or keyword — 95 real EXISTING products across
# other brands (Co-ord Set/Jeans/Shirt/Shorts/Trouser) had nowhere
# correct to land.
check("a bare 'Skirt' resolves its own leaf, not Shirt/Jeans/Shorts", "WILDFLOWER TIER SKIRT",
      vendor="Women", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Skirt")
check("'Denim Skirt' resolves Skirt, not Jeans", "Denim Skirt With Front Slit",
      vendor="Women", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Skirt")
check_leaf_exists("Women", "Western", "Bottomwear", "Skirt")
check_leaf_exists("Girls", "Western", "Bottomwear", "Skirt")
# Bandana's "Denim Terry" fabric-line name means terry cloth with a
# denim-look print, NOT real denim — its own description says so
# explicitly. A bare "Denim Terry Pants" title would otherwise wrongly
# resolve Jeans off the bare word "denim".
check("'Denim Terry Pants' resolves Trouser, not Jeans", "Men's Denim Terry Pants",
      vendor="Men", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Trouser")
check("a real denim item elsewhere (no 'terry') still resolves Jeans", "Men's Denim Pants",
      vendor="Men", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Jeans")
# Bandana's "RUH" capsule line is genuinely unisex — the same product ID
# appears in both the ruh-men and ruh-women collections, tagged "RUH Men"
# AND "RUH Women" simultaneously, with the description literally saying
# "UNISEX".
check("RUH's dual-gender tags + explicit 'UNISEX' description resolve Unisex, not Women", "Eclipse Sweatshirt",
      vendor="Bandana", tags="RUH, RUH Men, RUH Men Tops, RUH Women, RUH Women Tops",
      description="UNISEX. Musa is 6'1\" & wears size M. Maria is 5'4\" & wears size XS. Oversized silhouette.",
      expect_gender="Unisex", expect_branch="Western", expect_sub="Upperwear", expect_leaf="Sweatshirt")
check("a normal Women's product with 'unisex' nowhere in its own text is unaffected", "Women's Wrap Dress",
      vendor="Bandana Women", tags="Women, Women Dress",
      expect_gender="Women", expect_branch="Western", expect_leaf="Dress")
# "cardigan"/"turtleneck" fold into Sweater — 47 real EXISTING cardigans
# had no keyword and were falling to Shirt; turtleneck only resolved
# correctly by coincidence elsewhere and would fail for a brand (like
# Bandana) whose product_type is a generic bucket with no useful signal.
check("a bare 'Cardigan' with no other signal resolves Sweater", "Modal Rib Lace Cardigan",
      product_type="Tops", vendor="Women", expect_branch="Western", expect_leaf="Sweater")
check("a bare 'Turtleneck' with generic product_type resolves Sweater", "Rib Relaxed Fit Turtleneck",
      product_type="Tops", vendor="Women", expect_branch="Western", expect_leaf="Sweater")
# Bandana's "B-Fit" activewear line: vendor is just "B-Fit" (no gender
# word, so the vendor-only check finds nothing) and EVERY B-Fit product —
# men's and women's alike — carries a shared cross-collection tag literally
# named "B-Fit Men Women". Once that hits the merged blob, "women" wins
# (GENDER_PATTERNS checks it before "men" on purpose — see that list's own
# comment) and silently overrides a title that says "Men's" in plain
# English. 53 of 56 real "Men's B-Fit..." products were miscategorized
# under Women for exactly this reason before the title-prefix tier fixed it.
check("'Men's B-Fit...' title beats a same-blob 'B-Fit Men Women' tag", "Men's B-Fit CoolMax Joggers",
      vendor="B-Fit", tags="B-Fit, B-Fit Men, B-Fit Men Bottoms, B-Fit Men Women, Men, Men Activewear",
      expect_gender="Men", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Joggers")
check("the same tag doesn't break a genuinely Women's B-Fit product", "Women's B-Fit CoolMax Joggers",
      vendor="B-Fit", tags="B-Fit, B-Fit Women, B-Fit Men Women, Women, Women Activewear",
      expect_gender="Women", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Joggers")
# "Tote(s)" had no keyword of its own at all — real Bandana/Lama examples
# ("Women Tote", "Journey Tote", "SUNDAY MARKET TOTE") were falling all the
# way through to the generic Western>Shirt default.
check("a bare 'Tote' resolves Bag, not Shirt", "Journey Tote",
      vendor="Bandana", expect_branch="Accessories", expect_leaf="Bag")
# "Cap Sleeve" is a sleeve STYLE (covers just the shoulder), nothing to do
# with headwear — two real Bandana products ("Women's Raglan Cap Sleeve
# Tee", "Boys' Graphic Cap Sleeve Tee") were landing on the literal Cap
# accessory leaf off the bare substring "cap".
check("'Cap Sleeve Tee' resolves T-Shirt, not the Cap accessory", "Women's Raglan Cap Sleeve Tee",
      vendor="Bandana Women", expect_gender="Women", expect_branch="Western", expect_leaf="T-Shirt")
check("a real standalone cap is unaffected", "Embroidered Baseball Cap",
      vendor="Unisex", expect_branch="Accessories", expect_leaf="Cap")
# "Sock-fit" is a real sneaker-construction term (a knit upper built like a
# sock), not an actual pair of socks — real Lama example, "SOCK-FIT CASUAL
# SNEAKERS" (Rs. 8,970, shoe-tier pricing vs. every genuine Socks product
# under Rs. 1,950), was landing on Accessories>Socks off the bare
# substring "sock".
check("'Sock-fit Sneakers' resolves Shoes, not the Socks accessory", "Sock-Fit Casual Sneakers",
      vendor="Lama", product_type="Footwear", expect_branch="Western", expect_sub="Footwear", expect_leaf="Shoes")
check("a real standalone sock product is unaffected", "Cotton Sneaker Socks",
      vendor="Lama", expect_branch="Accessories", expect_leaf="Socks")
# "with...belt/tie" garment-detail stripping didn't cover "scarf" — a real
# Lama dress ("CITY DRESS WITH SCARF DETAIL") was landing on
# Accessories>Scarf instead of Dress.
check("'Dress With Scarf Detail' resolves Dress, not the Scarf accessory", "City Dress With Scarf Detail",
      vendor="Women", expect_gender="Women", expect_branch="Western", expect_leaf="Dress")
check("a real standalone scarf is unaffected", "Printed Silk Scarf",
      vendor="Women", expect_branch="Accessories", expect_leaf="Scarf")
# GARMENT_NOUN_RE only recognized "trousers", not the equally common
# "pants" spelling — a real Lama product, "TAPERED COTTON PANTS WITH
# BELT", was landing on Accessories>Belt instead of Trouser.
check("'Pants With Belt' resolves Trouser, not the Belt accessory", "Tapered Cotton Pants With Belt",
      vendor="Women", expect_gender="Women", expect_branch="Western", expect_sub="Bottomwear", expect_leaf="Trouser")
check("a real standalone belt is unaffected", "Faux Leather Belt",
      vendor="Men", expect_branch="Accessories", expect_leaf="Belt")
# Real Zellbury bug, 1,796 real products: the piece-count regex required
# the digit and "p" adjacent (only an optional HYPHEN between them, never
# a space) and only ever checked title+product_type, never description —
# so a real 3-piece set whose OWN description says "Buy 3 Piece Printed
# Lawn Shirt Shalwar Dupatta..." never matched on either count, and fell
# through to the named-piece-counting fallback, which ALSO undercounted
# it (see the next test) — landing on "2-Piece" instead of "3-Piece".
check("a '3 Piece' (space, not hyphen) stated only in the description resolves 3-Piece",
      "Shirt Shalwar Dupatta - 0582", product_type="Essential Unstitched", vendor="Zellbury Women",
      description="Buy 3 Piece Printed Lawn Shirt Shalwar Dupatta in Black Color",
      expect_gender="Women", expect_branch="Eastern", expect_sub="Unstitched", expect_leaf="3-Piece")
# Same real product family, no explicit count anywhere (title-only named-
# piece fallback) — "shalwar" wasn't in the countable keyword list at all,
# so "Shirt Shalwar Dupatta" only counted 2 (shirt, dupatta) instead of 3.
check("named-piece fallback counts 'shalwar' as its own piece, not just 'trouser'",
      "Shirt Shalwar Dupatta", product_type="Essential Unstitched", vendor="Zellbury Women",
      expect_gender="Women", expect_branch="Eastern", expect_sub="Unstitched", expect_leaf="3-Piece")
# User-reported: browsing Women's Jackets turned up real vests. Read every
# one of the 156 real vest/gilet/bodywarmer/Western-waistcoat products
# sitting in Jacket across every gender before adding this leaf — none
# showed any real Eastern signal, so this is a Western sub-category split
# (a sleeveless vest is a different garment from a jacket, which has
# sleeves), not an Eastern branch move.
check("a real Women's vest resolves its own Vest leaf, not Jacket", "Women's Brushed Spacer Vest",
      vendor="Bandana Women", expect_gender="Women", expect_branch="Western", expect_leaf="Vest")
check("a coat whose description mentions 'vests' only as a likely 'vents' typo stays Jacket",
      "Summar Coat Slim Fit 2 Button Down Charcoal Black", vendor="Men",
      description="Window Check Fabric Notch Lapel Two Buttons Two Flap Pockets Two Back Side Vests Contrast Elbow Patches",
      expect_gender="Men", expect_branch="Western", expect_leaf="Jacket")
# User-reported: browsing Hoodie turned up real hooded jackets. Read all
# 99 real Hoodie-filed products with an outerwear-sounding title word
# before deciding what to do — "hooded" is an ADJECTIVE describing a
# feature, not the garment's own type, and was winning outright over the
# actual garment noun (jacket/coat) appearing later in the same title.
check("'Hooded Puffer Jacket' resolves Jacket, not Hoodie", "Hooded Puffer Jacket",
      vendor="Cambridge", expect_branch="Western", expect_leaf="Jacket")
check("'Hooded Denim Jacket' resolves Jacket too", "Black Hooded Denim Jacket",
      vendor="Cambridge", expect_branch="Western", expect_leaf="Jacket")
check("'Hooded Duffle Coat' resolves Jacket (coat folds into Jacket)", "Men's Hooded Duffle Coat Olive",
      vendor="Charcoal", expect_branch="Western", expect_leaf="Jacket")
# "Gilet" wins over the hoodie ambiguity when NO "jacket" word is also
# present — real example: Furor's "Hooded Puffer Gilet" (no "jacket"
# anywhere in the title) was landing on Hoodie off the bare "hooded"
# adjective before this.
check("'Hooded Puffer Gilet' (no 'jacket' word) resolves Vest, not Hoodie", "Hooded Puffer Gilet - FMTJP24-043",
      vendor="Furor", description="Gilet Jacket Regular Fit Polyester Fabric Chest Zipper Pocket",
      expect_branch="Western", expect_leaf="Vest")
# Explicit user decision (2026-09-01, asked directly after two rounds of
# back-and-forth on this exact question — "logically one would want to
# see sleeveless/vest type jackets in JACKETS SECTION"): whenever
# "jacket" is ALSO in the title, Jacket wins outright — title word beats
# confirmed construction, full stop, even for a garment whose own
# description explicitly confirms sleeveless. Real examples, all visually
# confirmed genuinely sleeveless via the actual product photo before this
# rule was set: Cougar's "Hooded Gilet Jacket" ("...sleeveless
# construction and 100% polyester parachute fabric"), Charcoal's
# "QUILTED SUEDE GILET JACKET SLEEVELESS" (photo-verified real vest),
# Edenrobe's "Vest Gilet - 12008-SL Boys Jacket" (empty description, no
# evidence either way — same class of ambiguous title already left as
# Jacket when the Vest leaf itself was created, see CATEGORY_TREE's own
# comment). Do not reintroduce a sleeveless-description exception here
# without asking again.
check("'Hooded Gilet Jacket' resolves Jacket, not Vest — title word wins", "Hooded Gilet Jacket",
      vendor="Cougar", description="A streamlined quilted gilet in khaki with mock neck styling. The sleeveless construction and 100% polyester parachute fabric.",
      expect_branch="Western", expect_leaf="Jacket")
check("'Vest Gilet ... Jacket' also resolves Jacket", "Vest Gilet - 12008-SL Boys Jacket",
      vendor="Boys", expect_branch="Western", expect_leaf="Jacket")
# The literal NOUN "hoodie" is still trusted outright, even alongside
# "jacket" — real genuine hoodies verified by description before keeping
# this: Cambridge's "WAFFLE/OTTOMAN HOODIE ZIPPER JACKET" line (100% soft
# fleece, cotton-poly blend) and Charcoal's "JACKET FULL SLEEVE KNIT
# HOODIE" line (100% fleece cotton) are both real hoodies despite
# "jacket" also appearing in the title.
check("a genuine fleece 'Hoodie Zipper Jacket' stays Hoodie", "Waffle Hoodie Zipper Jacket",
      vendor="Cambridge", description="Crafted from soft LSF fleece with a waffle texture, cotton-poly blend.",
      expect_branch="Western", expect_leaf="Hoodie")
check("'Jacket ... Knit Hoodie' (fleece) stays Hoodie too", "Jacket Full Sleeve Knit Hoodie Grey Heather",
      vendor="Charcoal", description="100% Fleece Cotton", expect_branch="Western", expect_leaf="Hoodie")
# "with a hood(ie)" describes an attached-hood DETAIL on another garment,
# not the garment's own type — same class of fix as GARMENT_DETAIL_RE's
# "with...belt/tie/scarf" stripping. Real examples: Outfitters' "Faux
# Leather Jacket With Hoodie" (Synthetic Faux Leather) and "Denim Jacket
# With Hoodie" (100% Cotton denim) are both real jackets that merely
# include an attached hood.
check("'Jacket With Hoodie' resolves Jacket, not Hoodie", "Faux Leather Jacket With Hoodie",
      vendor="Outfitters", expect_branch="Western", expect_leaf="Jacket")
check("a plain 'Hooded Sweatshirt' with no competing noun still resolves Hoodie", "Men's Hooded Pullover",
      vendor="Men", expect_branch="Western", expect_leaf="Hoodie")
# "shirt" isn't checked elsewhere in this function (it's the caller's own
# final default), so a "hooded shirt" needs an explicit exclusion or the
# last-resort bare-"hooded" fallback swallows it. Real examples: One
# (Be-One)'s "Hooded Check Shirt" ("Regular fit short sleeve shirt in
# check fabrication, featuring... contrasting jersey hood") and Meme's
# "HOODED DENIM SHIRT" ("SLIM FIT SHACKET WITH REGULAR COLLAR FEATURING
# HOOD. SNAP BUTTON DOWN CLOSURE") are both genuine collared, buttoned
# shirts with a hood as a design detail, not hoodies.
check("'Hooded Check Shirt' resolves Shirt, not Hoodie", "Hooded Check Shirt",
      vendor="One (Be-One)",
      description="Regular fit short sleeve shirt in check fabrication, featuring front buttoned placket with contrasting jersey hood and double pockets in front",
      expect_branch="Western", expect_leaf="Shirt")
# User-reported size anomaly on Vest (chest-inch sizing) turned up nothing
# wrong there (verified via real product photos — every one really is a
# genuine sleeveless vest), but the same technique applied across every
# category surfaced a real, much bigger bug elsewhere: 112 real Edenrobe
# products literally titled "Formal Suit - EBTCPC..." (product_type "Men
# Formal Suits") were still sitting in Co-ord Set, because their own text
# never says blazer/lapel/tuxedo/etc — only "suit" — and bare "suit" was
# deliberately excluded from FORMAL_SUIT_RE (too broad on its own, see
# that regex's own original comment). "Formal Suit" the PHRASE is safe to
# trust outright — a casual Co-ord Set never calls itself "formal."
check("a product titled 'Formal Suit' resolves the Formal Suit leaf", "Formal Suit - EBTCPC22-4482",
      vendor="Suiting", product_type="Men Formal Suits", tags="70_Discount,Above-50_Discount",
      description="Men's Pant Coat Suit Suiting Fabric",
      expect_gender="Men", expect_branch="Western", expect_sub="Formalwear", expect_leaf="Formal Suit")
# A second, narrower real pattern found in the same audit: Cambridge's
# "SHARP"/"LUXER" formal-suit lines never say "formal" or any
# FORMAL_SUIT_RE word either — just "suit" plus this brand's own
# tailoring-fit boilerplate ("Model is 6'2" with a 40" chest, and is
# wearing a size 40"), which also shows up as real chest-inch sizing in
# the variant data (34-58), not S/M/L/XL. Requires BOTH "suit" AND the
# boilerplate together — a real Cambridge loungewear set ("KNIT &
# PAJAMA") uses the same boilerplate but never says "suit," and correctly
# stays excluded.
check("'Sharp 3 Piece Suit' + the chest-fit boilerplate resolves Formal Suit", "Sharp 3 Piece Suit",
      store="cambridge", vendor="Cambridge",
      description="Go for a sophisticated smart look with this textured suit. Slim Fit, 3 Pc. Model is 6'2\" with a 40\" chest, and is wearing a size 40.",
      expect_gender="Men", expect_branch="Western", expect_sub="Formalwear", expect_leaf="Formal Suit")
check("the same chest-fit boilerplate on a real pajama set (no 'suit' word) is unaffected, not Formal Suit",
      "Knit & Pajama", store="cambridge", vendor="Cambridge",
      description="Stripes pajama and knitted tees combine in this soft cotton pyjama set. Model is 6'2\" with a 40\" chest, and is wearing a size 40.",
      expect_gender="Men", expect_branch="Western", expect_leaf="Shirt")

print(f"{PASSED} passed, {len(FAILURES)} failed")
if FAILURES:
    print()
    for f in FAILURES:
        print(f, "\n")
    raise SystemExit(1)
