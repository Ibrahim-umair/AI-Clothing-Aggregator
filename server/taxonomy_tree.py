"""In-memory cache of the categories adjacency-list tree (~113 rows) plus
helpers for resolving human-readable gender/branch/sub/category filter
strings to a category id, walking descendants for filtering, and building
the mega-menu column structure the frontend's TaxonomyNav component expects.

Port of server/taxonomyTree.js — logic unchanged, see that file's comments
for the "why" behind each piece (skipped-level tree walk, BFS-by-name,
count-based vs fixed-order menu sorting).
"""
import time
from dataclasses import dataclass, field

from db import get_pool

GENDER_ORDER = ["Men", "Women", "Boys", "Girls", "Unisex"]
BRANCH_ORDER = ["Eastern", "Western", "Accessories", "Fragrance & Beauty"]
EASTERN_SUB_ORDER = ["Unstitched", "Semi-Stitched", "Stitched"]
WESTERN_SUB_ORDER = ["Upperwear", "Bottomwear", "Suits & Sets", "Footwear"]

TREE_TTL_SECONDS = 5 * 60


@dataclass
class CategoryNode:
    id: int
    parent_id: int | None
    name: str
    slug: str


@dataclass
class Tree:
    by_id: dict[int, CategoryNode] = field(default_factory=dict)
    children_of: dict[int | None, list[int]] = field(default_factory=dict)
    loaded_at: float = 0.0


_cache: Tree | None = None


def _sub_order_for_branch(branch: str) -> list[str] | None:
    if branch == "Eastern":
        return EASTERN_SUB_ORDER
    if branch == "Western":
        return WESTERN_SUB_ORDER
    return None


def _sort_by_order(items: list[dict], order: list[str] | None, key: str) -> list[dict]:
    if not order:
        return sorted(items, key=lambda x: x["count"], reverse=True)
    return sorted(items, key=lambda x: order.index(x[key]) if x[key] in order else len(order))


async def _load_tree() -> Tree:
    pool = await get_pool()
    rows = await pool.fetch("SELECT id, parent_id, name, slug FROM categories")
    by_id: dict[int, CategoryNode] = {}
    children_of: dict[int | None, list[int]] = {}
    for r in rows:
        by_id[r["id"]] = CategoryNode(id=r["id"], parent_id=r["parent_id"], name=r["name"], slug=r["slug"])
        children_of.setdefault(r["parent_id"], []).append(r["id"])
    global _cache
    _cache = Tree(by_id=by_id, children_of=children_of, loaded_at=time.monotonic())
    return _cache


async def get_tree() -> Tree:
    if _cache is None or time.monotonic() - _cache.loaded_at > TREE_TTL_SECONDS:
        return await _load_tree()
    return _cache


async def refresh_tree() -> Tree:
    return await _load_tree()


def _child_by_name(tree: Tree, parent_id: int | None, name: str) -> int | None:
    needle = name.strip().lower()
    for cid in tree.children_of.get(parent_id, []):
        if tree.by_id[cid].name.lower() == needle:
            return cid
    return None


def resolve_node_id(tree: Tree, gender: str | None = None, branch: str | None = None,
                     sub: str | None = None, category: str | None = None) -> tuple[int | None, bool]:
    """Returns (id, not_found). The 4 levels don't have to be contiguous —
    whenever a level is skipped, falls back to a deep search under whatever
    matched so far instead of requiring a direct child."""
    parent: int | None = None
    matched: int | None = None
    skipped = False
    for name in (gender, branch, sub, category):
        if not name:
            skipped = True
            continue
        node_id = find_descendant_by_name(tree, parent, name) if skipped else _child_by_name(tree, parent, name)
        if node_id is None:
            return None, True
        matched = node_id
        parent = node_id
        skipped = False
    return matched, False


def find_descendant_by_name(tree: Tree, root_id: int | None, name: str) -> int | None:
    """BFS/DFS under root_id (inclusive) for the first node whose name
    matches case-insensitively."""
    needle = name.strip().lower()
    stack = [root_id]
    while stack:
        node_id = stack.pop()
        node = tree.by_id.get(node_id) if node_id is not None else None
        if node and node.name.lower() == needle:
            return node_id
        stack.extend(tree.children_of.get(node_id, []))
    return None


def descendant_ids(tree: Tree, node_id: int | None) -> list[int] | None:
    """All descendant ids of node_id, including itself. None means 'every
    category in the tree' (used when no filter is active)."""
    if node_id is None:
        return None
    out = [node_id]
    stack = [node_id]
    while stack:
        cur = stack.pop()
        for child_id in tree.children_of.get(cur, []):
            out.append(child_id)
            stack.append(child_id)
    return out


def build_menus(tree: Tree, counts_by_category_id: dict[int, int]) -> dict:
    def count_for(node_id: int) -> int:
        ids = descendant_ids(tree, node_id) or []
        return sum(counts_by_category_id.get(i, 0) for i in ids)

    gender_roots = [
        tree.by_id[i] for i in tree.children_of.get(None, [])
        if tree.by_id[i].name in GENDER_ORDER
    ]

    menus: dict[str, list] = {}
    gender_facets: list[dict] = []

    for g_node in gender_roots:
        g_count = count_for(g_node.id)
        gender_facets.append({"value": g_node.name, "count": g_count})
        if g_count == 0:
            continue

        branch_nodes = [tree.by_id[i] for i in tree.children_of.get(g_node.id, [])]
        columns = []
        for b_node in branch_nodes:
            b_count = count_for(b_node.id)
            if b_count == 0:
                continue
            sub_order = _sub_order_for_branch(b_node.name)
            children = [tree.by_id[i] for i in tree.children_of.get(b_node.id, [])]

            if sub_order:
                subs = []
                for s_node in children:
                    s_count = count_for(s_node.id)
                    if s_count == 0:
                        continue
                    leaves = [
                        {"value": tree.by_id[i].name, "count": count_for(i)}
                        for i in tree.children_of.get(s_node.id, [])
                    ]
                    leaves = [c for c in leaves if c["count"] > 0]
                    subs.append({"sub": s_node.name, "count": s_count, "categories": leaves})
                subs = _sort_by_order(subs, sub_order, "sub")
                columns.append({"branch": b_node.name, "count": b_count, "subs": subs, "categories": None})
                continue

            leaves = [{"value": leaf.name, "count": count_for(leaf.id)} for leaf in children]
            leaves = [c for c in leaves if c["count"] > 0]
            columns.append({"branch": b_node.name, "count": b_count, "subs": None, "categories": leaves})

        columns = _sort_by_order(columns, BRANCH_ORDER, "branch")
        menus[g_node.name] = columns

    gender_facets = _sort_by_order(gender_facets, GENDER_ORDER, "value")
    return {"menus": menus, "genderFacets": gender_facets}
