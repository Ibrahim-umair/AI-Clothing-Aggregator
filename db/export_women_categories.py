"""
Builds a local photo page of the whole Women category tree
(review-exports/women-categories/index.html): sample photos for every
category, plus side-by-side comparisons of the categories that may be the
same thing or that overlap at the border. Read-only; re-run any time.

    python export_women_categories.py
"""
import html
from pathlib import Path

import psycopg2

from embed_products import build_category_paths
from load_data import DSN

OUT = Path(__file__).resolve().parent.parent / "review-exports" / "women-categories" / "index.html"
WOMEN = 39
EASTERN_SAMPLES, OTHER_SAMPLES, COMPARE_SAMPLES = 18, 8, 12

# (title, question, [(label, where-clause), ...]). Clauses run against products p.
COMPARES = [
    ("Kurta vs Kurti", "Your mom says these are the same. Do the photos agree?", [
        ("Kurta (single piece)", "p.category_id = 3289 AND p.title !~* 'dupatta|trouser|shalwar'"),
        ("Kurti", "p.category_id = 59")]),
    ("Kurta Set vs Shalwar Kameez", "Your mom says these are the same. Do the photos agree?", [
        ("Kurta Set", "p.category_id = 3732"),
        ("Shalwar Kameez", "p.category_id = 60")]),
    ("Unstitched 3-Piece vs Suit", "Your mom says these are almost the same thing.", [
        ("3-Piece", "p.category_id = 64"),
        ("Suit", "p.category_id = 766")]),
    ("Unstitched 2-Piece: the two kinds", "Your mom says a 2-piece is either shirt + dupatta or shirt + shalwar.", [
        ("Shirt + Dupatta (title says dupatta)", "p.category_id = 63 AND p.title ~* 'dupatta' AND p.title !~* 'shalwar|trouser|pant|bottom'"),
        ("Shirt + Shalwar/Trouser (title says a bottom)", "p.category_id = 63 AND p.title ~* 'shalwar|trouser|pant|bottom' AND p.title !~* 'dupatta'")]),
    ("Sets filed under Kurta", "Titles name a dupatta or trouser, so these are sets, but the rules filed them as Kurta.", [
        ("Kurta, title says dupatta or trouser", "p.category_id = 3289 AND p.title ~* 'dupatta|trouser|shalwar'")]),
    ("Winter 3-Piece with a shawl", "Shawl instead of a dupatta. Still a 3-piece?", [
        ("3-Piece, title says shawl", "p.category_id = 64 AND p.title ~* 'shawl'")]),
    ("Kurti vs Tunic (filed under Western Top)", "Is a tunic a kurti, or a Western top?", [
        ("Kurti", "p.category_id = 59"),
        ("Western Top, title says tunic", "p.category_id = 43 AND p.title ~* 'tunic'")]),
    ("Eastern trousers filed under Western Trouser", "Trousers sold to wear with a kurta sit under Western > Trouser.", [
        ("Shalwar & Pajama (Eastern)", "p.category_id = 6977"),
        ("Western Trouser, looks Eastern", "p.category_id = 49 AND p.title ~* 'cambric|lawn|lace|embroider|block print|shalwar|dyed'")]),
    ("Eastern suits filed under Western Co-ord Set", "Matching Eastern 2 or 3-piece outfits sit under Western > Co-ord Set.", [
        ("Kurta Set (Eastern)", "p.category_id = 3732"),
        ("Western Co-ord Set, title says suit", "p.category_id = 53 AND p.title ~* 'suit'")]),
    ("Dupatta vs Shawl", "Dupatta sits under Eastern, Shawl under Accessories.", [
        ("Dupatta", "p.category_id = 6980"),
        ("Shawl", "p.category_id = 70")]),
]

STOCK = "EXISTS (SELECT 1 FROM variants v WHERE v.product_id = p.id AND v.current_available)"

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Women Categories</title>
<style>
:root { --ink:#1d1d1b; --muted:#6b6a64; --line:#e3e1d9; --paper:#f7f6f2; --card:#fff;
        --olive:#5b6b2f; --olive-soft:#eef1e4; }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:14px/1.45 system-ui, sans-serif; }
header { position:sticky; top:0; z-index:5; background:var(--paper); border-bottom:1px solid var(--line);
         padding:10px 16px; display:flex; gap:14px; flex-wrap:wrap; align-items:center; }
header h1 { font-size:17px; margin:0 8px 0 0; }
header a { color:var(--olive); text-decoration:none; }
main { max-width:1180px; margin:0 auto; padding:16px; }
.intro { color:var(--muted); margin:0 0 16px; max-width:820px; }
h2.part { font-size:20px; margin:28px 0 4px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; margin:0 0 18px; padding:16px; }
.card h3 { font-size:16px; margin:0; }
.q { color:var(--olive); margin:2px 0 8px; }
.meta { color:var(--muted); font-size:13px; }
.cols { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:14px; }
.col h4 { font-size:14px; margin:6px 0 2px; }
.tiles { display:grid; grid-template-columns:repeat(auto-fill, minmax(130px, 1fr)); gap:8px; margin-top:8px; }
.tile { font-size:11px; color:var(--muted); }
.tile img { width:100%; aspect-ratio:3/4; object-fit:cover; border-radius:6px; border:1px solid var(--line);
            display:block; background:var(--paper); cursor:zoom-in; }
.tile a { color:var(--ink); text-decoration:none; display:block; margin-top:3px; line-height:1.3; }
.tile .out { color:#9a958a; }
.none { color:var(--muted); font-style:italic; }
details > summary { cursor:pointer; font-weight:600; font-size:16px; }
details.card[open] > summary { margin-bottom:6px; }
.lightbox { position:fixed; inset:0; background:rgba(0,0,0,.85); display:none; align-items:center; justify-content:center; z-index:10; }
.lightbox img { max-width:95vw; max-height:95vh; }
</style></head><body>
<header><h1>Women categories</h1>
  <a href="#compare">Questions for your mom</a><a href="#eastern">Eastern</a><a href="#western">Western</a><a href="#other">Accessories &amp; other</a></header>
<main>
<p class="intro">Photos are a random sample from each category, spread across stores, in-stock
products first. Greyed names are sold out. Counts are all products listed / in stock.
Click a photo to enlarge it, click a name to open the store page.</p>
__BODY__
</main>
<div class="lightbox" id="lb"><img id="lbimg" alt=""></div>
<script>
document.querySelectorAll(".tile img").forEach(i => i.onclick = () => {
  document.getElementById("lbimg").src = i.dataset.big || i.src; document.getElementById("lb").style.display = "flex"; });
document.getElementById("lb").onclick = () => document.getElementById("lb").style.display = "none";
</script></body></html>"""


def e(s):
    return html.escape(str(s or ""))


def small(url):
    """Shopify's CDN resizes on request; other hosts get the original."""
    if url and ("cdn.shopify.com" in url or "/cdn/shop/" in url):
        return url + ("&" if "?" in url else "?") + "width=300"
    return url


def counts(cur, where):
    cur.execute(f"""SELECT b.name, count(*), count(*) FILTER (WHERE {STOCK})
                    FROM products p JOIN brands b ON b.id = p.brand_id
                    WHERE p.is_active AND {where} GROUP BY 1""")
    rows = cur.fetchall()
    return sum(r[1] for r in rows), sum(r[2] for r in rows), {r[0]: r[1] for r in rows}


def sample(cur, where, n):
    """Round-robin across stores, in-stock first, stable order between runs."""
    cur.execute(f"""
        SELECT id, title, store, url, img, instock FROM (
          SELECT p.id, p.title, b.name store, b.base_url || '/products/' || p.handle url,
                 (SELECT i.url FROM product_images i WHERE i.product_id = p.id ORDER BY position LIMIT 1) img,
                 {STOCK} instock,
                 row_number() OVER (PARTITION BY b.name ORDER BY {STOCK} DESC, md5(p.id::text)) rn
          FROM products p JOIN brands b ON b.id = p.brand_id
          WHERE p.is_active AND {where}) x
        WHERE img IS NOT NULL ORDER BY rn, instock DESC, store LIMIT %s""", (n,))
    return cur.fetchall()


def stats_line(total, instock, stores):
    by_store = ", ".join(f"{s} {n:,}" for s, n in sorted(stores.items(), key=lambda kv: -kv[1]))
    return f"{total:,} listed · {instock:,} in stock" + (f" · {by_store}" if by_store else "")


def tiles(rows):
    if not rows:
        return '<p class="none">No products.</p>'
    out = []
    for pid, title, store, url, img, instock in rows:
        cls = "" if instock else ' class="out"'
        out.append(f'<div class="tile"><img loading="lazy" src="{e(small(img))}" data-big="{e(img)}" alt="">'
                   f'<a href="{e(url)}" target="_blank"{cls}>{e(title)}</a>{e(store)}</div>')
    return '<div class="tiles">' + "".join(out) + "</div>"


def group(cur, label, where, n, tag="h4"):
    total, instock, stores = counts(cur, where)
    return (f'<div class="col"><{tag}>{e(label)}</{tag}><div class="meta">{stats_line(total, instock, stores)}</div>'
            f'{tiles(sample(cur, where, n))}</div>')


def main():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    paths = build_category_paths(cur)
    women = {cid: p for cid, p in paths.items() if p.startswith("Women > ")}
    leaves = sorted(cid for cid in women if not any(o.startswith(women[cid] + " > ") for o in women.values()))

    body = ['<h2 class="part" id="compare">Questions for your mom</h2>'
            '<p class="intro">Categories that may be the same thing, and products that sit on a border '
            'between two categories. No product in our stores today is sold as a 4-piece (shirt, dupatta, '
            'shalwar and inner), so there is nothing to show for that one.</p>']
    for title, question, groups in COMPARES:
        cols = "".join(group(cur, label, where, COMPARE_SAMPLES) for label, where in groups)
        body.append(f'<div class="card"><h3>{e(title)}</h3><p class="q">{e(question)}</p>'
                    f'<div class="cols">{cols}</div></div>')

    sections = [("eastern", "Eastern", "Women > Eastern > ", EASTERN_SAMPLES, True),
                ("western", "Western", "Women > Western > ", OTHER_SAMPLES, False),
                ("other", "Accessories & other", None, OTHER_SAMPLES, False)]
    for anchor, name, prefix, n, open_ in sections:
        body.append(f'<h2 class="part" id="{anchor}">{e(name)}</h2>')
        for cid in leaves:
            path = women[cid]
            in_section = path.startswith(prefix) if prefix else not path.startswith(("Women > Eastern", "Women > Western"))
            if not in_section:
                continue
            short = path.removeprefix("Women > ")
            if prefix:
                short = path.removeprefix(prefix)
            total, instock, stores = counts(cur, f"p.category_id = {cid}")
            inner = (f'<div class="meta">{stats_line(total, instock, stores)}</div>'
                     f'{tiles(sample(cur, f"p.category_id = {cid}", n))}')
            body.append(f'<details class="card"{" open" if open_ else ""}><summary>{e(short)} '
                        f'<span class="meta">({total:,} / {instock:,} in stock)</span></summary>{inner}</details>')

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(PAGE.replace("__BODY__", "\n".join(body)), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
