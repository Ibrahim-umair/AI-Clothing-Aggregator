import { useState } from "react";
import ProductCard from "../components/ProductCard.jsx";
import ProductCardSkeleton from "../components/ProductCardSkeleton.jsx";
import {
  SparklesIcon,
  ArrowUpIcon,
  ShirtIcon,
  KurtaIcon,
  ShoeIcon,
  TShirtIcon,
  TrouserIcon,
  SunglassesIcon,
} from "../components/icons.jsx";
import { searchProducts } from "../lib/api.js";

// Real, varied example queries — each pairs with a garment icon already
// used elsewhere in the app (quick-category chips, mega-menu), so this
// isn't new iconography invented for this page. Exercises different parts
// of the pipeline: budget+category, occasion+category, brand+category,
// fuzzy/subjective with no explicit category, plain category+budget.
const EXAMPLE_QUERIES = [
  { icon: ShirtIcon, text: "Smart casual shirts under PKR 3,000" },
  { icon: KurtaIcon, text: "Formal kurta for a wedding" },
  { icon: ShoeIcon, text: "Minimal white sneakers" },
  { icon: TShirtIcon, text: "Cozy sweaters for women under 5,000" },
  { icon: TrouserIcon, text: "Royal Tag formal trousers" },
  { icon: SunglassesIcon, text: "Sunglasses under 2,000" },
];

// The extracted filter chips shown under the answer line — read-only
// visibility into what the pipeline understood (same idea as Shop.jsx's
// active-chips row, not an editable filter sidebar).
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
  // Defaults to "Men" (matching the supplied reference). Whatever is
  // selected overrides what the model would infer from the text itself
  // (see runSearch's genderOverride) — a person who has "Men" selected
  // and types "red kurta" means Men's kurtas regardless of whether the
  // text says so. Clicking the active button clears it back to null,
  // which is a real state meaning "let the AI decide from what I typed".
  const [genderFilter, setGenderFilter] = useState("Men");
  const [query, setQuery] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [result, setResult] = useState(null);

  async function runSearch(q, gender) {
    const trimmed = q.trim();
    if (!trimmed) return;
    setQuery(trimmed);
    setDraft(trimmed);
    setLoading(true);
    setError(false);
    setResult(null);
    try {
      const data = await searchProducts(trimmed, gender);
      setResult(data);
    } catch (err) {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e) {
    e.preventDefault();
    runSearch(draft, genderFilter);
  }

  function toggleGender(g) {
    setGenderFilter((cur) => (cur === g ? null : g));
  }

  return (
    <div className="ai-search">
      <div className="ai-search__hero">
        <h1 className="ai-search__headline">
          Shop across Pakistan's best brands with one <em>intelligent search</em>.
        </h1>
        <p className="ai-search__subtext">
          Describe what you're looking for in your own words. Libas searches the whole real
          catalog — every store, one line — to find the right pieces for you.
        </p>

        <div className="ai-search__gender-toggle" role="group" aria-label="Shop for">
          <button
            type="button"
            className={`ai-search__gender-btn${genderFilter === "Men" ? " ai-search__gender-btn--active" : ""}`}
            onClick={() => toggleGender("Men")}
          >
            Men
          </button>
          <button
            type="button"
            className={`ai-search__gender-btn${genderFilter === "Women" ? " ai-search__gender-btn--active" : ""}`}
            onClick={() => toggleGender("Women")}
          >
            Women
          </button>
        </div>

        <form className="ai-search__composer" onSubmit={onSubmit}>
          <input
            autoFocus
            className="ai-search__composer-input"
            placeholder="Ask anything. Describe your style, occasion or need…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="ai-search__composer-actions">
            <span className="ai-search__composer-hint">
              <SparklesIcon size={15} />
              Powered by Libas AI
            </span>
            <button type="submit" className="ai-search__submit" disabled={loading || !draft.trim()} aria-label="Search">
              <ArrowUpIcon size={17} />
            </button>
          </div>
        </form>

        {!query && (
          <div className="ai-search__examples">
            {EXAMPLE_QUERIES.map(({ icon: Icon, text }) => (
              <button type="button" key={text} className="ai-search__example-chip" onClick={() => runSearch(text, genderFilter)}>
                <Icon size={15} />
                {text}
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
              <button type="button" className="btn btn--primary" onClick={() => runSearch(query, genderFilter)}>
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
