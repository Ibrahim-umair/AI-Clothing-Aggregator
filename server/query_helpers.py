"""Shared query-building helpers used by /api/products and /api/search.

Port of server/queryHelpers.js — logic unchanged. See that file's history
(server/CHANGELOG-equivalent commits) for why each of these exists; the
short version is preserved in the comments below.
"""
from db import get_pool
from taxonomy_tree import Tree, descendant_ids, find_descendant_by_name, get_tree, resolve_node_id

PAGE_SIZE_DEFAULT = 24
PAGE_SIZE_MAX = 96

# Different stores spell the same size differently ("M" vs "Medium", "XXL"
# vs "2XL") — combined-range labels like "L-XL"/"S-M" are deliberately NOT
# folded into their component sizes, they're a genuinely different, wider
# size a customer can pick, not a duplicate spelling of an existing one.
SIZE_ALIASES = {
    "XS": ["xs", "extra small", "x-small", "xsmall"],
    "S": ["s", "small"],
    "M": ["m", "medium"],
    "L": ["l", "large"],
    "XL": ["xl", "extra large", "x-large", "xlarge"],
    "XXL": ["xxl", "2xl", "xx-large", "xxlarge"],
    "XXXL": ["xxxl", "3xl", "xxx-large", "xxxlarge"],
}
_SIZE_CANON_LOOKUP = {alias: canon for canon, aliases in SIZE_ALIASES.items() for alias in aliases}


def canonical_size(raw: str | None) -> str | None:
    if not raw:
        return raw
    trimmed = raw.strip()
    return _SIZE_CANON_LOOKUP.get(trimmed.lower(), trimmed)


def expand_size_aliases_for_query(requested: list[str]) -> list[str]:
    """Expands the canonical sizes a client requested (e.g. "M") back out
    to every raw spelling that should match it (e.g. "m", "medium")."""
    out: set[str] = set()
    for val in requested:
        trimmed = val.strip()
        out.add(trimmed.lower())
        aliases = SIZE_ALIASES.get(trimmed.upper())
        if aliases:
            out.update(aliases)
    return list(out)


def parse_page(page_param, page_size_param) -> tuple[int, int, int]:
    try:
        page = max(1, int(page_param))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(PAGE_SIZE_MAX, max(1, int(page_size_param)))
    except (TypeError, ValueError):
        page_size = PAGE_SIZE_DEFAULT
    return page, page_size, (page - 1) * page_size


async def category_ids_from_query(gender=None, branch=None, sub=None, category=None) -> tuple[list[int] | None, bool]:
    """Resolves a SINGLE tree node (correct for the Home page's "one
    specific card was clicked" case — see category_ids_for_search below for
    why a gender-less NL search needs different semantics)."""
    if not any([gender, branch, sub, category]):
        return None, False
    tree = await get_tree()
    node_id, not_found = resolve_node_id(tree, gender=gender, branch=branch, sub=sub, category=category)
    if not_found:
        return [], True
    return descendant_ids(tree, node_id), False


# Someone typing "polos under 3000" with no gender is browsing as an adult
# shopper — returning Boys'/Girls' items alongside is noise. Kids' items
# are still fully reachable, just only when actually asked for ("boys
# polo"), which sets gender explicitly and skips this default entirely.
ADULT_GENDER_ROOTS = ["Men", "Women", "Unisex"]


def _is_ancestor(tree: Tree, ancestor_id: int, node_id: int) -> bool:
    cur = tree.by_id[node_id].parent_id if node_id in tree.by_id else None
    while cur is not None:
        if cur == ancestor_id:
            return True
        cur = tree.by_id[cur].parent_id if cur in tree.by_id else None
    return False


async def category_ids_for_search(gender: str | None, categories: list[str] | None) -> tuple[list[int], bool]:
    """Purpose-built for /api/search, deliberately separate from
    category_ids_from_query above: a gender-less NL search needs every
    leaf with this exact name across every gender it exists under, not
    just the first one a tree walk happens to visit.

    Real bug fixed here (found via 100-query testing): the model's
    `categories` sometimes names a specific leaf AND one of its own
    ancestor grouping nodes in the same request (e.g. ["3-Piece",
    "Unstitched"]) — since every name's descendant set used to be unioned
    in unconditionally, the ancestor's much larger set swallowed the
    leaf's own precision. Within each gender root, any resolved node that
    is a strict ancestor of another resolved node is pruned before
    expanding to descendants.
    """
    names = [c for c in (categories or []) if c]

    if not gender and not names:
        tree = await get_tree()
        roots = [i for i in tree.children_of.get(None, []) if tree.by_id[i].name in ADULT_GENDER_ROOTS]
        ids: list[int] = []
        for r in roots:
            ids.extend(descendant_ids(tree, r) or [])
        return ids, False

    tree = await get_tree()
    if gender:
        gender_roots = [
            i for i in tree.children_of.get(None, [])
            if tree.by_id[i].name.lower() == gender.lower()
        ]
    else:
        gender_roots = [i for i in tree.children_of.get(None, []) if tree.by_id[i].name in ADULT_GENDER_ROOTS]

    if gender and not gender_roots:
        return [], True

    if not names:
        ids = []
        for r in gender_roots:
            ids.extend(descendant_ids(tree, r) or [])
        return ids, False

    ids_set: set[int] = set()
    for root_id in gender_roots:
        resolved = [nid for nid in (find_descendant_by_name(tree, root_id, name) for name in names) if nid is not None]
        pruned = [nid for nid in resolved if not any(_is_ancestor(tree, nid, other) for other in resolved if other != nid)]
        for node_id in pruned:
            ids_set.update(descendant_ids(tree, node_id) or [])

    if not ids_set:
        return [], True
    return list(ids_set), False


async def resolve_brand_id(brand_param: str | None) -> int | None:
    if not brand_param:
        return None
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id FROM brands WHERE lower(name) = lower($1) OR lower(slug) = lower($1) LIMIT 1",
        brand_param,
    )
    return row["id"] if row else None
