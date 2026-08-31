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

async function getJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    // status is attached (not just embedded in the message string) so
    // callers can tell "the thing you asked for doesn't exist" (404) apart
    // from "the server/network is broken" (everything else) without
    // parsing text — e.g. ProductDetail shows different copy for a
    // genuinely deleted product vs. a real outage.
    const err = new Error(`API ${path} failed: ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function postJSON(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = new Error(`API ${path} failed: ${res.status}`);
    err.status = res.status;
    throw err;
  }
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
  if (q) params.set("q", q);
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
  return postJSON("/search", { query, gender });
}
