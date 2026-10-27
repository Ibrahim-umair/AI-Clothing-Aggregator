"""
Maps every store color name to plain color families, so a search for
"olive" also finds "Dark Olive", "Army Green" and "DK.OLIVE", and "green"
finds all of those plus the other greens. Fills colors.families.

Each name gets its specific shade family (if it has one) plus the broad hue
it belongs to: 'Dark Olive' -> {olive, green}, 'Navy' -> {navy, blue},
'OLIVE&WHITE' -> {olive, green, white}. Names that aren't colors at all
('SOUL', 'Pack of 3') get an empty array, which search treats as "unknown".

One LLM call per ~150 names; the whole table (~2k names) costs cents.
Only maps names without families yet, so it can be re-run after scrapes
add new color names.

    python map_color_families.py            # map every unmapped name
    python map_color_families.py --redo     # remap everything
"""
import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / "server" / ".env")

from load_data import DSN  # noqa: E402

MODEL = os.environ.get("ENRICH_MODEL", "gpt-6-luna")
CHUNK = 150

# Broad hues first, then the specific shades a shopper actually types. A
# shade always comes with its hue so broad searches still find it. Kept in
# sync with server/search_v2.py, which offers the same list to the query
# model.
HUES = ["black", "white", "grey", "blue", "green", "yellow", "orange", "red",
        "pink", "purple", "brown", "beige", "gold", "silver", "multicolor"]
SHADES = ["navy", "sky blue", "teal", "turquoise", "olive", "mint", "mustard",
          "rust", "maroon", "peach", "lilac", "khaki", "camel", "cream",
          "off white", "charcoal"]
FAMILIES = HUES + SHADES

SYSTEM_PROMPT = f"""You map clothing store color names to color families.
Allowed families: {", ".join(FAMILIES)}.

For each name return every family it belongs to:
- a specific shade AND its broad hue: "Dark Olive" -> ["olive", "green"],
  "Navy Blue" -> ["navy", "blue"], "Off White" -> ["off white", "white"],
  "Charcoal" -> ["charcoal", "grey"], "Maroon" -> ["maroon", "red"],
  "Khaki" -> ["khaki", "beige"], "Cream" -> ["cream", "white"].
- every color in a combination: "OLIVE&WHITE" -> ["olive", "green", "white"].
- abbreviations count: "DK.OLIVE", "L Olive" are olive.
- "Multi", "Assorted", printed mixes -> ["multicolor"].
- names that aren't a recognisable color ("SOUL", "Pack of 3", "Design 2",
  "Default") -> [].
Return the names exactly as given."""

SCHEMA = {
    "name": "color_families",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "mappings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "families": {"type": "array", "items": {"type": "string", "enum": FAMILIES}},
                    },
                    "required": ["name", "families"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["mappings"],
        "additionalProperties": False,
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set (expected in server/.env)")

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(f"SELECT id, canonical_name FROM colors {'' if args.redo else 'WHERE families IS NULL'} ORDER BY id")
    rows = cur.fetchall()
    print(f"{len(rows)} color names to map")
    client = OpenAI(max_retries=6)
    tokens_in = tokens_out = mapped = 0

    for start in range(0, len(rows), CHUNK):
        chunk = rows[start:start + CHUNK]
        resp = client.chat.completions.create(
            model=MODEL,
            reasoning_effort="none",
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": "\n".join(name for _, name in chunk)}],
            response_format={"type": "json_schema", "json_schema": SCHEMA},
        )
        tokens_in += resp.usage.prompt_tokens
        tokens_out += resp.usage.completion_tokens
        by_name = {m["name"]: sorted(set(m["families"])) for m in json.loads(resp.choices[0].message.content)["mappings"]}
        for cid, name in chunk:
            fams = by_name.get(name)
            if fams is None:
                continue  # model dropped or altered the name: left NULL, picked up on the next run
            cur.execute("UPDATE colors SET families = %s WHERE id = %s", (fams, cid))
            mapped += 1
        conn.commit()
        print(f"  {min(start + CHUNK, len(rows))}/{len(rows)}")

    cost = tokens_in / 1e6 * 0.10 + tokens_out / 1e6 * 0.50
    print(f"mapped {mapped}/{len(rows)}  tokens {tokens_in:,} in / {tokens_out:,} out  cost ${cost:.4f}")


if __name__ == "__main__":
    main()
