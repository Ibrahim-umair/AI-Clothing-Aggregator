"""
Idempotently ensures every node in the current CATEGORY_TREE exists in the
categories table — adds anything new (e.g. "Underwear", Boys' plain "Kurta")
without touching or duplicating what's already there. Safe to re-run anytime
the tree gains new leaves; existing rows are matched via
ON CONFLICT (parent_id, slug) / the partial unique index on root slugs.
"""
import re
import psycopg2

from load_data import CATEGORY_TREE

DSN = "host=localhost port=5433 dbname=libas user=libas password=libas_dev_password"


def main():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()

    category_id = {}

    def get_or_make_category(parent_id, name, slug):
        key = (parent_id, slug)
        if key in category_id:
            return category_id[key]
        conflict_target = "(slug) WHERE parent_id IS NULL" if parent_id is None else "(parent_id, slug)"
        cur.execute(
            f"INSERT INTO categories (parent_id, name, slug) VALUES (%s,%s,%s) "
            f"ON CONFLICT {conflict_target} DO UPDATE SET name=EXCLUDED.name RETURNING id",
            (parent_id, name, slug),
        )
        cid = cur.fetchone()[0]
        category_id[key] = cid
        return cid

    before = cur.execute("SELECT COUNT(*) FROM categories") or None
    cur.execute("SELECT COUNT(*) FROM categories")
    before_count = cur.fetchone()[0]

    for gender, branches in CATEGORY_TREE.items():
        g_id = get_or_make_category(None, gender, gender.lower())
        for branch, content in branches.items():
            b_id = get_or_make_category(g_id, branch, re.sub(r"[^a-z]+", "-", branch.lower()))
            if isinstance(content, dict):
                for sub, leaves in content.items():
                    s_id = get_or_make_category(b_id, sub, re.sub(r"[^a-z]+", "-", sub.lower()))
                    for name, slug in leaves:
                        get_or_make_category(s_id, name, slug)
            else:
                for name, slug in content:
                    get_or_make_category(b_id, name, slug)

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM categories")
    after_count = cur.fetchone()[0]
    print(f"Categories before: {before_count}, after: {after_count} (added {after_count - before_count})")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
