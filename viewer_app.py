import os
import sqlite3

from flask import Flask, request, g, render_template_string

DB_PATH = r"C:\Work\scraping-init\scraped_data\products.db"
PAGE_SIZE = 48

app = Flask(__name__)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


BASE_CSS = """
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; background: #f4f4f6; color: #1a1a1a; }
  header { background: #16181d; color: white; padding: 14px 20px; position: sticky; top: 0; z-index: 10; }
  header h1 { margin: 0 0 8px 0; font-size: 18px; }
  header form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  header input[type=text] { padding: 7px 10px; border-radius: 6px; border: none; min-width: 220px; }
  header select { padding: 7px 10px; border-radius: 6px; border: none; }
  header button { padding: 7px 14px; border-radius: 6px; border: none; background: #3b82f6; color: white; cursor: pointer; }
  .stats { font-size: 12px; color: #aaa; margin-top: 4px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; padding: 18px; }
  .card { background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.12); display: flex; flex-direction: column; text-decoration: none; color: inherit; }
  .card img { width: 100%; height: 220px; object-fit: cover; background: #e5e5e5; }
  .card .body { padding: 10px 12px; flex: 1; display: flex; flex-direction: column; gap: 4px; }
  .card .store { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: #3b82f6; font-weight: 600; }
  .card .title { font-size: 13px; font-weight: 600; line-height: 1.3; min-height: 34px; }
  .card .price { font-size: 13px; color: #111; margin-top: auto; }
  .card .price .strike { color: #999; text-decoration: line-through; margin-left: 6px; font-size: 11px; }
  .badge-oos { display: inline-block; font-size: 10px; background: #fee2e2; color: #b91c1c; padding: 2px 6px; border-radius: 4px; margin-top: 2px; }
  .pager { display: flex; justify-content: center; gap: 10px; padding: 20px; align-items: center; }
  .pager a, .pager span { padding: 6px 12px; background: white; border-radius: 6px; text-decoration: none; color: #333; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
  .detail { max-width: 900px; margin: 20px auto; background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
  .detail-imgs { display: flex; gap: 10px; overflow-x: auto; margin-bottom: 16px; padding-bottom: 6px; }
  .detail-imgs img { height: 320px; border-radius: 8px; object-fit: cover; flex-shrink: 0; }
  .tag { display: inline-block; background: #eef2ff; color: #3b3bb0; font-size: 11px; padding: 3px 8px; border-radius: 5px; margin: 2px; }
  .back { display: inline-block; margin-bottom: 12px; color: #3b82f6; text-decoration: none; }
  a.storelink { color: #3b82f6; }
</style>
"""

GRID_TEMPLATE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>PK Apparel Scrape Viewer</title>""" + BASE_CSS + """</head>
<body>
<header>
  <h1>PK Apparel Aggregator — Scraped Data Viewer</h1>
  <form method="get" action="/">
    <input type="text" name="q" placeholder="Search title..." value="{{ q }}">
    <select name="store">
      <option value="">All stores</option>
      {% for s in stores %}
        <option value="{{ s.store }}" {% if s.store == store %}selected{% endif %}>{{ s.store_display }} ({{ s.cnt }})</option>
      {% endfor %}
    </select>
    <select name="avail">
      <option value="">Any availability</option>
      <option value="1" {% if avail == '1' %}selected{% endif %}>In stock only</option>
      <option value="0" {% if avail == '0' %}selected{% endif %}>Out of stock only</option>
    </select>
    <button type="submit">Filter</button>
  </form>
  <div class="stats">{{ total }} products matched &middot; page {{ page }} of {{ max_page }} &middot; {{ total_all }} total in database</div>
</header>
<div class="grid">
  {% for p in products %}
  <a class="card" href="/product/{{ p.id }}">
    <img src="{{ p.image_url or '' }}" loading="lazy" onerror="this.style.opacity=0.15">
    <div class="body">
      <div class="store">{{ p.store_display }}</div>
      <div class="title">{{ p.title }}</div>
      {% if not p.available %}<span class="badge-oos">Out of stock</span>{% endif %}
      <div class="price">
        {% if p.price %}Rs. {{ "%.0f"|format(p.price) }}{% endif %}
        {% if p.compare_at_price and p.compare_at_price > p.price %}<span class="strike">Rs. {{ "%.0f"|format(p.compare_at_price) }}</span>{% endif %}
      </div>
    </div>
  </a>
  {% endfor %}
</div>
<div class="pager">
  {% if page > 1 %}<a href="{{ url_for_page(page-1) }}">&laquo; Prev</a>{% endif %}
  <span>{{ page }} / {{ max_page }}</span>
  {% if page < max_page %}<a href="{{ url_for_page(page+1) }}">Next &raquo;</a>{% endif %}
</div>
</body></html>
"""

DETAIL_TEMPLATE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>{{ p.title }}</title>""" + BASE_CSS + """</head>
<body>
<div class="detail">
  <a class="back" href="javascript:history.back()">&laquo; Back</a>
  <div class="detail-imgs">
    {% for img in images %}
    <img src="{{ img }}" onerror="this.style.display='none'">
    {% endfor %}
  </div>
  <div class="store">{{ p.store_display }}</div>
  <h2>{{ p.title }}</h2>
  <p><strong>Price:</strong>
    {% if p.price %}Rs. {{ "%.0f"|format(p.price) }}{% endif %}
    {% if p.compare_at_price and p.compare_at_price > p.price %}<span class="strike">Rs. {{ "%.0f"|format(p.compare_at_price) }}</span>{% endif %}
    &nbsp; {% if not p.available %}<span class="badge-oos">Out of stock</span>{% endif %}
  </p>
  <p><strong>Vendor:</strong> {{ p.vendor or "-" }} &nbsp; <strong>Product type:</strong> {{ p.product_type or "-" }} &nbsp; <strong>Variants:</strong> {{ p.variant_count }} &nbsp; <strong>Images:</strong> {{ p.image_count }}</p>
  <p><strong>Tags:</strong><br>
    {% for t in (p.tags or "").split(",") if t.strip() %}<span class="tag">{{ t.strip() }}</span>{% endfor %}
  </p>
  <p><strong>Description:</strong><br>{{ p.description or "-" }}</p>
  <p><strong>Product ID:</strong> {{ p.product_id }}</p>
  {% if p.product_url %}<p><a class="storelink" href="{{ p.product_url }}" target="_blank">View on store site &rarr;</a></p>{% endif %}
</div>
</body></html>
"""


@app.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    store = request.args.get("store", "").strip()
    avail = request.args.get("avail", "").strip()
    page = max(1, int(request.args.get("page", 1) or 1))

    where = []
    params = []
    if q:
        where.append("title LIKE ?")
        params.append(f"%{q}%")
    if store:
        where.append("store = ?")
        params.append(store)
    if avail in ("0", "1"):
        where.append("available = ?")
        params.append(int(avail))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = db.execute(f"SELECT COUNT(*) c FROM products {where_sql}", params).fetchone()["c"]
    total_all = db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
    max_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, max_page)
    offset = (page - 1) * PAGE_SIZE

    products = db.execute(
        f"SELECT * FROM products {where_sql} ORDER BY id LIMIT ? OFFSET ?",
        params + [PAGE_SIZE, offset],
    ).fetchall()

    stores = db.execute(
        "SELECT store, store_display, COUNT(*) cnt FROM products GROUP BY store ORDER BY store_display"
    ).fetchall()

    def url_for_page(p):
        from urllib.parse import urlencode
        args = {"q": q, "store": store, "avail": avail, "page": p}
        args = {k: v for k, v in args.items() if v}
        return "/?" + urlencode(args)

    return render_template_string(
        GRID_TEMPLATE, products=products, stores=stores, q=q, store=store, avail=avail,
        total=total, total_all=total_all, page=page, max_page=max_page, url_for_page=url_for_page,
    )


@app.route("/product/<int:pid>")
def detail(pid):
    import json as _json
    db = get_db()
    p = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if p is None:
        return "Not found", 404
    try:
        images = _json.loads(p["images_json"]) if p["images_json"] else []
    except (ValueError, TypeError):
        images = []
    if not images and p["image_url"]:
        images = [p["image_url"]]
    return render_template_string(DETAIL_TEMPLATE, p=p, images=images)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
