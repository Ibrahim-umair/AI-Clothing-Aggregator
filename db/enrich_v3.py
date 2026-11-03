"""
Enrichment v3 run (docs/NEXT_RUN_SPEC.md section 6): GPT-6 Luna through the
Batch API. The prompt and schema live in enrich_v3_test.py (round r9), so the
tested prompt is exactly what runs.

    python enrich_v3.py build --run pilot --limit 500   # pick products, write batch files (no calls)
    python enrich_v3.py submit --run pilot              # upload + create the batches
    python enrich_v3.py collect --run pilot             # save finished answers to ai_enrichment
    python enrich_v3.py apply --run pilot [--dry-run]   # write answers to products (with undo data)
    python enrich_v3.py undo --run pilot                # put everything back

Who gets a call: active, at least one in-stock size, at least one photo, not
hidden, and no answer yet for this prompt version. Photos go as links to the
store's CDN resized to 512 px (the "low" detail size), not embedded, so a
5,000-product file stays well under the 200 MB limit.

Run files: local-notes/enrich_v3_run/<run>/ (manifest.json + batch_NN.jsonl).
"""
import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import Json

import enrich_v3_test as t
from embed_products import build_category_paths
from enrich_products import MODEL, resized, url_key
from load_data import DSN

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "local-notes" / "enrich_v3_run"
PROMPT_VERSION = "v3-r9"
SOURCE = "enrich-v3"          # category_overrides.source for changes made by this run
PER_FILE = 5000
MAX_FILE_BYTES = 190_000_000
# Batch prices per 1M tokens (gpt-6-luna): input, cached input, output.
BATCH_IN, BATCH_CACHED, BATCH_OUT = 0.05, 0.005, 0.25

# Pilot cache test: half the products share one key, half are spread over 64
# keys (OpenAI: ~15 requests/minute per key before requests overflow to other
# machines and miss the cache).
CACHE_SHARDS = 64

LADDERS = {
    "dress": ["casual", "smart casual", "office", "party", "wedding"],
    "warmth": ["light", "medium", "warm"],
    "embellishment": ["plain", "printed", "light", "medium", "heavy"],
    "sheerness": ["opaque", "lined", "semi-sheer", "sheer"],
}


def rung(ladder, value):
    """Ordered number for a ladder value; None for n/a, not clear or unknown."""
    return LADDERS[ladder].index(value) if value in LADDERS[ladder] else None


def run_dir(run):
    return RUNS / run


def load_manifest(run):
    return json.loads((run_dir(run) / "manifest.json").read_text(encoding="utf-8"))


def save_manifest(run, m):
    (run_dir(run) / "manifest.json").write_text(json.dumps(m, indent=1), encoding="utf-8")


def eligible_ids(cur):
    cur.execute(f"""SELECT p.id FROM products p
                    WHERE {t.SELLABLE}
                      AND NOT EXISTS (SELECT 1 FROM category_overrides o WHERE o.product_id = p.id AND o.hide)
                      AND NOT EXISTS (SELECT 1 FROM ai_enrichment e WHERE e.product_id = p.id
                                      AND e.prompt_version = %s AND e.valid)
                    ORDER BY p.id""", (PROMPT_VERSION,))
    return [r[0] for r in cur.fetchall()]


def photo_positions(cur, pid, urls):
    """product_images.position of each photo sent, in order (Photo 1 = first)."""
    cur.execute("SELECT url, position FROM product_images WHERE product_id = %s", (pid,))
    pos = {}
    for url, p in cur.fetchall():
        pos.setdefault(url_key(url), p)
    return [pos.get(url_key(u)) for u in urls]


def request_body(system_prompt, product, cache_key):
    content = t.user_content(product, [])  # the text part, exactly as tested
    for n, url in enumerate(product["photos"], 1):
        content.append({"type": "text", "text": f"Photo {n}:"})
        content.append({"type": "image_url", "image_url": {"url": resized(url), "detail": "low"}})
    return {
        "model": MODEL, "reasoning_effort": "none",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
        "response_format": {"type": "json_schema", "json_schema": t.SCHEMA},
        "prompt_cache_key": cache_key,
    }


def cmd_build(args, conn):
    cur = conn.cursor()
    out = run_dir(args.run)
    if (out / "manifest.json").exists():
        sys.exit(f"{out} already has a manifest; use a new --run name")
    out.mkdir(parents=True, exist_ok=True)
    ids = eligible_ids(cur)
    if args.limit:
        ids = sorted(random.Random(args.seed).sample(ids, min(args.limit, len(ids))))
    system_prompt = t.SYSTEM_PROMPT + t.grouped_tree(cur)
    manifest = {"prompt_version": PROMPT_VERSION, "model": MODEL, "created": datetime.now(timezone.utc).isoformat(),
                "files": [], "products": {}}
    lines, size, n_file = [], 0, 0

    def flush():
        nonlocal lines, size, n_file
        if not lines:
            return
        n_file += 1
        path = out / f"batch_{n_file:02d}.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        manifest["files"].append({"path": path.name, "requests": len(lines), "bytes": size})
        lines, size = [], 0

    for i, pid in enumerate(ids):
        product = t.load_product(cur, pid)
        if not product["photos"]:
            continue
        shard = args.shard_keys or (args.cache_test and i % 2 == 1)
        key = f"{t.CACHE_KEY}-{pid % CACHE_SHARDS}" if shard else t.CACHE_KEY
        custom_id = f"{pid}:{PROMPT_VERSION}"
        line = json.dumps({"custom_id": custom_id, "method": "POST", "url": "/v1/chat/completions",
                           "body": request_body(system_prompt, product, key)}, ensure_ascii=False)
        if len(lines) >= PER_FILE or size + len(line) > MAX_FILE_BYTES:
            flush()
        lines.append(line)
        size += len(line.encode("utf-8")) + 1
        manifest["products"][custom_id] = {
            "pid": pid, "cache_key": key, "photos": photo_positions(cur, pid, product["photos"]),
            "colors": [c["name"] for c in product["colors"]], "category": product["category"],
            "reviewed": product["reviewed"]}
    flush()
    save_manifest(args.run, manifest)
    print(f"{len(manifest['products'])} products in {len(manifest['files'])} file(s): "
          + ", ".join(f"{f['path']} {f['requests']} req {f['bytes'] / 1e6:.1f} MB" for f in manifest["files"]))


def openai_client():
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(ROOT / "server" / ".env")
    return OpenAI()


def cmd_submit(args, conn):
    m = load_manifest(args.run)
    client = openai_client()
    for f in m["files"]:
        if f.get("batch_id"):
            continue
        with open(run_dir(args.run) / f["path"], "rb") as fh:
            up = client.files.create(file=fh, purpose="batch")
        b = client.batches.create(input_file_id=up.id, endpoint="/v1/chat/completions", completion_window="24h",
                                  metadata={"run": args.run, "file": f["path"]})
        f["batch_id"] = b.id
        save_manifest(args.run, m)
        print(f"{f['path']}: {f['requests']} requests -> {b.id}")
        if args.one:
            break


def validate(res, info, valid_paths):
    problems = []
    path = res["category"]["path"]
    if path != "NONE" and path not in valid_paths:
        problems.append(f"category path not in tree: {path}")
    if path == "NONE" and not res["category"]["proposed_new"]:
        problems.append("NONE without a proposed category")
    if not res["looks_like"].strip():
        problems.append("empty looks_like")
    n_photos, versions = len(info["photos"]), res["versions"]
    if not versions and not res["not_apparel"]:
        problems.append("no colour versions")
    for v in versions:
        bad = [n for n in v["photos"] if not 1 <= n <= n_photos]
        if bad:
            problems.append(f"photo numbers out of range: {bad}")
    for c in res["color_map"]:
        if not 0 <= c["version"] < len(versions):
            problems.append(f"color_map version out of range: {c}")
    mapped = {c["store_color"].strip().lower() for c in res["color_map"]}
    missing = [c for c in info["colors"] if c.strip().lower() not in mapped]
    if missing and len(versions) > 1:
        problems.append(f"store colours not mapped: {missing[:5]}")
    return problems


def usage_of(body):
    u = body.get("usage") or {}
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0), "cached": cached,
            "cost": ((u.get("prompt_tokens", 0) - cached) * BATCH_IN + cached * BATCH_CACHED
                     + u.get("completion_tokens", 0) * BATCH_OUT) / 1e6}


def cmd_collect(args, conn):
    m = load_manifest(args.run)
    client = openai_client()
    cur = conn.cursor()
    valid_paths = set(t.leaf_paths(cur))
    saved = Counter()
    for f in m["files"]:
        if not f.get("batch_id") or f.get("collected"):
            continue
        b = client.batches.retrieve(f["batch_id"])
        print(f"{f['path']}: {b.status} {b.request_counts}")
        if b.status not in ("completed", "expired", "cancelled"):
            continue
        rows = []
        for fid in (b.output_file_id, b.error_file_id):
            if fid:
                rows += [json.loads(line) for line in client.files.content(fid).text.splitlines() if line.strip()]
        for row in rows:
            info = m["products"][row["custom_id"]]
            body = (row.get("response") or {}).get("body") or {}
            if not body.get("choices"):
                saved["failed (no answer)"] += 1
                continue
            res = json.loads(body["choices"][0]["message"]["content"])
            problems = validate(res, info, valid_paths)
            cur.execute("""
                INSERT INTO ai_enrichment (product_id, result, model, prompt_version, batch_id, photos_sent,
                                           usage, valid, problems)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (product_id) DO UPDATE SET result = EXCLUDED.result, model = EXCLUDED.model,
                    prompt_version = EXCLUDED.prompt_version, batch_id = EXCLUDED.batch_id,
                    photos_sent = EXCLUDED.photos_sent, usage = EXCLUDED.usage, valid = EXCLUDED.valid,
                    problems = EXCLUDED.problems, created_at = now(), applied_at = NULL
            """, (info["pid"], Json(res), body.get("model") or m["model"], m["prompt_version"], f["batch_id"],
                  info["photos"], Json({**usage_of(body), "cache_key": info["cache_key"]}),
                  not problems, problems or None))
            saved["valid" if not problems else "invalid"] += 1
        conn.commit()
        f["collected"] = True
        f["status"] = b.status
        save_manifest(args.run, m)
    print("saved:", dict(saved) or "nothing new")
    report(cur, m)


def report(cur, m):
    """Cost and cache use for this run's answers, split by cache-key group."""
    pids = [p["pid"] for p in m["products"].values()]
    cur.execute("""SELECT usage, valid, problems FROM ai_enrichment
                   WHERE product_id = ANY(%s) AND prompt_version = %s""", (pids, m["prompt_version"]))
    rows = cur.fetchall()
    if not rows:
        return
    groups = {}
    for u, valid, problems in rows:
        g = "one key" if u["cache_key"] == t.CACHE_KEY else f"{CACHE_SHARDS} keys"
        s = groups.setdefault(g, Counter())
        for k in ("in", "out", "cached", "cost"):
            s[k] += u[k]
        s["n"] += 1
    total = Counter()
    for g, s in sorted(groups.items()):
        total.update(s)
        print(f"  {g:>8}: {s['n']} answers, cache {100 * s['cached'] / max(s['in'], 1):.0f}% of input, "
              f"${s['cost'] / s['n']:.6f}/product")
    per = total["cost"] / total["n"]
    print(f"  total: {total['n']} answers, ${total['cost']:.4f}, ${per:.6f}/product "
          f"-> ~${per * len(eligible_ids_cache(cur)):.2f} for every eligible product now")
    bad = Counter(p.split(":")[0] for _, valid, ps in rows if not valid for p in ps)
    print("  invalid answers:", sum(1 for _, v, _ in rows if not v), dict(bad))


_eligible = None


def eligible_ids_cache(cur):
    global _eligible
    if _eligible is None:
        cur.execute(f"""SELECT p.id FROM products p WHERE {t.SELLABLE}
                        AND NOT EXISTS (SELECT 1 FROM category_overrides o WHERE o.product_id = p.id AND o.hide)""")
        _eligible = [r[0] for r in cur.fetchall()]
    return _eligible


def decide(res, cat_id, override_source, by_path):
    """What the apply step does with one answer, given the product's category
    before this run and the source of its override (None when it has none).
    Shared with the review page so the page shows exactly what apply does.
    Returns (action, ai_category_id); action is one of
      agrees        the AI picked the category the product already has
      moved         high confidence, different category: the AI's wins
      flagged       medium/low confidence or NONE: the rules' category stays
      hidden        not apparel
      reviewed_wins you reviewed this product; your decision stays"""
    reviewed = override_source is not None and override_source != SOURCE  # a human decision always wins
    cat = res["category"]
    ai_cat_id = by_path.get(cat["path"])
    if reviewed:
        return ("agrees" if ai_cat_id == cat_id and not res["not_apparel"] else "reviewed_wins"), ai_cat_id
    if res["not_apparel"]:
        return "hidden", ai_cat_id
    if ai_cat_id == cat_id:
        return "agrees", ai_cat_id
    if cat["confidence"] == "high" and ai_cat_id:
        return "moved", ai_cat_id
    return "flagged", ai_cat_id


def apply_one(cur, pid, res, photos, meta, by_path, paths):
    cur.execute("""SELECT category_id, ai_description, ai_tags, ai_looks_like, ai_category_ok, ai_meta
                   FROM products WHERE id = %s""", (pid,))
    cat_id, *old_ai = cur.fetchone()
    old = dict(zip(["ai_description", "ai_tags", "ai_looks_like", "ai_category_ok", "ai_meta"], old_ai))
    cur.execute("SELECT source FROM category_overrides WHERE product_id = %s", (pid,))
    row = cur.fetchone()
    cat, aud, d = res["category"], res["audience"], res["descriptors"]
    action, ai_cat_id = decide(res, cat_id, row[0] if row else None, by_path)
    if action in ("hidden", "moved"):
        if action == "hidden":
            cur.execute("""INSERT INTO category_overrides (product_id, category_id, hide, old_category_id, source, note)
                           VALUES (%s, NULL, true, %s, %s, %s)
                           ON CONFLICT (product_id) DO UPDATE SET category_id = NULL, hide = true, note = EXCLUDED.note""",
                        (pid, cat_id, SOURCE, f"not apparel: {res['looks_like']}"))
        else:
            cur.execute("""INSERT INTO category_overrides (product_id, category_id, hide, old_category_id, source, note)
                           VALUES (%s, %s, false, %s, %s, %s)
                           ON CONFLICT (product_id) DO UPDATE SET category_id = EXCLUDED.category_id, hide = false,
                               note = EXCLUDED.note""",
                        (pid, ai_cat_id, cat_id, SOURCE, cat["reason"][:300]))
    final_cat = ai_cat_id if action == "moved" else cat_id
    dl, emb = d["dress_level"], d["embellishment"]
    cur.execute("""
        UPDATE products SET category_id = category_id,
            ai_description = %s, ai_tags = %s, ai_looks_like = %s,
            ai_category_ok = %s, ai_meta = %s,
            ai_audience = %s, ai_audience_confidence = %s,
            ai_category_id = %s, ai_category_confidence = %s, ai_category_reason = %s, ai_proposed_category = %s,
            ai_not_apparel = %s, ai_descriptors = %s,
            ai_dress_from = %s, ai_dress_to = %s, ai_warmth = %s, ai_embellishment = %s, ai_sheerness = %s
        WHERE id = %s""", (
        res["description"], res["tags"], res["looks_like"],
        # true = the category shown agrees with the photo; NULL = not sure (never hidden for it)
        True if ai_cat_id == final_cat else None, Json(meta),
        aud["value"], aud["confidence"],
        ai_cat_id, cat["confidence"], cat["reason"] or None, cat["proposed_new"] or None,
        res["not_apparel"], Json(d),
        rung("dress", dl["from"]), rung("dress", dl["to"]), rung("warmth", d["warmth"]),
        rung("embellishment", emb["level"]), rung("sheerness", d["coverage"]["sheerness"]), pid))

    # Colour versions: rewritten whole; variants re-linked from color_map.
    cur.execute("DELETE FROM product_color_versions WHERE product_id = %s", (pid,))
    version_ids = []
    for i, v in enumerate(res["versions"]):
        match = [v["main_color"]] + [s["color"] for s in v["secondary"] if s["share"] == "equal"]
        part = [s["color"] for s in v["secondary"] if s["share"] == "part"]
        pos = [photos[n - 1] for n in v["photos"] if 1 <= n <= len(photos) and photos[n - 1] is not None]
        cur.execute("""INSERT INTO product_color_versions (product_id, idx, main_color, secondary, details, pattern,
                                                           photo_positions, match_colors, part_colors)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (pid, i, v["main_color"], Json(v["secondary"]), Json(v["details"]), v["pattern"] or None,
                     pos, sorted(set(match)), sorted(set(part) - set(match))))
        version_ids.append(cur.fetchone()[0])
    if len(version_ids) == 1:
        cur.execute("UPDATE variants SET color_version_id = %s WHERE product_id = %s", (version_ids[0], pid))
    else:
        for c in res["color_map"]:
            if 0 <= c["version"] < len(version_ids):
                cur.execute("""UPDATE variants v SET color_version_id = %s FROM colors co
                               WHERE v.product_id = %s AND co.id = v.color_id
                                 AND lower(trim(co.canonical_name)) = lower(trim(%s))""",
                            (version_ids[c["version"]], pid, c["store_color"]))
    cur.execute("UPDATE ai_enrichment SET applied_at = now(), old = COALESCE(old, %s) WHERE product_id = %s",
                (Json({**old, "category_id": cat_id}), pid))
    return action, paths.get(cat_id), cat["path"], cat["confidence"]


def cmd_apply(args, conn):
    m = load_manifest(args.run)
    cur = conn.cursor()
    paths = build_category_paths(cur)
    by_path = {v: k for k, v in paths.items()}
    pids = [p["pid"] for p in m["products"].values()]
    cur.execute("""SELECT product_id, result, photos_sent, model, batch_id, usage, created_at FROM ai_enrichment
                   WHERE product_id = ANY(%s) AND prompt_version = %s AND valid AND applied_at IS NULL""",
                (pids, m["prompt_version"]))
    rows = cur.fetchall()
    actions, moves = Counter(), Counter()
    for pid, res, photos, model, batch_id, usage, created in rows:
        meta = {"model": model, "prompt_version": m["prompt_version"], "batch_id": batch_id,
                "photos": photos, "usage": usage, "at": created.isoformat()}
        action, old_path, new_path, conf = apply_one(cur, pid, res, photos, meta, by_path, paths)
        actions[action] += 1
        if action == "moved":
            moves[f"{(old_path or 'Uncategorised').split(' > ', 1)[-1]} -> {new_path.split(' > ', 1)[-1]}"] += 1
    print(f"{len(rows)} answers: " + ", ".join(f"{k} {v}" for k, v in actions.most_common()))
    for k, v in moves.most_common(15):
        print(f"  {v:>4}  {k}")
    if args.dry_run:
        conn.rollback()
        print("dry run: rolled back, nothing written")
        return
    conn.commit()
    cur.execute("""SELECT count(*) FROM products p JOIN category_overrides o ON o.product_id = p.id
                   WHERE (o.category_id IS NOT NULL AND p.category_id <> o.category_id) OR (o.hide AND p.is_browsable)""")
    print("products not matching their override:", cur.fetchone()[0])


def cmd_undo(args, conn):
    m = load_manifest(args.run)
    cur = conn.cursor()
    pids = [p["pid"] for p in m["products"].values()]
    cur.execute("""
        WITH gone AS (DELETE FROM category_overrides WHERE source = %s AND product_id = ANY(%s)
                      RETURNING product_id, old_category_id, hide)
        UPDATE products p SET category_id = g.old_category_id,
               is_browsable = CASE WHEN g.hide THEN true ELSE p.is_browsable END
        FROM gone g WHERE p.id = g.product_id""", (SOURCE, pids))
    moved = cur.rowcount
    cur.execute("""
        UPDATE products p SET ai_description = e.old->>'ai_description',
            ai_tags = ARRAY(SELECT jsonb_array_elements_text(COALESCE(e.old->'ai_tags', '[]'))),
            ai_looks_like = e.old->>'ai_looks_like', ai_category_ok = (e.old->>'ai_category_ok')::boolean,
            ai_meta = e.old->'ai_meta',
            ai_audience = NULL, ai_audience_confidence = NULL, ai_category_id = NULL, ai_category_confidence = NULL,
            ai_category_reason = NULL, ai_proposed_category = NULL, ai_not_apparel = NULL, ai_descriptors = NULL,
            ai_dress_from = NULL, ai_dress_to = NULL, ai_warmth = NULL, ai_embellishment = NULL, ai_sheerness = NULL
        FROM ai_enrichment e WHERE e.product_id = p.id AND p.id = ANY(%s) AND e.applied_at IS NOT NULL""", (pids,))
    restored = cur.rowcount
    cur.execute("DELETE FROM product_color_versions WHERE product_id = ANY(%s)", (pids,))
    cur.execute("UPDATE ai_enrichment SET applied_at = NULL, old = NULL WHERE product_id = ANY(%s)", (pids,))
    conn.commit()
    print(f"undone: {restored} products restored, {moved} category changes reverted")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--run", required=True)
    b.add_argument("--limit", type=int, help="random sample of this many eligible products (pilot)")
    b.add_argument("--seed", type=int, default=20261102)
    b.add_argument("--cache-test", action="store_true", help="half one cache key, half 64 keys")
    b.add_argument("--shard-keys", action="store_true", help="spread every request over 64 cache keys")
    s = sub.add_parser("submit")
    s.add_argument("--run", required=True)
    s.add_argument("--one", action="store_true", help="submit only the next file")
    for name in ("collect", "undo"):
        sub.add_parser(name).add_argument("--run", required=True)
    a = sub.add_parser("apply")
    a.add_argument("--run", required=True)
    a.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conn = psycopg2.connect(DSN)
    {"build": cmd_build, "submit": cmd_submit, "collect": cmd_collect, "apply": cmd_apply,
     "undo": cmd_undo}[args.cmd](args, conn)


if __name__ == "__main__":
    main()
