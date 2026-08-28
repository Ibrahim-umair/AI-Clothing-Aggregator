import json
import os
import re
import statistics
from collections import Counter, defaultdict

DATA_DIR = r"C:\Work\scraping-init\scraped_data"
REPORT_PATH = os.path.join(DATA_DIR, "data_format_report.txt")

STORE_SLUGS = [
    "outfitters", "furor", "edenrobe", "one_be-one", "equator", "meme", "breakout",
    "monark", "engine_clothing", "charcoal", "royal_tag", "diners", "cambridge",
    "uniworth", "cougar",
]

LEADING_CODE_RE = re.compile(r'^[A-Z0-9][A-Z0-9\-_/]{3,}\b')
SIZE_WORDS = {"size", "sizes"}
COLOR_WORDS = {"color", "colour", "colors", "colours"}


def analyze_store(slug, out):
    path = os.path.join(DATA_DIR, f"{slug}.jsonl")
    is_graphql = (slug == "cougar")
    out.write(f"\n{'='*95}\nSTORE: {slug}\n{'='*95}\n")

    option_name_sets = Counter()
    product_types = Counter()
    vendors = Counter()
    tag_counter = Counter()
    tags_per_product = []
    title_word_counts = []
    title_has_leading_code = 0
    has_color_option = 0
    has_size_option = 0
    total = 0
    titles_by_type = defaultdict(list)

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            total += 1
            title = p.get("title") or ""
            title_word_counts.append(len(title.split()))
            if LEADING_CODE_RE.match(title):
                title_has_leading_code += 1

            if is_graphql:
                ptype = p.get("productType") or ""
                vendor = p.get("vendor") or ""
                tags = p.get("tags") or []
                opts = set()
                for e in (p.get("variants") or {}).get("edges", []):
                    for so in e["node"].get("selectedOptions", []):
                        opts.add(so["name"])
            else:
                ptype = p.get("product_type") or ""
                vendor = p.get("vendor") or ""
                tags_raw = p.get("tags", "")
                tags = tags_raw if isinstance(tags_raw, list) else [t.strip() for t in tags_raw.split(",") if t.strip()]
                opts = set(o.get("name", "") for o in (p.get("options") or []))

            opts_lower = {o.lower() for o in opts}
            if opts_lower & SIZE_WORDS:
                has_size_option += 1
            if opts_lower & COLOR_WORDS:
                has_color_option += 1

            product_types[ptype] += 1
            vendors[vendor] += 1
            tags_per_product.append(len(tags))
            for t in tags:
                tag_counter[t] += 1
            option_name_sets[tuple(sorted(opts))] += 1
            if len(titles_by_type[ptype]) < 8:
                titles_by_type[ptype].append(title)

    out.write(f"Total products: {total}\n")

    out.write("\n--- product_type distribution (top 8) ---\n")
    for pt, c in product_types.most_common(8):
        out.write(f"  {c:6d}  {pt!r}\n")
    null_pt = product_types.get("", 0)
    out.write(f"  null/empty product_type: {null_pt} ({null_pt/total*100:.1f}%)\n")
    out.write(f"  distinct product_type values: {len(product_types)}\n")

    out.write("\n--- vendor distribution (top 6) ---\n")
    for v, c in vendors.most_common(6):
        out.write(f"  {c:6d}  {v!r}\n")

    out.write("\n--- variant OPTIONS field (structured Size/Color signal) ---\n")
    out.write(f"  products with a 'Size' option: {has_size_option} ({has_size_option/total*100:.1f}%)\n")
    out.write(f"  products with a 'Color' option: {has_color_option} ({has_color_option/total*100:.1f}%)\n")
    out.write("  top option-name combinations:\n")
    for opt_set, c in option_name_sets.most_common(8):
        out.write(f"    {c:6d}  {opt_set}\n")

    out.write("\n--- tags ---\n")
    out.write(f"  avg tags/product: {statistics.mean(tags_per_product):.1f}\n")
    out.write(f"  distinct tags across store: {len(tag_counter)}\n")
    out.write(f"  top 15 tags: {[t for t, _ in tag_counter.most_common(15)]}\n")

    out.write("\n--- title stats ---\n")
    out.write(f"  avg word count: {statistics.mean(title_word_counts):.1f}  (min {min(title_word_counts)}, max {max(title_word_counts)})\n")
    out.write(f"  % titles starting with a code-like token: {title_has_leading_code/total*100:.1f}%\n")

    out.write("\n--- sample titles for top 3 product_types (cross-category comparison) ---\n")
    for pt, cnt in product_types.most_common(3):
        out.write(f"  [{pt!r}] (n={cnt}) examples:\n")
        for t in titles_by_type[pt]:
            out.write(f"      - {t}\n")


def main():
    with open(REPORT_PATH, "w", encoding="utf-8") as out:
        for slug in STORE_SLUGS:
            analyze_store(slug, out)
    print("Report written to", REPORT_PATH)


if __name__ == "__main__":
    main()
