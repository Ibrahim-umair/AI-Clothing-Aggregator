// In-memory cache of the categories adjacency-list tree (~113 rows — cheap
// to hold entirely in memory) plus helpers for resolving human-readable
// gender/branch/sub/category filter strings to a category id, walking
// descendants for filtering, and building the mega-menu column structure
// the frontend's TaxonomyNav component expects (mirrors the shape that used
// to be computed client-side in src/lib/taxonomy.js against the full
// products array).
import { pool } from "./db.js";

const GENDER_ORDER = ["Men", "Women", "Boys", "Girls", "Unisex"];
const BRANCH_ORDER = ["Eastern", "Western", "Accessories", "Fragrance & Beauty"];
const EASTERN_SUB_ORDER = ["Unstitched", "Semi-Stitched", "Stitched"];
const WESTERN_SUB_ORDER = ["Upperwear", "Bottomwear", "Suits & Sets", "Footwear"];

function subOrderForBranch(branch) {
  if (branch === "Eastern") return EASTERN_SUB_ORDER;
  if (branch === "Western") return WESTERN_SUB_ORDER;
  return null;
}

function sortByOrder(list, order, key) {
  if (!order) return list.sort((a, b) => b.count - a.count);
  return list.sort((a, b) => order.indexOf(a[key]) - order.indexOf(b[key]));
}

let cache = null; // { byId, childrenOf, roots, loadedAt }

async function loadTree() {
  const { rows } = await pool.query("SELECT id, parent_id, name, slug FROM categories");
  const byId = new Map();
  const childrenOf = new Map();
  for (const r of rows) {
    byId.set(r.id, { id: r.id, parentId: r.parent_id, name: r.name, slug: r.slug });
    if (!childrenOf.has(r.parent_id)) childrenOf.set(r.parent_id, []);
    childrenOf.get(r.parent_id).push(r.id);
  }
  cache = { byId, childrenOf, loadedAt: Date.now() };
  return cache;
}

// ~150 rows — cheap enough to re-fetch on a short TTL rather than require a
// server restart every time a category gets added/renamed (e.g. by
// reseed_categories.py, run independently of this server). A daily-scraping
// pipeline can't rely on someone noticing a category is "missing" and
// remembering to bounce the Node process; this makes that a non-issue.
const TREE_TTL_MS = 5 * 60 * 1000;

export async function getTree() {
  if (!cache || Date.now() - cache.loadedAt > TREE_TTL_MS) await loadTree();
  return cache;
}

export async function refreshTree() {
  return loadTree();
}

function childByName(tree, parentId, name) {
  const kids = tree.childrenOf.get(parentId) || [];
  const needle = name.trim().toLowerCase();
  const id = kids.find((cid) => tree.byId.get(cid).name.toLowerCase() === needle);
  return id ?? null;
}

// Resolves a { gender, branch, sub, category } filter to the deepest
// matching category node id. The 4 levels don't have to be given
// contiguously — the Home page's category cards link with only
// { gender, category } (no branch/sub, since the card doesn't know or care
// which branch a leaf lives under), so whenever a level is skipped we fall
// back to a deep search under whatever's been matched so far instead of
// requiring the next name to be a *direct* child (which would otherwise
// silently fail to match anything and made every such link degrade into
// "just filter by gender", dropping the category filter entirely).
export function resolveNodeId(tree, { gender, branch, sub, category }) {
  let parent = null; // categories.parent_id IS NULL for the 5 gender roots
  let matched = null;
  let skipped = false;
  for (const name of [gender, branch, sub, category]) {
    if (!name) {
      skipped = true;
      continue;
    }
    const id = skipped ? findDescendantByName(tree, parent, name) : childByName(tree, parent, name);
    if (id == null) return { notFound: true };
    matched = id;
    parent = id;
    skipped = false;
  }
  return { id: matched, notFound: false };
}

// BFS under rootId (inclusive) for the first node whose name matches
// (case-insensitive). Used by the Home page's category-card grid, which
// references leaf categories by plain name ("Kurti", "Trouser", ...)
// without needing to know the full branch/sub path.
export function findDescendantByName(tree, rootId, name) {
  const needle = name.trim().toLowerCase();
  const stack = [rootId];
  while (stack.length) {
    const id = stack.pop();
    const node = tree.byId.get(id);
    if (node && node.name.toLowerCase() === needle) return id;
    for (const childId of tree.childrenOf.get(id) || []) stack.push(childId);
  }
  return null;
}

// All descendant ids of nodeId, including itself. Pass null to mean "every
// category in the tree" (used when no filter is active).
export function descendantIds(tree, nodeId) {
  if (nodeId == null) return null;
  const out = [nodeId];
  const stack = [nodeId];
  while (stack.length) {
    const cur = stack.pop();
    for (const childId of tree.childrenOf.get(cur) || []) {
      out.push(childId);
      stack.push(childId);
    }
  }
  return out;
}

// Builds { [gender]: [...menu columns...] } — one column per branch present
// under that gender, each grouped by sub-branch (Eastern/Western) or a flat
// category list (Accessories/Fragrance & Beauty) — using per-leaf-category
// product counts supplied by the caller (countsByCategoryId: Map<id, number>).
export function buildMenus(tree, countsByCategoryId) {
  function countFor(nodeId) {
    const ids = descendantIds(tree, nodeId);
    let total = 0;
    for (const id of ids) total += countsByCategoryId.get(id) || 0;
    return total;
  }

  const genderRoots = (tree.childrenOf.get(null) || [])
    .map((id) => tree.byId.get(id))
    .filter((n) => GENDER_ORDER.includes(n.name));

  const menus = {};
  const genderFacets = [];

  for (const gNode of genderRoots) {
    const gCount = countFor(gNode.id);
    genderFacets.push({ value: gNode.name, count: gCount });
    if (gCount === 0) continue;

    const branchNodes = (tree.childrenOf.get(gNode.id) || []).map((id) => tree.byId.get(id));
    const columns = branchNodes
      .map((bNode) => {
        const bCount = countFor(bNode.id);
        if (bCount === 0) return null;
        const subOrder = subOrderForBranch(bNode.name);
        const children = (tree.childrenOf.get(bNode.id) || []).map((id) => tree.byId.get(id));

        if (subOrder) {
          // children are sub-branches, each containing leaf categories. Leaf
          // order is deliberately left as-is (the order categories were
          // defined in CATEGORY_TREE / inserted into the DB — see
          // db/load_data.py), NOT re-sorted by count: a fixed, predictable
          // order (T-Shirt, Polo, Shirt, ...) reads better as a filter row
          // than one that reshuffles itself as stock counts change.
          const subs = children
            .map((sNode) => {
              const sCount = countFor(sNode.id);
              if (sCount === 0) return null;
              const leaves = (tree.childrenOf.get(sNode.id) || [])
                .map((id) => tree.byId.get(id))
                .map((leaf) => ({ value: leaf.name, count: countFor(leaf.id) }))
                .filter((c) => c.count > 0);
              return { sub: sNode.name, count: sCount, categories: leaves };
            })
            .filter(Boolean);
          sortByOrder(subs, subOrder, "sub");
          return { branch: bNode.name, count: bCount, subs, categories: null };
        }

        // flat branch (Accessories / Fragrance & Beauty): children are
        // leaves directly, same "keep definition order" reasoning as above.
        const leaves = children
          .map((leaf) => ({ value: leaf.name, count: countFor(leaf.id) }))
          .filter((c) => c.count > 0);
        return { branch: bNode.name, count: bCount, subs: null, categories: leaves };
      })
      .filter(Boolean);

    sortByOrder(columns, BRANCH_ORDER, "branch");
    menus[gNode.name] = columns;
  }

  sortByOrder(genderFacets, GENDER_ORDER, "value");
  return { menus, genderFacets };
}
