"""
Read-only CATEGORY_TREE <-> DB category_id resolution, extracted from
backfill_categories.py so both it and the new live-scraper pipeline
(db/scraper/) resolve a classify() result to a category_id identically.

This deliberately does NOT create/seed categories (that's load_data.py's
get_or_make_category / reseed_categories.py's job, run explicitly when
CATEGORY_TREE changes) — it only reads back what's already in the table.
"""
import re


def build_category_lookup(cur):
    """Returns (category_id, leaf_lookup):
    - category_id: (parent_id, slug) -> id, for every row in categories.
    - leaf_lookup: (gender, branch, sub_or_None, leaf_name) -> id, walking
      CATEGORY_TREE and resolving each node against what's actually in the
      DB (a tree node with no matching DB row is simply absent from the
      map, same as backfill_categories.py's original behavior).
    """
    from load_data import CATEGORY_TREE

    cur.execute("SELECT id, parent_id, name, slug FROM categories")
    rows = cur.fetchall()
    by_id = {r[0]: {"parent_id": r[1], "name": r[2], "slug": r[3]} for r in rows}
    children = {}
    for cid, node in by_id.items():
        children.setdefault(node["parent_id"], []).append(cid)

    def child_by_slug(parent_id, slug):
        for cid in children.get(parent_id, []):
            if by_id[cid]["slug"] == slug:
                return cid
        return None

    category_id = {(node["parent_id"], node["slug"]): cid for cid, node in by_id.items()}

    leaf_lookup = {}
    for gender, branches in CATEGORY_TREE.items():
        g_id = child_by_slug(None, gender.lower())
        for branch, content in branches.items():
            b_slug = re.sub(r"[^a-z]+", "-", branch.lower())
            b_id = child_by_slug(g_id, b_slug) if g_id is not None else None
            if isinstance(content, dict):
                for sub, leaves in content.items():
                    s_slug = re.sub(r"[^a-z]+", "-", sub.lower())
                    s_id = child_by_slug(b_id, s_slug) if b_id is not None else None
                    for name, slug in leaves:
                        l_id = child_by_slug(s_id, slug) if s_id is not None else None
                        if l_id is not None:
                            leaf_lookup[(gender, branch, sub, name)] = l_id
            else:
                for name, slug in content:
                    l_id = child_by_slug(b_id, slug) if b_id is not None else None
                    if l_id is not None:
                        leaf_lookup[(gender, branch, None, name)] = l_id

    return category_id, leaf_lookup


def resolve_category_id(cls, category_id, leaf_lookup):
    """Resolves a classify() result dict to a final category_id, falling
    back leaf -> branch -> gender root exactly as load_data.py/
    backfill_categories.py already do (CATEGORY_TREE doesn't give every
    gender every branch, e.g. Unisex historically had only Accessories —
    a product still needs somewhere browsable to land)."""
    cat_id = leaf_lookup.get((cls["gender"], cls["branch"], cls.get("sub"), cls["leaf"]))
    gender_root_id = category_id.get((None, cls["gender"].lower()))
    if cat_id is None:
        branch_slug = re.sub(r"[^a-z]+", "-", cls["branch"].lower())
        cat_id = category_id.get((gender_root_id, branch_slug))
    if cat_id is None:
        cat_id = gender_root_id
    return cat_id
