"""
Side-by-side page: the same products through two models (e.g. Luna batch run vs
an OpenRouter model). Rows that differ are highlighted; per product you pick
which model did better. Verdicts stay in the browser and export as JSON.

    python export_model_compare.py --a results_r5.json --b results_r5_deepseek-v4.1-flash-1017.json \
        --name-a "GPT-6 Luna" --name-b "DeepSeek V4.1 Flash"
Output: review-exports/model-compare/index.html
"""
import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "local-notes" / "enrich_v3_test"
OUT = ROOT / "review-exports" / "model-compare" / "index.html"


def e(s):
    return html.escape(str(s))


def color_text(v):
    """One colour version: main, big secondary areas, then small details with where
    they sit. Older runs only had a flat "accents" list."""
    out = v["main_color"]
    if v.get("secondary"):
        out += " + " + ", ".join(s if isinstance(s, str) else f'{s["color"]} ({s["share"]})'
                                 for s in v["secondary"])
    if v.get("accents"):
        out += " + " + ", ".join(v["accents"])
    if v.get("details"):
        out += " · details: " + ", ".join(f'{d["color"]} {d["where"]}' for d in v["details"])
    return out + f' ({v["pattern"]})'


def rows(res):
    d, c, a = res["descriptors"], res["category"], res["audience"]
    dl = d["dress_level"]
    cov = d["coverage"]
    emb = d["embellishment"]
    return [
        ("Category", f'{c["path"]} ({c["confidence"]})' + (f' — {c["reason"]}' if c["reason"] else "")),
        ("Gender", f'{a["value"]} ({a["confidence"]})'),
        ("Looks like", res["looks_like"]),
        ("Not apparel", "yes" if res["not_apparel"] else "no"),
        ("Dress level", dl["from"] if dl["from"] == dl["to"] else f'{dl["from"]} → {dl["to"]}'),
        ("Embellishment", f'{emb["level"]}' + (f' · {", ".join(emb["work"])}' if emb["work"] else "")),
        ("Warmth / seasons", f'{d["warmth"]} · {", ".join(d["seasons"]) or "none"}'),
        ("Fabric", d["fabric"] or "unknown"),
        ("Fit / closure", f'{d["fit"]} · {d["closure"]}'),
        ("Coverage", f'sleeves {cov["sleeves"]} · length {cov["length"]} · neck {cov["neckline"]} · '
                     f'{cov["sheerness"]} · slit {cov["slit"]}'),
        ("Colours", "; ".join(color_text(v) for v in res["versions"]) or "none"),
        ("Activities", ", ".join(d["activities"]) or "none"),
        ("Style", ", ".join(d["style"]) or "none"),
        ("Comfort / care", f'{", ".join(d["comfort"]) or "none"} · {", ".join(d["care"]) or "none"}'),
        ("Description", res["description"]),
        ("Tags", ", ".join(res["tags"])),
    ]


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Model Comparison</title>
<style>
:root{--ink:#1d1d1b;--muted:#6b6a64;--line:#e3e1d9;--paper:#f7f6f2;--olive:#5b6b2f;--soft:#eef1e4;--diff:#fbf1dc}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--paper);border-bottom:1px solid var(--line);padding:12px 16px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
header h1{font-size:17px;margin:0 12px 0 0}.muted{color:var(--muted)}
button{font:inherit;padding:6px 12px;border:1px solid var(--line);background:#fff;border-radius:6px;cursor:pointer}
button.on{background:var(--olive);color:#fff;border-color:var(--olive)}
main{max-width:1240px;margin:0 auto;padding:16px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;margin:0 0 18px;padding:16px}
.photos{display:flex;gap:6px;overflow-x:auto;margin:10px 0}.photos img{height:200px;border-radius:6px;border:1px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;vertical-align:top;padding:6px 8px;border-top:1px solid var(--line)}
th{width:140px;color:var(--muted);font-weight:500}td{min-width:200px}
tr.diff td{background:var(--diff)}thead th,thead td{font-weight:600;color:var(--ink);background:var(--soft)}
.verdict{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
textarea{width:100%;margin-top:8px;font:inherit;border:1px solid var(--line);border-radius:6px;padding:6px;min-height:36px}
.sum{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:16px}
</style></head><body>
<header><h1>__A__ vs __B__</h1><span class="muted" id="stat"></span><button id="exp">Download my verdicts</button></header>
<main><div class="sum">__SUMMARY__</div>__CARDS__</main>
<script>
const KEY="libas-model-compare-__KEY__";let s={};try{s=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(s))}catch(e){}stat()}
function stat(){const v=Object.values(s).map(x=>x.v).filter(Boolean);const c={};v.forEach(x=>c[x]=(c[x]||0)+1);
document.getElementById("stat").textContent=`${v.length}/__N__ judged · `+Object.entries(c).map(([k,n])=>`${k}: ${n}`).join(" · ")}
document.querySelectorAll(".card").forEach(card=>{const id=card.dataset.id;s[id]=s[id]||{};
 card.querySelectorAll(".verdict button").forEach(b=>{if(s[id].v===b.dataset.v)b.classList.add("on");
  b.onclick=()=>{s[id].v=s[id].v===b.dataset.v?null:b.dataset.v;card.querySelectorAll(".verdict button").forEach(x=>x.classList.toggle("on",x.dataset.v===s[id].v));save()}});
 const t=card.querySelector("textarea");t.value=s[id].note||"";t.oninput=()=>{s[id].note=t.value;save()}});
document.getElementById("exp").onclick=()=>{const a=document.createElement("a");
 a.href=URL.createObjectURL(new Blob([JSON.stringify(s,null,1)],{type:"application/json"}));a.download="libas-model-compare.json";a.click()};
stat();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, metavar="NAME=FILE",
                    help="one per model, e.g. --run \"GPT-6 Luna=results_r6_gpt-6-luna.json\"")
    args = ap.parse_args()
    runs = []
    for spec in args.run:
        name, _, fname = spec.partition("=")
        rs = {r["product"]["id"]: r for r in json.loads((DIR / fname).read_text(encoding="utf-8")) if "result" in r}
        runs.append((name, rs))
    ids = [i for i in runs[0][1] if all(i in rs for _, rs in runs)]
    names = [n for n, _ in runs]
    cards, diff_rows, total_rows = [], 0, 0
    for pid in ids:
        p = runs[0][1][pid]["product"]
        sent = set(runs[0][1][pid]["photos_sent"])
        photos = "".join(f'<img loading="lazy" src="{e(u)}" alt="">' for n, u in enumerate(p["photos"], 1) if n in sent)
        per_model = [rows(rs[pid]["result"]) for _, rs in runs]
        body = []
        for j, (label, _) in enumerate(per_model[0]):
            vals = [m[j][1] for m in per_model]
            diff = len({v.strip().lower() for v in vals}) > 1
            total_rows += 1
            diff_rows += diff
            body.append(f'<tr class="{"diff" if diff else ""}"><th>{e(label)}</th>' + "".join(f"<td>{e(v)}</td>" for v in vals) + "</tr>")
            if label == "Category":  # show reasons on their own row, not glued to the category
                rsn = [rs[pid]["result"]["category"]["reason"] or "" for _, rs in runs]
                if any(rsn):
                    body.append('<tr><th>Category reason</th>' + "".join(f'<td class="muted">{e(r)}</td>' for r in rsn) + "</tr>")
        head = "".join(f'<td>{e(n)} <span class="muted">({rs[pid]["usage"]["out"]} out, ${rs[pid]["usage"].get("cost", 0):.5f})</span></td>'
                       for n, rs in runs)
        buttons = "".join(f'<button data-v="{e(n)}">{e(n)}</button>' for n in names)
        cards.append(
            f'<section class="card" data-id="{pid}"><b>{e(p["title"])}</b> <span class="muted">· {e(p["brand"])} · '
            f'rules said {e(p["category"])} · <a href="{e(p["url"])}" target="_blank" rel="noopener">store ↗</a></span>'
            f'<div class="photos">{photos}</div><div style="overflow-x:auto"><table><thead><tr><th></th>{head}</tr></thead>'
            f'{"".join(body)}</table></div>'
            f'<div class="verdict">Best here: {buttons}<button data-v="same">All about the same</button></div>'
            f'<textarea placeholder="Note (optional)"></textarea></section>')
    cost = lambda rs: sum(rs[i]["usage"].get("cost", 0) for i in ids) / len(ids)
    summary = (f"{len(ids)} products, same prompt for every model. Highlighted rows differ between models "
               f"({diff_rows} of {total_rows}). Measured cost per product without Batch: "
               + "; ".join(f"{e(n)} ${cost(rs):.6f} (~${cost(rs) * 45693:.0f} for all in-stock)" for n, rs in runs))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    page = (PAGE.replace("__CARDS__", "".join(cards)).replace("__SUMMARY__", summary)
            .replace("__A__ vs __B__", " vs ".join(e(n) for n in names)).replace("__N__", str(len(ids)))
            .replace("__KEY__", "-".join(names)))
    OUT.write_text(page, encoding="utf-8")
    print(summary, "->", OUT)


if __name__ == "__main__":
    main()
