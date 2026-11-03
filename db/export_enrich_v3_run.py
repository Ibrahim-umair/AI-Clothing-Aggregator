"""
Review page for a batch run of enrich_v3.py, built from ai_enrichment:
review-exports/enrich-v3-run-<run>/index.html.

Each product shows the photos the AI saw, what it returned, and what the apply
step does with it (enrich_v3.decide, the same function apply uses): where the
AI overturns the keyword rules, where it disagrees but isn't sure enough,
where it disagrees with a category you reviewed, what it would hide, and
answers that failed the checks. Works before and after apply (after apply,
"before" is the category saved for undo). Verdicts stay in the browser and
download as a file, like the test-round page.

    python export_enrich_v3_run.py --run pilot
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

import psycopg2

import enrich_v3 as run
import enrich_v3_test as t
import export_enrich_v3_review as review
from embed_products import build_category_paths
from enrich_products import resized
from load_data import DSN

ROOT = Path(__file__).resolve().parent.parent
STYLE = re.search(r"<style>(.*?)</style>", review.PAGE, re.S).group(1)

GROUPS = [  # (action, chip label, banner text) in page order
    ("moved", "AI overturned the rules", "AI overturns the keyword rules: the product moves"),
    ("reviewed_wins", "AI disagrees with your review", "AI disagrees with a category you reviewed: yours stays"),
    ("flagged", "AI disagrees, not sure", "AI disagrees but isn't sure: the rules' category stays"),
    ("hidden", "Not apparel (hidden)", "AI says this isn't apparel: it gets hidden"),
    ("invalid", "Answer failed checks", "The answer failed the checks: apply skips it"),
    ("agrees", "AI agrees", "AI agrees with the current category"),
]
LABEL = {a: (chip, banner) for a, chip, banner in GROUPS}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Enrichment Run Check</title>
<style>__STYLE__
.chips { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 14px; }
.chip { border-radius:16px; padding:5px 12px; }
.chip.on { background:var(--ink); color:#fff; border-color:var(--ink); }
.chip b { margin-left:4px; }
.banner { margin:10px 0 0; padding:8px 10px; border-radius:8px; background:var(--olive-soft); }
.banner.moved, .banner.reviewed_wins, .banner.hidden, .banner.invalid { background:var(--bad-soft); }
.banner .path { font-weight:600; }
.moves { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 16px; margin:0 0 18px; }
.moves h2 { font-size:15px; margin:0 0 8px; }
.moves table { border-collapse:collapse; width:100%; font-size:13px; }
.moves td { padding:3px 6px; border-top:1px solid var(--line); vertical-align:top; }
.moves td.n { text-align:right; width:40px; font-variant-numeric:tabular-nums; }
.moves tr { cursor:pointer; } .moves tr:hover td { background:var(--olive-soft); }
.moves tr.on td { background:var(--olive-soft); font-weight:600; }
.failed { color:var(--muted); font-size:13px; }
</style></head><body>
<header>
  <h1>Run "__RUN__": __N__ answers</h1>
  <span class="stat" id="stat"></span>
  <select id="store"><option value="">All stores</option>__STORES__</select>
  <select id="mine"><option value="all">Checked or not</option><option value="todo">Not checked yet</option>
    <option value="bad">Marked wrong</option></select>
  <label><input type="checkbox" id="gender"> Gender changed only</label>
  <button class="primary" id="export">Download my verdicts</button>
</header>
<main>
<p class="intro">Each card shows the photos the AI saw (at the size it saw them), what it returned, and
what the apply step does with it. Nothing on this page has been written to the products unless you
ran apply. Mark each area <b>✓</b> right or <b>✗</b> wrong by the photos; "Download my verdicts"
saves them as a file for me. Click a photo to enlarge it, or a row in the moves table to see those products.</p>
<div class="chips" id="chips"></div>
<div class="moves"><h2>Category moves (rules → AI), for moved and flagged</h2><table>__MOVES__</table></div>
<div id="cards"></div>
__FAILED__
</main>
<div class="lightbox" id="lb"><img id="lbimg" alt=""></div>
<script>
const DATA = __DATA__;
const GROUPS = __GROUPS__;
const KEY = "libas-enrich-v3-run-__RUN__";
let state = {}, group = "", move = "";
try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} stat(); }
function areas(id) { return Object.values((state[id] || {}).areas || {}); }
function stat() {
  const done = DATA.filter(d => areas(d.id).length).length;
  const bad = DATA.filter(d => areas(d.id).includes("bad")).length;
  document.getElementById("stat").textContent = `${done}/${DATA.length} checked · ${bad} with a wrong area`;
}
function chips() {
  const n = a => DATA.filter(d => !a || d.action === a).length;
  document.getElementById("chips").innerHTML =
    [["", "All"], ...GROUPS].filter(([a]) => n(a)).map(([a, label]) =>
      `<button class="chip${a === group ? " on" : ""}" data-a="${a}">${label}<b>${n(a)}</b></button>`).join("");
  document.querySelectorAll(".chip").forEach(b => b.onclick = () => { group = b.dataset.a; move = ""; chips(); render(); });
}
function render() {
  const store = document.getElementById("store").value, mine = document.getElementById("mine").value;
  const gender = document.getElementById("gender").checked;
  document.querySelectorAll(".moves tr").forEach(r => r.classList.toggle("on", r.dataset.m === move));
  DATA.forEach(d => {
    const c = document.getElementById("c" + d.id), a = areas(d.id);
    c.classList.toggle("done", a.length > 0);
    const show = (!group || d.action === group) && (!move || d.move === move) && (!store || d.store === store)
      && (!gender || d.gender) && (mine === "all" || (mine === "todo" && !a.length) || (mine === "bad" && a.includes("bad")));
    c.style.display = show ? "" : "none";
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
document.querySelectorAll(".card textarea").forEach(ta => {
  const id = ta.closest(".card").dataset.id; ta.value = (state[id] || {}).note || "";
  ta.oninput = () => { state[id] = state[id] || {areas: {}}; state[id].note = ta.value; save(); };
});
document.querySelectorAll(".moves tr").forEach(r => r.onclick = () => {
  move = move === r.dataset.m ? "" : r.dataset.m; group = ""; chips(); render(); window.scrollTo(0, 0); });
document.querySelectorAll(".photos img").forEach(i => i.onclick = () => {
  document.getElementById("lbimg").src = i.src; document.getElementById("lb").style.display = "flex"; });
document.getElementById("lb").onclick = () => document.getElementById("lb").style.display = "none";
["store", "mine", "gender"].forEach(id => document.getElementById(id).onchange = render);
document.getElementById("export").onclick = () => {
  const out = DATA.map(d => ({id: d.id, title: d.title, action: d.action, ...(state[d.id] || {})}));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {type: "application/json"}));
  a.download = "libas-enrich-v3-run-__RUN__.json"; a.click();
};
stat(); chips(); render();
</script></body></html>"""


def short(path):
    return (path or "Uncategorised").replace(" > ", " › ")


def banner(action, before, reviewed, res, problems):
    cat = res["category"]
    ai = cat["path"] if cat["path"] != "NONE" else f'NONE (proposes "{cat["proposed_new"]}")'
    who = "Your reviewed category" if reviewed else "Rules"
    text = (f'<b>{review.e(LABEL[action][1])}.</b><br>{who}: <span class="path">{review.e(short(before))}</span>'
            f' → AI: <span class="path">{review.e(short(ai))}</span> ({review.e(cat["confidence"])})')
    if problems:
        text += "<br>Problems: " + review.e("; ".join(problems))
    return f'<div class="banner {action}">{text}</div>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    m = run.load_manifest(args.run)
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    paths = build_category_paths(cur)
    by_path = {v: k for k, v in paths.items()}
    pids = [p["pid"] for p in m["products"].values()]
    cur.execute("""SELECT e.product_id, e.result, e.valid, e.problems, e.applied_at, e.old, p.category_id, o.source
                   FROM ai_enrichment e JOIN products p ON p.id = e.product_id
                   LEFT JOIN category_overrides o ON o.product_id = e.product_id
                   WHERE e.product_id = ANY(%s) AND e.prompt_version = %s""", (pids, m["prompt_version"]))
    rows = cur.fetchall()
    order = {a: i for i, (a, _, _) in enumerate(GROUPS)}
    data, moves, answered = [], Counter(), set()
    for pid, res, valid, problems, applied_at, old, cat_id, source in rows:
        answered.add(pid)
        if applied_at and old:  # after apply: compare against the category saved for undo
            cat_id = old.get("category_id")
            if source == run.SOURCE:
                source = None
        action, ai_cat_id = run.decide(res, cat_id, source, by_path)
        if not valid:
            action = "invalid"
        p = t.load_product(cur, pid)
        before = paths.get(cat_id)
        reviewed = source is not None and source != run.SOURCE
        p["category"], p["reviewed"] = before or "Uncategorised", reviewed
        p["photos"] = [resized(u) for u in p["photos"]]
        html = review.card({"product": p, "result": res, "photos_sent": range(1, len(p["photos"]) + 1)})
        html = html.replace('<section class="card"', f'<section class="card" id="c{pid}"', 1)
        html = html.replace('<div class="photos">', banner(action, before, reviewed, res, problems)
                            + '<div class="photos">', 1)
        mv = ""
        if action in ("moved", "flagged", "reviewed_wins") and res["category"]["path"] != "NONE":
            mv = f"{short(before)} → {short(res['category']['path'])}"
            moves[mv] += 1
        old_gender = (before or "").split(" > ")[0]
        data.append({"id": pid, "title": p["title"], "store": p["store"], "action": action, "move": mv,
                     "gender": res["audience"]["value"] != old_gender, "html": html,
                     "_sort": (order[action], p["store"], pid)})
    data.sort(key=lambda d: d.pop("_sort"))

    missing = [p for p in m["products"].values() if p["pid"] not in answered]
    failed = ""
    if missing:
        items = []
        for p in missing:
            cur.execute("SELECT title FROM products WHERE id = %s", (p["pid"],))
            r = cur.fetchone()
            items.append(f'#{p["pid"]} {review.e(r[0] if r else "?")}')
        failed = (f'<p class="failed"><b>{len(missing)} without an answer</b> (the batch request failed; '
                  f'they get a call in the next run): ' + ", ".join(items) + "</p>")

    move_rows = "".join(f'<tr data-m="{review.e(k)}"><td class="n">{n}</td><td>{review.e(k)}</td></tr>'
                        for k, n in moves.most_common())
    stores = "".join(f'<option value="{s}">{s}</option>' for s in sorted({d["store"] for d in data}))
    out = ROOT / "review-exports" / f"enrich-v3-run-{args.run}" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    page = (PAGE.replace("__STYLE__", STYLE).replace("__MOVES__", move_rows or "<tr><td>none</td></tr>")
                .replace("__STORES__", stores).replace("__FAILED__", failed)
                .replace("__GROUPS__", json.dumps([[a, chip] for a, chip, _ in GROUPS]))
                .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
                .replace("__RUN__", args.run).replace("__N__", str(len(data))))
    out.write_text(page, encoding="utf-8")
    print(f"{len(data)} answers, {len(missing)} without one -> {out}")
    print("  " + ", ".join(f"{LABEL[a][0]} {n}" for a, n in Counter(d["action"] for d in data).most_common()))


if __name__ == "__main__":
    main()
