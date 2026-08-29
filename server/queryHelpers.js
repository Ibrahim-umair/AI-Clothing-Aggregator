// Shared, Express-independent query-building helpers — used by /api/products
// and /api/search in index.js, and by search.js/debug_search.js (which
// import categoryIdsForSearch/resolveBrandId without needing Express or an
// HTTP request object at all). Pulled out of index.js specifically so the
// CLI debug tool doesn't have to start a whole server to reuse this logic.
import { pool } from "./db.js";
import { getTree, resolveNodeId, descendantIds, findDescendantByName } from "./taxonomyTree.js";

export const PAGE_SIZE_DEFAULT = 24;
export const PAGE_SIZE_MAX = 96;

// Different stores spell the same size differently — "M" vs "Medium",
// "XXL" vs "2XL" — which was showing up as separate, duplicate size buttons
// in the filter sidebar and the product page. Combined-range labels like
// "L-XL" and "S-M" are deliberately NOT folded into their component sizes —
// they're a genuinely different, wider size a customer can pick, not a
// duplicate spelling of an existing one.
export const SIZE_ALIASES = {
  XS: ["xs", "extra small", "x-small", "xsmall"],
  S: ["s", "small"],
  M: ["m", "medium"],
  L: ["l", "large"],
  XL: ["xl", "extra large", "x-large", "xlarge"],
  XXL: ["xxl", "2xl", "xx-large", "xxlarge"],
  XXXL: ["xxxl", "3xl", "xxx-large", "xxxlarge"],
};
const SIZE_CANON_LOOKUP = new Map();
for (const [canon, aliases] of Object.entries(SIZE_ALIASES)) {
  for (const a of aliases) SIZE_CANON_LOOKUP.set(a, canon);
}
export function canonicalSize(raw) {
  if (!raw) return raw;
  const trimmed = raw.trim();
  return SIZE_CANON_LOOKUP.get(trimmed.toLowerCase()) || trimmed;
}
// Expands the canonical sizes a client requested (e.g. "M") back out to
// every raw spelling that should match it (e.g. "m", "medium") so the SQL
// filter still matches whichever spelling a given store actually used.
export function expandSizeAliasesForQuery(requested) {
  const out = new Set();
  for (const val of requested) {
    const trimmed = val.trim();
    out.add(trimmed.toLowerCase());
    const aliases = SIZE_ALIASES[trimmed.toUpperCase()];
    if (aliases) aliases.forEach((a) => out.add(a));
  }
  return [...out];
}

export function parsePage(q) {
  const page = Math.max(1, parseInt(q.page, 10) || 1);
  const pageSize = Math.min(PAGE_SIZE_MAX, Math.max(1, parseInt(q.pageSize, 10) || PAGE_SIZE_DEFAULT));
  return { page, pageSize, offset: (page - 1) * pageSize };
}

// Resolves { gender, branch, sub, category } into a Postgres-ready
// category_id filter (an array of ids to match with = ANY($)), honoring
// the tree structure — selecting "Men" also matches every category nested
// under it. Resolves to a SINGLE tree node (correct for the Home page's
// "one specific card was clicked" case — see categoryIdsForSearch below
// for why a gender-less NL search needs different semantics).
export async function categoryIdsFromQuery(q) {
  if (!q.gender && !q.branch && !q.sub && !q.category) return { ids: null, notFound: false };
  const tree = await getTree();
  const { id, notFound } = resolveNodeId(tree, {
    gender: q.gender,
    branch: q.branch,
    sub: q.sub,
    category: q.category,
  });
  if (notFound) return { ids: [], notFound: true };
  return { ids: descendantIds(tree, id), notFound: false };
}

// Purpose-built for /api/search, deliberately separate from
// categoryIdsFromQuery above: that one resolves to a SINGLE node (correct
// for the Home page's "one specific card was clicked" case, via
// resolveNodeId/findDescendantByName's first-match semantics), but a
// gender-less NL search needs the OPPOSITE — every leaf with this exact
// name, across every gender it exists under, not just the first one a tree
// walk happens to visit. Real bug this fixes: "furor jeans" (no gender
// extracted) with categoryIdsFromQuery({category: "Jeans"}) was silently
// resolving to only ONE gender's Jeans leaf (whichever BFS visited first),
// matching zero of Furor's real (Men's) jeans products.
// When no gender is specified at all, only adult roots are searched.
// Someone typing "polos under 3000" with no gender is browsing as an
// adult shopper — returning Boys'/Girls' items alongside is noise, and it
// was really happening (a "Polo" search surfaced Boys Polo Tees near the
// top of the textual leg). Kids' items are still fully reachable, just
// only when actually asked for ("boys polo"), which sets gender
// explicitly and skips this default entirely.
const ADULT_GENDER_ROOTS = ["Men", "Women", "Unisex"];

export async function categoryIdsForSearch(gender, categories) {
  const names = (Array.isArray(categories) ? categories : categories ? [categories] : []).filter(Boolean);
  if (!gender && names.length === 0) {
    // No gender AND no category: still scope to adult roots rather than
    // returning null (= "no category filter at all"), so the kids
    // exclusion above holds for bare queries like "grey clothes" too.
    const tree = await getTree();
    const roots = (tree.childrenOf.get(null) || []).filter((id) => ADULT_GENDER_ROOTS.includes(tree.byId.get(id).name));
    return { ids: roots.flatMap((id) => descendantIds(tree, id)), notFound: false };
  }
  const tree = await getTree();
  const genderRoots = gender
    ? [(tree.childrenOf.get(null) || []).find((id) => tree.byId.get(id).name.toLowerCase() === gender.toLowerCase())].filter((x) => x != null)
    : (tree.childrenOf.get(null) || []).filter((id) => ADULT_GENDER_ROOTS.includes(tree.byId.get(id).name));
  if (gender && genderRoots.length === 0) return { ids: [], notFound: true };

  if (names.length === 0) {
    // Gender only: every category under that one root.
    return { ids: genderRoots.flatMap((id) => descendantIds(tree, id)), notFound: false };
  }

  // Every matching node under every in-scope gender root, EXPANDED to its
  // descendants. The expansion is what makes a grouping node like
  // "Upperwear" work at all: products sit on leaf ids only, so matching
  // the Upperwear node itself and stopping there returns literally zero
  // rows. For an actual leaf, descendantIds is just [leafId], so the same
  // code path is correct for both.
  //
  // Real bug found via 100-query testing: the model's `categories` array
  // sometimes names a specific leaf AND one of its own ancestor grouping
  // nodes in the same request — e.g. `["3-Piece", "Unstitched"]` for
  // "unstitched 3-piece suits", or `["Top", "Shirt", "Western"]` for
  // "women's western tops and shirts". Since every name's descendant set
  // was unioned in unconditionally, the ancestor's much larger descendant
  // set (all of Unstitched's 1/2/3-Piece/Suit, or all of Western's
  // Upperwear/Bottomwear/Footwear/Suits & Sets) swallowed the specific
  // leaf's own precision entirely — "3-Piece" stopped meaning anything
  // once "Unstitched" was unioned in alongside it. An ancestor named
  // alongside its own descendant carries no additional information (the
  // descendant is already a subset of it) and only dilutes — so within
  // each gender root, prune any resolved node that is a strict ancestor
  // of another resolved node before expanding to descendants.
  const ids = new Set();
  for (const rootId of genderRoots) {
    const resolved = names
      .map((name) => findDescendantByName(tree, rootId, name))
      .filter((id) => id != null);
    const pruned = resolved.filter(
      (id) => !resolved.some((other) => other !== id && isAncestor(tree, id, other))
    );
    for (const nodeId of pruned) descendantIds(tree, nodeId).forEach((id) => ids.add(id));
  }
  if (ids.size === 0) return { ids: [], notFound: true };
  return { ids: [...ids], notFound: false };
}

function isAncestor(tree, ancestorId, nodeId) {
  let cur = tree.byId.get(nodeId)?.parentId;
  while (cur != null) {
    if (cur === ancestorId) return true;
    cur = tree.byId.get(cur)?.parentId;
  }
  return false;
}

export async function resolveBrandId(brandParam) {
  if (!brandParam) return null;
  const { rows } = await pool.query(
    "SELECT id FROM brands WHERE lower(name) = lower($1) OR lower(slug) = lower($1) LIMIT 1",
    [brandParam]
  );
  return rows[0]?.id ?? null;
}
