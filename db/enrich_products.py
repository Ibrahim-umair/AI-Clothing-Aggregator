"""
Product enrichment: a vision LLM looks at a product's photos plus its own
text and writes an objective, free-text description and a handful of open
tags (no fixed vocabulary). The point is to put what's only visible in the
photos - cut, fit, prints and where they sit, details - into text that
search can match on. About a quarter of the catalog has under 80 characters
of brand-written description, so brand text alone can't do this.

Product facts only: no guessing occasions or situations here. Interpreting
"what should I wear to X" is the query side's job at search time.

Color-free on purpose (agreed 2026-10-27): colors go in and out of stock
daily, so color is matched at search time from in-stock variants, never from
this text. A description saying "olive" would make search show a product
whose olive is sold out.

Fit is always stated plainly ("slim fit", "relaxed fit", ...) because search
v2 matches the query's must-have / must-not words against this text.

Photo rule (agreed 2026-10-27): the first 2 product photos, duplicates
removed by URL, resized to 512px via Shopify's CDN to keep it cheap.

    python enrich_products.py --ids 101 202 303            # review, no DB writes
    python enrich_products.py --brand charcoal --limit 3   # review, no DB writes
    python enrich_products.py --brands charcoal zellbury --write --workers 16
"""
import argparse
import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import psycopg2
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / "server" / ".env")

from load_data import DSN  # noqa: E402

MODEL = os.environ.get("ENRICH_MODEL", "gpt-6-luna")
MAX_PHOTOS = 2
IMAGE_WIDTH = 512
# gpt-6-luna standard rates, USD per 1M tokens (for the running cost print).
PRICE_IN, PRICE_OUT = 0.10, 0.50

SYSTEM_PROMPT = """You describe clothing products for a shopping search engine.
You get one product's photos and the store's own text. Write what a shopper
would need to know to recognise this exact item, based on what you can see
and what the text states.

Rules:
- Describe only the item being sold. Ignore the model, background, and any
  other garments or accessories that appear only for styling.
- Never name a color or shade, not even one from the title or store text.
  The same design is sold in several colors that go in and out of stock.
  Describe patterns without color names ("contrast stripes", "two-tone",
  "tonal embroidery").
- Start with the garment type and its fit in plain shopper words, e.g.
  "slim fit", "regular fit", "relaxed fit", "oversized fit", "boxy",
  "straight leg", "wide leg", "tapered", "skinny", "flared". Only state a fit
  you can see or the text states; otherwise write "fit not clear from the
  photos". Describe what it is, never what it isn't.
- Then cover what's relevant: length, sleeves, neckline/collar, prints,
  graphics or embroidery and WHERE they are (front, back, chest, sleeve,
  all-over), texture and visible fabric look, notable details (pockets,
  buttons, zips, distressing, pleats), overall style and formality. Only
  mention a detail you can actually see or the text states.
- Fabric: only state it if the text says so or it's clearly visible; say
  "looks like" when inferring.
- If the item is unstitched fabric, say so; the photo may show a stitched
  example.
- No marketing language, no guesses about occasions or events.

description: 2-4 plain sentences.
tags: 8-15 short lowercase phrases a shopper might use for this item,
covering type, fit, design elements, style. Use common shopper words. No
colors, no brand names.
looks_like: the garment type in 1-3 shopper words, from what you see.
category_ok: false only if the store's category is clearly wrong for what
you see (e.g. category says T-Shirt but it is a polo with a collar)."""

SCHEMA = {
    "name": "product_enrichment",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "looks_like": {"type": "string"},
            "category_ok": {"type": "boolean"},
        },
        "required": ["description", "tags", "looks_like", "category_ok"],
        "additionalProperties": False,
    },
}


def resized(url: str) -> str:
    """Ask Shopify's CDN for a smaller copy; non-Shopify URLs pass through."""
    parts = urlparse(url)
    if "shopify" not in parts.netloc and "/cdn/shop/" not in parts.path:
        return url
    q = dict(parse_qsl(parts.query))
    q["width"] = str(IMAGE_WIDTH)
    return urlunparse(parts._replace(query=urlencode(q)))


def url_key(url: str) -> str:
    p = urlparse(url)
    return p.netloc + p.path


_category_paths = {}


def category_path(cur, category_id):
    if not _category_paths:
        cur.execute("SELECT id, parent_id, name FROM categories")
        by_id = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        for cid in by_id:
            chain, node = [], cid
            while node is not None:
                parent_id, name = by_id[node]
                chain.append(name)
                node = parent_id
            _category_paths[cid] = " > ".join(reversed(chain))
    return _category_paths.get(category_id, "")


def load_product(cur, pid):
    cur.execute(
        """SELECT p.id, b.name, p.title, p.description, p.category_id
           FROM products p JOIN brands b ON b.id = p.brand_id WHERE p.id = %s""",
        (pid,),
    )
    row = cur.fetchone()
    if not row:
        return None
    _, brand, title, description, category_id = row

    cur.execute("SELECT url FROM product_images WHERE product_id = %s ORDER BY position", (pid,))
    product_images = [r[0] for r in cur.fetchall()]

    return {
        "id": pid,
        "brand": brand,
        "title": title,
        "description": description or "",
        "category": category_path(cur, category_id) if category_id else "",
        "all_images": product_images,
    }


def pick_photos(product):
    picked, seen = [], set()

    def add(url):
        k = url_key(url)
        if k not in seen and len(picked) < MAX_PHOTOS:
            seen.add(k)
            picked.append(url)

    for url in product["all_images"]:
        add(url)
    return picked


def download(url, timeout=20):
    """Fetch the resized photo ourselves and pass bytes, not a URL - OpenAI's
    own URL fetcher times out on slow CDN responses and fails the whole
    request. Returns None for dead/slow photos so they're just skipped."""
    try:
        r = requests.get(resized(url), timeout=timeout)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
            return r.content, r.headers["content-type"].split(";")[0]
    except requests.RequestException:
        pass
    return None


def product_text(product):
    return (
        f"Brand: {product['brand']}\n"
        f"Title: {product['title']}\n"
        f"Category: {product['category'] or 'unknown'}\n"
        f"Store description: {product['description'][:1500] or '(none)'}"
    )


def request_body(product, image_urls):
    """One Chat Completions request. image_urls are either data: URLs (sync
    mode, we download the photos ourselves) or plain resized CDN URLs (batch
    mode, where embedding the photos would blow the 200MB batch file cap)."""
    content = [{"type": "text", "text": product_text(product)}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url, "detail": "low"}})
    return {
        "model": MODEL,
        "reasoning_effort": "none",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
        "response_format": {"type": "json_schema", "json_schema": SCHEMA},
    }


def enrich(client, product, photos):
    urls = [f"data:{mime};base64,{base64.b64encode(data).decode()}" for data, mime in photos]
    resp = client.chat.completions.create(**request_body(product, urls))
    return json.loads(resp.choices[0].message.content), resp.usage


def save_result(cur, pid, result, meta):
    cur.execute(
        # New text invalidates the v2 vectors; embed_products_v2.py refills them.
        """UPDATE products SET ai_description = %s, ai_tags = %s, ai_looks_like = %s,
                  ai_category_ok = %s, ai_meta = %s, embedding_v2 = NULL, search_vector_v2 = NULL
           WHERE id = %s""",
        (result["description"], [t.strip().lower() for t in result["tags"] if t.strip()],
         result["looks_like"], result["category_ok"], json.dumps(meta), pid),
    )


def select_ids(cur, brands, redo=False):
    # Fully sold-out products are skipped (agreed 2026-10-27): search never
    # shows them, and stores keep thousands listed (83% of Charcoal, 64% of
    # Zellbury on 2026-10-27). One comes back in stock -> the next run
    # picks it up.
    cur.execute(
        f"""SELECT p.id FROM products p JOIN brands b ON b.id = p.brand_id
            WHERE b.slug = ANY(%s) AND p.is_active {'' if redo else 'AND p.ai_description IS NULL'}
              AND EXISTS (SELECT 1 FROM variants v WHERE v.product_id = p.id AND v.current_available)
            ORDER BY p.id""",
        (brands,),
    )
    return [r[0] for r in cur.fetchall()]


def now_utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Stats:
    """Running totals, printed as we go and written to stats.json at the end."""

    def __init__(self, price_in, price_out):
        self.price_in, self.price_out = price_in, price_out
        self.ok = self.failed = self.no_photo = self.tokens_in = self.tokens_out = 0
        self.t0 = time.time()

    def add(self, tokens_in, tokens_out):
        self.ok += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

    @property
    def cost(self):
        return self.tokens_in / 1e6 * self.price_in + self.tokens_out / 1e6 * self.price_out

    def line(self):
        per = self.cost / self.ok if self.ok else 0
        return (f"done {self.ok}  failed {self.failed}  text-only {self.no_photo}  "
                f"tokens {self.tokens_in:,} in / {self.tokens_out:,} out  "
                f"cost ${self.cost:.3f} (${per * 1000:.3f} per 1k products)  {time.time() - self.t0:.0f}s")

    def as_dict(self):
        return {"succeeded": self.ok, "failed": self.failed, "text_only_no_photo": self.no_photo,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "price_per_1m_usd": {"in": self.price_in, "out": self.price_out},
                "cost_usd": round(self.cost, 4), "seconds": round(time.time() - self.t0)}


# ---------------------------------------------------------------- sync mode

def run_sync(args, conn, ids):
    """Normal API, photos downloaded and sent inline. Used for review runs and
    to retry whatever the batch run couldn't do (e.g. photo links OpenAI
    couldn't fetch)."""
    cur = conn.cursor()
    client = OpenAI(max_retries=6)
    stats = Stats(PRICE_IN, PRICE_OUT)
    collected = []
    products = {pid: load_product(cur, pid) for pid in ids}

    def work(pid):
        product = products[pid]
        picked = pick_photos(product)
        photos = []
        for attempt in range(3):
            photos = [d for d in (download(u) for u in picked) if d]
            if photos or not picked:
                break
            time.sleep(2 * (attempt + 1))
        if picked and not photos:
            # The product has photos but none came through (usually too many
            # parallel downloads timing out). Never fall back to text-only
            # for these: count it as failed so a later run retries it.
            raise RuntimeError(f"{pid}: photos wouldn't download")
        result, usage = enrich(client, product, photos)
        return pid, product, len(photos), result, usage

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, pid) for pid in ids if products.get(pid)]
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                pid, product, n_photos, result, usage = fut.result()
            except Exception as e:  # one bad product must not stop the run
                stats.failed += 1
                print(f"  failed: {e}")
                continue
            stats.add(usage.prompt_tokens, usage.completion_tokens)
            stats.no_photo += n_photos == 0
            if args.write:
                save_result(cur, pid, result, {
                    "model": MODEL, "mode": "sync", "photos": n_photos,
                    "tokens": {"in": usage.prompt_tokens, "out": usage.completion_tokens},
                    "enriched_at": now_utc(),
                })
                if n % 50 == 0:
                    conn.commit()
            collected.append({"id": pid, "brand": product["brand"], "title": product["title"],
                              "category": product["category"], "store_description": product["description"],
                              "photos_sent": n_photos, "result": result,
                              "tokens": {"in": usage.prompt_tokens, "out": usage.completion_tokens}})
            if not args.write:
                print(f"{pid} {product['brand']} | {product['title']}: {result['description'][:90]}...")
            elif n % 200 == 0:
                print("  " + stats.line(), flush=True)
    conn.commit()
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(collected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(stats.line())
    return stats


# --------------------------------------------------------------- batch mode
# OpenAI's Batch API: half the price, results within 24h (usually much
# sooner). Everything lives in a run folder (state.json, request/result
# files, stats.json) so the command can be stopped and re-run to resume.

BATCH_CHUNK = 5000  # requests per batch file (OpenAI's cap is 50k / 200MB)
POLL_SECONDS = 60
TERMINAL = ("completed", "failed", "expired", "cancelled")


def batch_run(args, conn):
    run_dir = Path(args.batch_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "state.json"
    cur = conn.cursor()
    client = OpenAI(max_retries=6)

    if state_path.exists():
        state = json.loads(state_path.read_text())
        print(f"resuming {run_dir}")
    else:
        ids = select_ids(cur, args.brands, args.redo)[: args.limit]
        state = {"brands": args.brands, "selected": len(ids), "chunks": [], "started": time.time()}
        text_only = 0
        for c, start in enumerate(range(0, len(ids), BATCH_CHUNK)):
            chunk = ids[start:start + BATCH_CHUNK]
            path = run_dir / f"requests_{c:02d}.jsonl"
            with path.open("w", encoding="utf-8") as f:
                for pid in chunk:
                    product = load_product(cur, pid)
                    urls = [resized(u) for u in pick_photos(product)]
                    text_only += not urls
                    f.write(json.dumps({"custom_id": str(pid), "method": "POST", "url": "/v1/chat/completions",
                                        "body": request_body(product, urls)}) + "\n")
            state["chunks"].append({"file": path.name, "n": len(chunk), "batch_id": None,
                                    "status": None, "collected": False, "attempts": 0})
        state["text_only"] = text_only
        state_path.write_text(json.dumps(state, indent=2))
        print(f"prepared {len(ids)} requests in {len(state['chunks'])} batch file(s), {text_only} without photos")

    stats = Stats(PRICE_IN / 2, PRICE_OUT / 2)  # Batch API = 50% of standard
    stats.no_photo = state.get("text_only", 0)
    totals = state.get("totals", {})
    stats.ok, stats.failed = totals.get("ok", 0), totals.get("failed", 0)
    stats.tokens_in, stats.tokens_out = totals.get("tokens_in", 0), totals.get("tokens_out", 0)
    failed_ids = set(state.get("failed_ids", []))

    def save_state():
        state["totals"] = {"ok": stats.ok, "failed": stats.failed,
                           "tokens_in": stats.tokens_in, "tokens_out": stats.tokens_out}
        state["failed_ids"] = sorted(failed_ids)
        state_path.write_text(json.dumps(state, indent=2))

    def request_ids(ch):
        with open(run_dir / ch["file"], encoding="utf-8") as f:
            return {int(json.loads(line)["custom_id"]): len(json.loads(line)["body"]["messages"][1]["content"]) - 1
                    for line in f}

    while not all(ch["collected"] for ch in state["chunks"]):
        if args.submit_only and all(ch["batch_id"] for ch in state["chunks"]):
            # Everything is with OpenAI now; nothing local needs to keep
            # running. Re-run without --submit-only later to collect.
            print("all batches submitted; re-run without --submit-only to collect", flush=True)
            return set()
        for ch in state["chunks"]:
            if ch["collected"]:
                continue
            if ch["batch_id"] is None:
                with open(run_dir / ch["file"], "rb") as f:
                    up = client.files.create(file=f, purpose="batch")
                b = client.batches.create(input_file_id=up.id, endpoint="/v1/chat/completions",
                                          completion_window="24h")
                ch.update(batch_id=b.id, status=b.status, attempts=ch["attempts"] + 1)
                print(f"submitted {ch['file']} ({ch['n']} products) as {b.id}", flush=True)
                save_state()
                continue
            b = client.batches.retrieve(ch["batch_id"])
            rc = b.request_counts
            if b.status != ch["status"]:
                print(f"{ch['file']}: {b.status}  {rc.completed if rc else 0}/{rc.total if rc else ch['n']}", flush=True)
                ch["status"] = b.status
                save_state()
            if b.status not in TERMINAL:
                continue
            if not b.output_file_id and not b.error_file_id:
                # Rejected as a whole (e.g. the org's enqueued-token limit
                # while other batches run): resubmit on a later pass.
                errs = [e.message for e in (b.errors.data if b.errors else [])][:2]
                print(f"  {ch['file']} {b.status}: {errs}", flush=True)
                if ch["attempts"] < 6:
                    ch["batch_id"] = None
                else:
                    ch["collected"] = True
                    ids = request_ids(ch)
                    failed_ids.update(ids)
                    stats.failed += len(ids)
                save_state()
                continue
            photos_by_id = request_ids(ch)
            seen = set()
            if b.output_file_id:
                out = client.files.content(b.output_file_id).text
                (run_dir / ch["file"].replace("requests", "results")).write_text(out, encoding="utf-8")
                for line in out.splitlines():
                    rec = json.loads(line)
                    pid = int(rec["custom_id"])
                    seen.add(pid)
                    resp = rec.get("response") or {}
                    try:
                        if resp.get("status_code") != 200:
                            raise ValueError(resp.get("status_code"))
                        body = resp["body"]
                        result = json.loads(body["choices"][0]["message"]["content"])
                    except (KeyError, ValueError, TypeError):
                        failed_ids.add(pid)
                        stats.failed += 1
                        continue
                    usage = body["usage"]
                    stats.add(usage["prompt_tokens"], usage["completion_tokens"])
                    save_result(cur, pid, result, {
                        "model": MODEL, "mode": "batch", "batch_id": b.id, "photos": photos_by_id.get(pid),
                        "tokens": {"in": usage["prompt_tokens"], "out": usage["completion_tokens"]},
                        "enriched_at": now_utc(),
                    })
                conn.commit()
            if b.error_file_id:
                (run_dir / ch["file"].replace("requests", "errors")).write_text(
                    client.files.content(b.error_file_id).text, encoding="utf-8")
            # anything without a successful output line (errors file, or a
            # cut-off expired batch) counts as failed and can be retried
            for pid in photos_by_id:
                if pid not in seen:
                    failed_ids.add(pid)
                    stats.failed += 1
            ch["collected"] = True
            save_state()
            print("  " + stats.line(), flush=True)
        if args.no_wait:
            # One pass only: save whatever batches are finished, leave the
            # rest with OpenAI. Re-run later to collect them.
            pending = [ch["file"] for ch in state["chunks"] if not ch["collected"]]
            if pending:
                print(f"not finished yet, left for a later run: {pending}", flush=True)
            break
        if not all(ch["collected"] for ch in state["chunks"]):
            time.sleep(POLL_SECONDS)

    save_state()
    summary = {"brands": state["brands"], "selected": state["selected"], **stats.as_dict(),
               "seconds": round(time.time() - state["started"])}
    (run_dir / "stats.json").write_text(json.dumps(summary, indent=2))
    print("BATCH DONE  " + stats.line(), flush=True)
    return failed_ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", type=int, nargs="*")
    ap.add_argument("--brand", help="review mode: random products of one brand slug")
    ap.add_argument("--brands", nargs="*", help="every active product of these brand slugs not yet enriched")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--write", action="store_true", help="save results to the products table")
    ap.add_argument("--redo", action="store_true", help="include products already enriched")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--batch-dir", help="use the Batch API (half price); run folder for state + results")
    ap.add_argument("--no-wait", action="store_true",
                    help="batch mode: collect the batches that are finished and exit without waiting for the rest")
    ap.add_argument("--submit-only", action="store_true",
                    help="batch mode: upload and submit, then exit (collect later by re-running without it)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="after a batch run, redo its failures with the normal API (photos sent inline)")
    ap.add_argument("--json-out", help="also write all results to this JSON file")
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set (expected in server/.env)")
    conn = psycopg2.connect(DSN)

    if args.batch_dir:
        if not (args.write and args.brands):
            sys.exit("--batch-dir needs --brands and --write")
        failed = batch_run(args, conn)
        if failed and args.retry_failed:
            print(f"retrying {len(failed)} failed products with the normal API", flush=True)
            retry = run_sync(args, conn, sorted(failed))
            stats_path = Path(args.batch_dir) / "stats.json"
            summary = json.loads(stats_path.read_text())
            summary["retry_sync"] = retry.as_dict()
            summary["total_cost_usd"] = round(summary["cost_usd"] + retry.cost, 4)
            stats_path.write_text(json.dumps(summary, indent=2))
            print(f"TOTAL cost ${summary['total_cost_usd']:.3f}", flush=True)
        return

    cur = conn.cursor()
    ids = list(args.ids or [])
    if args.brand:
        cur.execute(
            """SELECT p.id FROM products p JOIN brands b ON b.id = p.brand_id
               WHERE b.slug = %s AND p.is_active ORDER BY random() LIMIT %s""",
            (args.brand, args.limit or 3),
        )
        ids += [r[0] for r in cur.fetchall()]
    if args.brands:
        ids += select_ids(cur, args.brands, args.redo)[: args.limit]
    run_sync(args, conn, ids)


if __name__ == "__main__":
    main()
