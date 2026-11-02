"""
Runs the enrichment test prompt (enrich_v3_test.py) on another model, one
product at a time with a pause between calls, so the results can be compared
with other models on the same products (export_model_compare.py).

Models go through OpenRouter (key in server/.env.openrouter, gitignored), or
straight to OpenAI with --openai (key in server/.env).

    python enrich_openrouter_test.py --model deepseek/deepseek-v4.1-flash --tag r6 --no-reasoning
    python enrich_openrouter_test.py --model qwen/qwen3.7-flash --tag r6 --json-mode
    python enrich_openrouter_test.py --model gpt-6-luna --openai --tag r6
Results: local-notes/enrich_v3_test/results_<tag>_<model-slug>.json
"""
import argparse
import json
import os
import time
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI

import enrich_v3_test as t
from enrich_products import PRICE_IN, PRICE_OUT
from load_data import DSN

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--sample", default="r5", help="which sample file to reuse")
    ap.add_argument("--tag", default="r6", help="prefix of the results file")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--pause", type=float, default=15, help="seconds between calls")
    ap.add_argument("--temperature", type=float, default=0)
    ap.add_argument("--max-tokens", type=int, default=1500,
                    help="answer cap; answers are ~450 tokens, and OpenRouter checks credit against the cap")
    ap.add_argument("--no-reasoning", action="store_true", help="turn the model's thinking off")
    ap.add_argument("--json-mode", action="store_true",
                    help="for models without strict schemas: plain JSON, schema given in the prompt")
    ap.add_argument("--openai", action="store_true", help="call OpenAI directly instead of OpenRouter")
    args = ap.parse_args()

    if args.openai:
        load_dotenv(ROOT / "server" / ".env")
        client = OpenAI()
    else:
        load_dotenv(ROOT / "server" / ".env.openrouter")
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
    cur = psycopg2.connect(DSN).cursor()
    system_prompt = t.SYSTEM_PROMPT + t.grouped_tree(cur)
    if args.json_mode:
        system_prompt += ("\n\nReturn only a JSON object that matches this JSON schema exactly:\n"
                          + json.dumps(t.SCHEMA["schema"]))
    valid_paths = set(t.leaf_paths(cur))

    products = json.loads((t.OUT_DIR / f"sample_{args.sample}.json").read_text(encoding="utf-8"))[:args.limit]
    out_file = t.OUT_DIR / f"results_{args.tag}_{args.model.split('/')[-1]}.json"
    results = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else []
    done = {r["product"]["id"] for r in results if "result" in r}

    for i, p in enumerate(products, 1):
        if p["id"] in done:
            continue
        photos = t.fetch_photos(p)
        body = t.request_body(system_prompt, p, photos)
        body["model"] = args.model
        body["temperature"] = args.temperature
        # OpenAI's newer models only take max_completion_tokens.
        body["max_completion_tokens" if args.openai else "max_tokens"] = args.max_tokens
        extra = {}
        if args.openai:
            pass  # keeps reasoning_effort "none" and the cache key
        else:
            for k in ("reasoning_effort", "prompt_cache_key"):  # OpenAI-only parameters
                body.pop(k, None)
            extra = {"usage": {"include": True}}
            if args.no_reasoning:
                extra["reasoning"] = {"enabled": False}
            if args.json_mode:
                body["response_format"] = {"type": "json_object"}
            else:
                extra["provider"] = {"require_parameters": True}
        t0 = time.time()
        try:
            resp = client.chat.completions.create(**body, extra_body=extra or None)
            text = resp.choices[0].message.content
            u = resp.usage.model_dump()
        except Exception as e:  # stop on the first hard error (credits, rate limit)
            print(f"{i:>2}/{len(products)} FAILED {p['title'][:34]}: {str(e)[:300]}")
            break
        cost = u.get("cost")
        if cost is None:  # direct OpenAI: work it out from the standard rates
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            cost = ((u["prompt_tokens"] - cached) * PRICE_IN + cached * PRICE_IN / 10
                    + u["completion_tokens"] * PRICE_OUT) / 1e6
        usage = {"in": u["prompt_tokens"], "out": u["completion_tokens"], "cost": cost,
                 "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                 "reasoning": (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0}
        row = {"product": p, "photos_sent": [n for n, _ in photos], "usage": usage,
               "seconds": round(time.time() - t0, 1)}
        try:
            row["result"] = json.loads(text)
            path = row["result"]["category"]["path"]
            note = "" if path in valid_paths | {"NONE"} else "  (path not in tree)"
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            row["error"] = f"bad JSON: {e}: {(text or '')[:200]}"
            path, note = "-", "  (BAD JSON)"
        print(f"{i:>2}/{len(products)} {p['title'][:32]:<32} {path[-32:]:<32} in {usage['in']} "
              f"out {usage['out']} (thinking {usage['reasoning']}) ${cost:.6f}{note}")
        results.append(row)
        out_file.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
        if i < len(products):
            time.sleep(args.pause)
    ok = [r for r in results if "result" in r]
    if ok:
        avg = sum(r["usage"]["cost"] for r in ok) / len(ok)
        print(f"{len(ok)} ok, {len(results) - len(ok)} bad -> {out_file.name}; "
              f"avg ${avg:.6f}/product, ~${avg * 45693:.2f} for 45,693 (no batch)")


if __name__ == "__main__":
    main()
