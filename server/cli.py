#!/usr/bin/env python
"""CLI introspection tool for the search pipeline. No HTTP server needed:
it calls run_search_v2() directly with debug=True, so every stage is
visible: how the LLM planned the query, then each search's results with
their scores and which retrieval legs found them.

  python cli.py "furor jeans"
  python cli.py "cozy warm sweaters for women under 5000"
  python cli.py "kurta set under 3000" --gender=3   (skips the prompt)
"""
import asyncio
import sys
import time

# Windows' console defaults to cp1252, which can't render the em-dashes
# used in the section headers below (silently prints "?" / mojibake) —
# force UTF-8 the same way every other terminal already handles it.
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from db import close_pool
from search_v2 import run_search_v2

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


async def main():
    args = sys.argv[1:]
    flag_gender = next((a.split("=", 1)[1] for a in args if a.startswith("--gender=")), None)
    query = " ".join(a for a in args if not a.startswith("--gender=")).strip()
    if not query:
        print('Usage: python cli.py "your search query" [--gender=1-4]', file=sys.stderr)
        sys.exit(1)

    gender_override = pick_gender(flag_gender)
    print(f'Query: "{query}"  (gender override: {gender_override or "none — AI infers"})')

    t0 = time.perf_counter()
    try:
        result = await run_search_v2(query, debug=True, gender_override=gender_override)
    except Exception as err:
        print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    elapsed = time.perf_counter() - t0

    section("1. The plan — how the LLM read the query")
    filters = {k: v for k, v in result["filters"].items() if k not in ("response_text", "searches", "semantic_query")}
    for k, v in filters.items():
        print(f"  {k:<10} = {v!r}")

    for n, g in enumerate(result["groups"], 2):
        section(f"{n}. Search \"{g['label'] or g['query']}\" — {len(g['products'])} results")
        print(f"  query      = {g['query']!r}")
        print(f"  categories = {g['categories']}")
        print(f"  must have  = {g['must_have']}   must not = {g['must_not']}")
        for note in g["notes"]:
            print(f"  note: {note}")
        removed = g.get("_debug", {}).get("removed_count", 0)
        if removed:
            print(f"  removed by must-not: {removed}")
        print("  [v#N / t#N = rank in the vector / text leg, - = not found by it; * = must-have hit; alt = alternative]")
        for i, p in enumerate(g["products"], 1):
            d = p.get("_debug", {})
            legs = d.get("legs") or {}
            v = f"v#{legs['vector']}" if legs.get("vector") is not None else "  -  "
            t = f"t#{legs['textual']}" if legs.get("textual") is not None else "  -  "
            flags = ("*" if d.get("must_have_hit") else " ") + (" alt" if p.get("alternative") else "    ")
            print(f"  {i:>2}. {p['title'][:60]:<60} {p['store']:<12} {v} {t} {d.get('score', 0):.5f}{flags}")

    section("Summary")
    print(f"  response_text: \"{result['response_text']}\"")
    print(f"  {result['total']} products in {len(result['groups'])} group(s), {elapsed:.2f}s")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
