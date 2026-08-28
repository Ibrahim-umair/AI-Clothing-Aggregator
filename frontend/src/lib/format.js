export function formatPrice(value, currency = "PKR") {
  if (value == null || Number.isNaN(value)) return "";
  const rounded = Math.round(value);
  const withCommas = rounded.toLocaleString("en-PK");
  const symbol = currency === "PKR" ? "Rs." : currency;
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
