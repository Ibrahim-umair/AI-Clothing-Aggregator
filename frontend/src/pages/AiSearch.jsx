import { useState } from "react";
import ProductCard from "../components/ProductCard.jsx";
import ProductCardSkeleton from "../components/ProductCardSkeleton.jsx";
import { SparklesIcon, SearchIcon } from "../components/icons.jsx";
import { searchProducts } from "../lib/api.js";

// A handful of real, varied example queries — not filler copy, each one
// exercises a different part of the pipeline (a plain category+budget
// query, a brand-specific one, a fuzzy/subjective one with no explicit
// category at all) so a first-time visitor sees the range of what this
// actually understands, not just one style of query.
const EXAMPLE_QUERIES = [
  "cozy warm sweaters for women under 5000",
  "formal kurta for a wedding, men, under 8000",
  "royal tag formal shirt",
  "girls party dress under 3000",
];

// The extracted filter chips shown under the answer line — same idea as
// Shop.jsx's active-chips row, but read-only (this is "here's what it
// understood", not an editable filter sidebar — see AiSearch.md-style
// framing in the conversation this was built from: the point is
// visibility into the pipeline, not replacing the structured Shop page).
function filterChips(filters) {
  const chips = [];
  if (filters.gender) chips.push(filters.gender);
  if (filters.category) chips.push(filters.category);
  if (filters.brand) chips.push(filters.brand);
  if (filters.minPrice != null || filters.maxPrice != null) {
    const min = filters.minPrice != null ? `PKR ${filters.minPrice.toLocaleString()}` : "";
    const max = filters.maxPrice != null ? `PKR ${filters.maxPrice.toLocaleString()}` : "";
    chips.push(min && max ? `${min} – ${max}` : max ? `Under ${max}` : `Over ${min}`);
  }
  if (filters.onSale) chips.push("On Sale");
  (filters.colors || []).forEach((c) => chips.push(c));
  (filters.sizes || []).forEach((s) => chips.push(`Size ${s}`));
  return chips;
}

export default function AiSearch() {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [result, setResult] = useState(null);

  async function runSearch(q) {
    const trimmed = q.trim();
    if (!trimmed) return;
    setQuery(trimmed);
    setDraft(trimmed);
    setLoading(true);
    setError(false);
    setResult(null);
    try {
      const data = await searchProducts(trimmed);
      setResult(data);
    } catch (err) {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e) {
    e.preventDefault();
    runSearch(draft);
  }

  return (
    <div className="ai-search">
      <div className="ai-search__hero">
        <span className="ai-search__eyebrow">
          <SparklesIcon size={14} />
          AI-Powered Search
        </span>
        <h1>Describe what you're looking for</h1>
        <p>
          Not filters and dropdowns — just say it plainly. "Cozy sweaters under 5,000",
          "formal kurta for a wedding" — the whole real catalog, searched in one line.
        </p>

        <form className="ai-search__bar" onSubmit={onSubmit}>
          <SearchIcon size={17} />
          <input
            autoFocus
            placeholder="Search in plain English…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <button type="submit" className="btn btn--primary" disabled={loading || !draft.trim()}>
            {loading ? "Searching…" : "Search"}
          </button>
        </form>

        {!query && (
          <div className="ai-search__examples">
            <span>Try:</span>
            {EXAMPLE_QUERIES.map((q) => (
              <button type="button" key={q} className="ai-search__example-chip" onClick={() => runSearch(q)}>
                {q}
              </button>
            ))}
          </div>
        )}
      </div>

      {query && (
        <div className="ai-search__results">
          {loading ? (
            <>
              <div className="ai-search__answer ai-search__answer--loading">
                <SparklesIcon size={15} />
                <span className="skeleton-line" style={{ width: "60%" }} />
              </div>
              <div className="product-grid product-grid--4">
                {Array.from({ length: 8 }, (_, i) => (
                  <ProductCardSkeleton key={i} />
                ))}
              </div>
            </>
          ) : error ? (
            <div className="empty-state">
              <h3>Couldn't reach the search engine</h3>
              <p>Something went wrong talking to the server. Check your connection and try again.</p>
              <button type="button" className="btn btn--primary" onClick={() => runSearch(query)}>
                Try again
              </button>
            </div>
          ) : (
            <>
              <div className="ai-search__answer">
                <SparklesIcon size={15} />
                <span>{result.response_text}</span>
              </div>

              <div className="ai-search__chips">
                {filterChips(result.filters).map((c, i) => (
                  <span className="ai-search__chip" key={i}>
                    {c}
                  </span>
                ))}
                {filterChips(result.filters).length === 0 && (
                  <span className="ai-search__chip ai-search__chip--muted">No specific filters detected — ranked by meaning alone</span>
                )}
              </div>

              {result.products.length === 0 ? (
                <div className="empty-state">
                  <h3>Nothing matched that</h3>
                  <p>Try describing it a little differently, or broaden the budget/brand.</p>
                </div>
              ) : (
                <div className="product-grid product-grid--4">
                  {result.products.map((p) => (
                    <ProductCard key={p.id} product={p} />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
