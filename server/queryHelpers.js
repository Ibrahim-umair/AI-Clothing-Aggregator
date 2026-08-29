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
export async function categoryIdsForSearch(gender, category) {
  if (!gender && !category) return { ids: null, notFound: false };
  const tree = await getTree();
  const genderRoots = gender
    ? [(tree.childrenOf.get(null) || []).find((id) => tree.byId.get(id).name.toLowerCase() === gender.toLowerCase())].filter((x) => x != null)
    : tree.childrenOf.get(null) || [];
  if (gender && genderRoots.length === 0) return { ids: [], notFound: true };

  if (!category) {
    // Gender only: every category under that one root (categoryIdsFromQuery
    // already does exactly this correctly for a single known root).
    return categoryIdsFromQuery({ gender });
  }

  const leafIds = genderRoots.flatMap((rootId) => {
    const id = findDescendantByName(tree, rootId, category);
    return id != null ? [id] : [];
  });
  if (leafIds.length === 0) return { ids: [], notFound: true };
  // Leaves have no descendants of their own — this is already the final id set.
  return { ids: leafIds, notFound: false };
}

export async function resolveBrandId(brandParam) {
  if (!brandParam) return null;
  const { rows } = await pool.query(
    "SELECT id FROM brands WHERE lower(name) = lower($1) OR lower(slug) = lower($1) LIMIT 1",
    [brandParam]
  );
  return rows[0]?.id ?? null;
}
