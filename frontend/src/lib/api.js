// Thin fetch client for the Libas API (server/, FastAPI). Locally this
// stays a relative "/api" and rides vite.config.js's dev proxy to
// localhost:4000 — same-origin, no CORS involved. In production the
// frontend (Cloudflare Pages) and backend (a separate EC2 host) are on
// different origins, so a relative path would resolve against the
// frontend's own domain instead. VITE_API_BASE, set in Cloudflare Pages'
// build environment variables, points it at the real backend instead;
// unset (local dev, `npm run build` with no env override) it falls back
// to the old relative "/api" behavior unchanged.
const API_BASE = import.meta.env.VITE_API_BASE || "/api";

// Must match MAX_QUERY_LENGTH in server/models.py — the server rejects
// anything longer with a 422, so inputs cap themselves here first.
export const MAX_QUERY_LENGTH = 300;
// Shop's title search — server/routes/products.py MAX_TITLE_QUERY_LENGTH.
export const MAX_SHOP_QUERY_LENGTH = 100;

// Same normalization the server applies (server/models.py clean_query):
// control characters and runs of whitespace collapse to one space.
export function cleanQuery(text) {
  return String(text ?? "")
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f\u007f]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_QUERY_LENGTH);
}

function apiError(path, res) {
  // status is attached (not just embedded in the message string) so
  // callers can tell "the thing you asked for doesn't exist" (404) apart
  // from "the server/network is broken" (everything else) without
  // parsing text — e.g. ProductDetail shows different copy for a
  // genuinely deleted product vs. a real outage. retryAfter (seconds) is
  // set on a 429 from the search rate limiter.
  const err = new Error(`API ${path} failed: ${res.status}`);
  err.status = res.status;
  const retryAfter = Number(res.headers.get("Retry-After"));
  if (retryAfter > 0) err.retryAfter = retryAfter;
  return err;
}

async function getJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw apiError(path, res);
  return res.json();
}

async function postJSON(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw apiError(path, res);
  return res.json();
}

function selectionParams(selection = {}) {
  const params = new URLSearchParams();
  if (selection.gender) params.set("gender", selection.gender);
  if (selection.branch) params.set("branch", selection.branch);
  if (selection.sub) params.set("sub", selection.sub);
  if (selection.category) params.set("category", selection.category);
  if (selection.store) params.set("brand", selection.store);
  return params;
}

export function fetchProducts(
  selection = {},
  { page = 1, pageSize = 24, sort, minPrice, maxPrice, sizes, colors, q, onSale, includeOutOfStock } = {}
) {
  const params = selectionParams(selection);
  params.set("page", page);
  params.set("pageSize", pageSize);
  if (sort) params.set("sort", sort);
  if (minPrice) params.set("minPrice", minPrice);
  if (maxPrice) params.set("maxPrice", maxPrice);
  if (sizes?.length) params.set("size", sizes.join(","));
  if (colors?.length) params.set("color", colors.join(","));
  if (q) params.set("q", cleanQuery(q).slice(0, MAX_SHOP_QUERY_LENGTH));
  if (onSale) params.set("onSale", "true");
  if (includeOutOfStock) params.set("includeOutOfStock", "true");
  return getJSON(`/products?${params.toString()}`);
}

export function fetchProduct(id) {
  return getJSON(`/products/${id}`);
}

export function fetchTaxonomy(selection = {}) {
  const params = selectionParams(selection);
  return getJSON(`/taxonomy?${params.toString()}`);
}

export function fetchBrands() {
  return getJSON("/brands");
}

// POST /api/search — natural-language search (server/search.js). See
// server/SEARCH.md for the full pipeline design. `gender`, if passed
// (from an explicit UI toggle), overrides whatever the model would have
// inferred from the query text — see runSearch()'s genderOverride.
export function searchProducts(query, gender = null) {
  return postJSON("/search", { query: cleanQuery(query), gender });
}
