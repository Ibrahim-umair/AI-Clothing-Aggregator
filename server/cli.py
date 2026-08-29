#!/usr/bin/env python
"""CLI introspection tool for the search pipeline — port of
server/debug_search.js. No HTTP server needed, imports run_search()
directly with debug=True so every stage is visible.

  python cli.py "furor jeans"
  python cli.py "cozy warm sweaters for women under 5000"
  python cli.py "kurta set under 3000" --gender=3   (skips the prompt)
"""
import asyncio
import sys

# Windows' console defaults to cp1252, which can't render the em-dashes
# used in the section headers below (silently prints "?" / mojibake) —
# force UTF-8 the same way every other terminal already handles it.
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from db import close_pool
from rag import run_search

GENDER_OPTIONS = [None, "Men", "Women", "Boys", "Girls"]  # index 0 unused, 1-4 match the prompt


def pick_gender(flag_gender: str | None) -> str | None:
    if flag_gender:
        try:
            n = int(flag_gender)
            if 1 <= n <= 4:
                return GENDER_OPTIONS[n]
        except ValueError:
            pass
        print(f"--gender must be 1-4 (got {flag_gender}) — ignoring, will prompt instead.", file=sys.stderr)
    answer = input("Shop for — 1) Men  2) Women  3) Boys  4) Girls  (anything else = let AI infer): ")
    try:
        n = int(answer.strip())
        return GENDER_OPTIONS[n] if 1 <= n <= 4 else None
    except ValueError:
        return None


def section(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def title_list(rows, show_legs=False):
    if not rows:
        print("  (none)")
        return
    for i, r in enumerate(rows):
        rank = f"{i + 1:>2}. "
        leg_info = ""
        if show_legs:
            v = f"v#{r['legs']['vector']}" if r["legs"]["vector"] is not None else "  -  "
            t = f"t#{r['legs']['textual']}" if r["legs"]["textual"] is not None else "  -  "
            leg_info = f"  [{v} {t}  score={r['score']:.5f}]"
        print(f"  {rank}{r['title']}{leg_info}")


async def main():
    args = sys.argv[1:]
    flag_gender = next((a.split("=", 1)[1] for a in args if a.startswith("--gender=")), None)
    query = " ".join(a for a in args if not a.startswith("--gender=")).strip()
    if not query:
        print('Usage: python cli.py "your search query" [--gender=1-4]', file=sys.stderr)
        sys.exit(1)

    gender_override = pick_gender(flag_gender)
    print(f'Query: "{query}"  (gender override: {gender_override or "none — AI infers"})')

    import time

    t0 = time.perf_counter()
    try:
        result = await run_search(query, debug=True, gender_override=gender_override)
    except Exception as err:
        print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    elapsed = time.perf_counter() - t0

    section("1. LLM tool-call — extracted filters (search_filters function)")
    filters = {k: v for k, v in result["filters"].items() if k != "response_text"}
    for k, v in filters.items():
        print(f"  {k:<14} = {v!r}")
    print(f"  (generated response_text: \"{result['filters']['response_text']}\")")

    section("2. Objective filter match — how much SQL filtering did (before any ranking)")
    cat_ids = result["debug"].get("categoryIds")
    print(f"  category resolved to {len(cat_ids) if cat_ids else 'ALL'} category id(s){' — NOT FOUND, zero results' if result['debug'].get('categoryNotFound') else ''}")
    print(f"  total products matching gender/category/price/brand/size/color/sale filters: {result['total']}")

    section(f"3. Vector search leg — top {len(result['debug']['vectorLeg'])} by embedding similarity, within the filtered set")
    title_list(result["debug"]["vectorLeg"])

    section(f"4. Textual (full-text/BM25-equivalent) leg — top {len(result['debug']['textualLeg'])} by ts_rank, within the filtered set")
    title_list(result["debug"]["textualLeg"])

    section(f"5. Final RRF-fused result — what /api/search actually returns ({len(result['debug']['fused'])} products)")
    print("  [v#N = rank in vector leg, t#N = rank in textual leg, - = not present in that leg]")
    title_list(result["debug"]["fused"], show_legs=True)

    section("Summary")
    print(f"  response_text: \"{result['response_text']}\"")
    print(f"  elapsed: {elapsed:.2f}s")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
