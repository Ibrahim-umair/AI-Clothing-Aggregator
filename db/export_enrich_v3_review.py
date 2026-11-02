"""
Builds the review page for the enrichment test run (enrich_v3_test.py):
review-exports/enrich-v3-test/index.html. One card per product: every photo
sent, the store's text, and what the model returned, with a right/wrong
toggle per area. Verdicts stay in the browser (localStorage) and are exported
as libas-enrich-v3-review.json.

    python export_enrich_v3_review.py
"""
import argparse

from export_model_compare import color_text
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "local-notes" / "enrich_v3_test" / "results.json"
OUT = ROOT / "review-exports" / "enrich-v3-test" / "index.html"

AREAS = ["Category", "Gender", "Dress level", "Embellishment", "Coverage", "Warmth & season",
         "Colours", "Description & tags"]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Enrichment Test Review</title>
<style>
:root { --ink:#1d1d1b; --muted:#6b6a64; --line:#e3e1d9; --paper:#f7f6f2; --card:#fff;
        --olive:#5b6b2f; --olive-soft:#eef1e4; --bad:#8a5a00; --bad-soft:#fbf1dc; }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:14px/1.45 system-ui, sans-serif; }
header { position:sticky; top:0; z-index:5; background:var(--paper); border-bottom:1px solid var(--line);
         padding:12px 16px; display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
header h1 { font-size:17px; margin:0 12px 0 0; }
header .stat { color:var(--muted); }
button, select { font:inherit; padding:6px 12px; border:1px solid var(--line); background:#fff; border-radius:6px; cursor:pointer; }
button.primary { background:var(--olive); color:#fff; border-color:var(--olive); }
main { max-width:1180px; margin:0 auto; padding:16px; }
.intro { color:var(--muted); margin:0 0 16px; max-width:820px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; margin:0 0 18px; padding:16px; }
.card.done { border-color:var(--olive); }
.top { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }
.top h2 { font-size:16px; margin:0; }
.top a { color:var(--olive); }
.meta { color:var(--muted); font-size:13px; }
.photos { display:flex; gap:6px; overflow-x:auto; margin:12px 0; padding-bottom:4px; }
.photos figure { margin:0; flex:0 0 auto; text-align:center; font-size:11px; color:var(--muted); }
.photos img { height:220px; border-radius:6px; border:1px solid var(--line); display:block; cursor:zoom-in; }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(330px, 1fr)); gap:10px; }
.area { border:1px solid var(--line); border-radius:8px; padding:10px; }
.area.ok { background:var(--olive-soft); border-color:var(--olive); }
.area.bad { background:var(--bad-soft); border-color:var(--bad); }
.area h3 { font-size:13px; margin:0 0 6px; display:flex; justify-content:space-between; align-items:center; }
.area h3 span button { padding:2px 9px; margin-left:4px; }
.kv { margin:2px 0; }
.kv b { color:var(--muted); font-weight:500; }
.chg { color:var(--bad); font-weight:600; }
.tag { display:inline-block; border:1px solid var(--line); border-radius:12px; padding:1px 8px; margin:2px 3px 0 0; font-size:12px; }
.storetext { color:var(--muted); font-size:12px; max-height:90px; overflow:auto; margin-top:6px; }
textarea { width:100%; margin-top:10px; font:inherit; border:1px solid var(--line); border-radius:6px; padding:6px; min-height:38px; }
.lightbox { position:fixed; inset:0; background:rgba(0,0,0,.85); display:none; align-items:center; justify-content:center; z-index:10; }
.lightbox img { max-width:95vw; max-height:95vh; }
@media (max-width:600px) { .photos img { height:160px; } }
</style></head><body>
<header>
  <h1>Enrichment test __ROUND__: __N__ products</h1>
  <span class="stat" id="stat"></span>
  <select id="filter"><option value="all">Show all</option><option value="todo">Not checked yet</option>
    <option value="bad">Has a wrong area</option></select>
  <button class="primary" id="export">Download my verdicts</button>
</header>
<main>
<p class="intro">Each card shows every photo the AI saw, then what it returned. Mark each area
<b>✓</b> right or <b>✗</b> wrong, judging by the photos, and add a note when something is off.
Areas that don't apply (e.g. dress level on a perfume) can be left alone. Your marks stay in this
browser; "Download my verdicts" saves them as a file for me. Click a photo to enlarge it.</p>
<div id="cards"></div>
</main>
<div class="lightbox" id="lb"><img id="lbimg" alt=""></div>
<script>
const DATA = __DATA__;
const AREAS = __AREAS__;
const KEY = "libas-enrich-v3-review__SFX__";
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} stat(); }
function stat() {
  const n = DATA.length;
  const done = DATA.filter(d => Object.keys((state[d.id] || {}).areas || {}).length).length;
  const bad = DATA.filter(d => Object.values((state[d.id] || {}).areas || {}).includes("bad")).length;
  document.getElementById("stat").textContent = `${done}/${n} checked · ${bad} with a wrong area`;
}
function render() {
  const f = document.getElementById("filter").value;
  document.querySelectorAll(".card").forEach(c => {
    const s = state[c.dataset.id] || {}; const a = Object.values(s.areas || {});
    c.classList.toggle("done", a.length > 0);
    c.style.display = (f === "all" || (f === "todo" && !a.length) || (f === "bad" && a.includes("bad"))) ? "" : "none";
  });
}
document.getElementById("cards").innerHTML = DATA.map(d => d.html).join("");
document.querySelectorAll(".area").forEach(el => {
  const id = el.closest(".card").dataset.id, area = el.dataset.area;
  const v = ((state[id] || {}).areas || {})[area]; if (v) el.classList.add(v);
  el.querySelectorAll("button").forEach(b => b.onclick = () => {
    state[id] = state[id] || {areas: {}}; state[id].areas = state[id].areas || {};
    const cur = state[id].areas[area];
    el.classList.remove("ok", "bad");
    if (cur === b.dataset.v) delete state[id].areas[area]; else { state[id].areas[area] = b.dataset.v; el.classList.add(b.dataset.v); }
    save(); render();
  });
});
document.querySelectorAll("textarea").forEach(t => {
  const id = t.closest(".card").dataset.id; t.value = (state[id] || {}).note || "";
  t.oninput = () => { state[id] = state[id] || {areas: {}}; state[id].note = t.value; save(); };
});
document.querySelectorAll(".photos img").forEach(i => i.onclick = () => {
  document.getElementById("lbimg").src = i.src; document.getElementById("lb").style.display = "flex"; });
document.getElementById("lb").onclick = () => document.getElementById("lb").style.display = "none";
document.getElementById("filter").onchange = render;
document.getElementById("export").onclick = () => {
  const out = DATA.map(d => ({id: d.id, title: d.title, ...(state[d.id] || {})}));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {type: "application/json"}));
  a.download = "libas-enrich-v3-review__SFX__.json"; a.click();
};
stat(); render();
</script></body></html>"""


def e(s):
    return html.escape(str(s))


def kv(label, value, changed=False):
    cls = ' class="chg"' if changed else ""
    return f'<div class="kv"><b>{e(label)}:</b> <span{cls}>{e(value)}</span></div>'


def tags(items):
    return "".join(f'<span class="tag">{e(t)}</span>' for t in items) or '<span class="meta">none</span>'


def area(name, body):
    return (f'<div class="area" data-area="{e(name)}"><h3>{e(name)}<span>'
            f'<button data-v="ok" title="right">✓</button><button data-v="bad" title="wrong">✗</button>'
            f'</span></h3>{body}</div>')


def card(r):
    p, res = r["product"], r["result"]
    d, cat, aud = res["descriptors"], res["category"], res["audience"]
    sent = set(r["photos_sent"])
    photos = "".join(f'<figure><img loading="lazy" src="{e(u)}" alt="photo {n}"><figcaption>Photo {n}</figcaption></figure>'
                     for n, u in enumerate(p["photos"], 1) if n in sent)
    new_path = cat["path"]
    cat_body = (kv("Before (keyword rules)", p["category"] + ("  · reviewed by you" if p["reviewed"] else ""))
                + kv("AI picks", new_path, changed=new_path != p["category"])
                + kv("Confidence", cat["confidence"]) + kv("Why", cat["reason"])
                + (kv("Proposed new", cat["proposed_new"]) if cat["proposed_new"] else "")
                + kv("Looks like", res["looks_like"]) + kv("Not apparel", "yes" if res["not_apparel"] else "no"))
    old_gender = p["category"].split(" > ")[0]
    gen_body = (kv("Before", old_gender) + kv("AI", aud["value"], changed=aud["value"] != old_gender)
                + kv("Confidence", aud["confidence"]) + kv("Why", aud["reason"]))
    dl = d["dress_level"]
    dress = dl["from"] if dl["from"] == dl["to"] else f'{dl["from"]} → {dl["to"]}'
    dress_body = kv("Dress level", dress) + kv("Fit", d["fit"]) + kv("Closure", d["closure"]) \
        + '<div class="kv"><b>Activities:</b> ' + tags(d["activities"]) + '</div>' \
        + '<div class="kv"><b>Style:</b> ' + tags(d["style"]) + '</div>'
    emb = d["embellishment"]
    emb_body = kv("Level", emb["level"]) + '<div class="kv"><b>Work:</b> ' + tags(emb["work"]) + '</div>'
    cov = d["coverage"]
    cov_body = (kv("Sleeves", cov["sleeves"]) + kv("Length", cov["length"]) + kv("Neckline", cov["neckline"])
                + kv("Sheerness", cov["sheerness"]) + kv("Slit", cov["slit"]))
    warm_body = (kv("Warmth", d["warmth"]) + kv("Seasons", ", ".join(d["seasons"]) or "none")
                 + kv("Fabric", d["fabric"] or "unknown")
                 + '<div class="kv"><b>Comfort:</b> ' + tags(d["comfort"]) + '</div>'
                 + '<div class="kv"><b>Care:</b> ' + tags(d["care"]) + '</div>')
    versions = "".join(
        kv(f"Version {i}", color_text(v) + f' · photos {", ".join(map(str, v["photos"]))}')
        for i, v in enumerate(res["versions"]))
    store_colors = ", ".join(f'{c["name"]}{"" if c["in_stock"] else " (sold out)"}' for c in p["colors"]) or "none given"
    mapping = ", ".join(f'{m["store_color"]} → {"?" if m["version"] < 0 else "version " + str(m["version"])}'
                        for m in res["color_map"]) or "none"
    col_body = versions + kv("Store colour names", store_colors) + kv("Mapped", mapping)
    desc_body = f'<div class="kv">{e(res["description"])}</div><div class="kv">{tags(res["tags"])}</div>'
    body = "".join([area("Category", cat_body), area("Gender", gen_body), area("Dress level", dress_body),
                    area("Embellishment", emb_body), area("Coverage", cov_body),
                    area("Warmth & season", warm_body), area("Colours", col_body),
                    area("Description & tags", desc_body)])
    store_text = e((p["description"] or "(no store description)")[:700])
    return (f'<section class="card" data-id="{p["id"]}"><div class="top"><div><h2>{e(p["title"])}</h2>'
            f'<div class="meta">{e(p["brand"])} · #{p["id"]} · {len(sent)} photos sent</div></div>'
            f'<div><a href="{e(p["url"])}" target="_blank" rel="noopener">Open on store ↗</a></div></div>'
            f'<div class="photos">{photos}</div><div class="grid">{body}</div>'
            f'<div class="storetext"><b>Store text:</b> {store_text}</div>'
            f'<textarea placeholder="Note (optional)"></textarea></section>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="", help="e.g. r2 (round 1 used none)")
    args = ap.parse_args()
    sfx = f"_{args.round}" if args.round else ""
    results_file = RESULTS.with_name(f"results{sfx}.json")
    out = OUT.parent.with_name(f"enrich-v3-test{'-' + args.round if args.round else ''}") / "index.html"
    results = [r for r in json.loads(results_file.read_text(encoding="utf-8")) if "result" in r]
    data = [{"id": r["product"]["id"], "title": r["product"]["title"], "html": card(r)} for r in results]
    out.parent.mkdir(parents=True, exist_ok=True)
    page = (PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
                .replace("__AREAS__", json.dumps(AREAS)).replace("__ROUND__", args.round or "r1")
                .replace("__N__", str(len(data))).replace("__SFX__", sfx))
    out.write_text(page, encoding="utf-8")
    print(f"{len(data)} products -> {out}")


if __name__ == "__main__":
    main()
