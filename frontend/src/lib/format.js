export function formatPrice(value, currency = "PKR") {
  if (value == null || Number.isNaN(value)) return "";
  const rounded = Math.round(value);
  const withCommas = rounded.toLocaleString("en-PK");
  const symbol = currency === "PKR" ? "Rs" : currency;
  return `${symbol} ${withCommas}`;
}

export function discountPercent(price, compareAt) {
  if (!compareAt || compareAt <= price) return null;
  return Math.round(((compareAt - price) / compareAt) * 100);
}

// The scraper's strip_html() only strips tags, it never decodes entities
// (see db/load_data.py) — every stored description with a "&amp;", "&#39;",
// etc. in the source HTML still has that literal entity text in it. Decoded
// here at render time via the browser's own parser (a <textarea> never
// executes its content, so this is safe even though the input originated
// as HTML) rather than fixing it in the scraper + re-backfilling ~96k rows.
export function decodeHtmlEntities(str) {
  if (!str) return str;
  const el = document.createElement("textarea");
  el.innerHTML = str;
  return el.value;
}

// Store titles arrive however each brand typed them — many are ALL CAPS
// ("PERFORMANCE BLUE T-SHIRT"), some carry SKU codes ("... - EGTKE22-70359")
// or outlet tags ("(E-FACTORY OUTLET)"). Cleaned for display only; the stored
// title is untouched. Mixed-case titles are left as the brand wrote them.
const SMALL_WORDS = new Set(["a", "an", "and", "as", "at", "for", "in", "of", "on", "or", "the", "to", "with"]);

export function displayTitle(title) {
  if (!title) return title;
  let t = title
    .replace(/\(\s*e-?factory outlet\s*\)/gi, "")
    .replace(/\s+-\s+[A-Z0-9]{2,}[A-Z0-9-]*\d[A-Z0-9-]*\s*$/, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  const letters = t.replace(/[^A-Za-z]/g, "");
  const isAllCaps = letters.length > 3 && letters === letters.toUpperCase();
  if (!isAllCaps) return t;
  return t
    .toLowerCase()
    .split(" ")
    .map((w, i) => {
      if (i > 0 && SMALL_WORDS.has(w)) return w;
      // keep hyphenated parts capitalised: "t-shirt" -> "T-Shirt"
      return w.replace(/(^|-)([a-z])/g, (_, sep, c) => sep + c.toUpperCase());
    })
    .join(" ");
}
