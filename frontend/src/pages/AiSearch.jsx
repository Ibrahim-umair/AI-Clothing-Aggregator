import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
// isn't new iconography invented for this page.
const EXAMPLE_QUERIES = [
  { icon: ShirtIcon, text: "Smart casual shirts under PKR 3,000" },
  { icon: KurtaIcon, text: "Formal kurta for a wedding" },
  { icon: ShoeIcon, text: "Minimal white sneakers" },
  { icon: TShirtIcon, text: "Cozy sweaters under 5,000" },
  { icon: TrouserIcon, text: "Royal Tag formal trousers" },
  { icon: SunglassesIcon, text: "Sunglasses under 2,000" },
];

const DEFAULT_GENDER = "Men";
// Sentinel for "explicitly cleared" in the URL. Needed because an absent
// ?gender= means "untouched, use the default", which is NOT the same as
// the user having deliberately cleared the toggle to let the AI infer
// gender from the text. Without this the cleared state would silently
// snap back to Men on reload or back-navigation.
const GENDER_ANY = "any";

// Results are cached per (query, gender) so returning from a product page
// restores the previous search instantly — no second LLM call, no repaid
// latency or cost. sessionStorage (not localStorage) because a stale
// price/stock snapshot shouldn't outlive the tab; every fresh visit
// re-queries. Both reads and writes are guarded: storage throws outright
// in some contexts (private windows, blocked site data, quota), and a
// failed cache must degrade to "just fetch it again", never to a crash.
function cacheKey(query, gender) {
  return `libas-ai-search:${gender || GENDER_ANY}:${query}`;
}
function readCache(query, gender) {
  try {
    const raw = sessionStorage.getItem(cacheKey(query, gender));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
function writeCache(query, gender, data) {
  try {
    sessionStorage.setItem(cacheKey(query, gender), JSON.stringify(data));
  } catch {
    /* quota or blocked storage — the search still works, it just won't restore for free */
  }
}

// The extracted filter chips shown under the answer line — read-only
// visibility into what the pipeline understood.
function filterChips(filters) {
  const chips = [];
  if (filters.gender) chips.push(filters.gender);
  (filters.categories || []).forEach((c) => chips.push(c));
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
  // The query and gender live in the URL, not component state, so browser
  // back/forward and reload all restore the search exactly — this page is
  // a real destination people navigate away from (into a product) and
  // come back to.
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const genderParam = searchParams.get("gender");
  const genderFilter = genderParam === GENDER_ANY ? null : genderParam || DEFAULT_GENDER;

  const [draft, setDraft] = useState(query);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [result, setResult] = useState(() => (query ? readCache(query, genderFilter) : null));

  // Keep the input in sync when the URL changes underneath us (back /
  // forward navigation), without clobbering what someone is mid-typing on
  // this page — the URL only changes on submit or history navigation.
  useEffect(() => {
    setDraft(query);
  }, [query]);

  useEffect(() => {
    if (!query) {
      setResult(null);
      setError(false);
      return;
    }
    const cached = readCache(query, genderFilter);
    if (cached) {
      setResult(cached);
      setError(false);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(false);
    setResult(null);
    searchProducts(query, genderFilter)
      .then((data) => {
        if (cancelled) return;
        setResult(data);
        writeCache(query, genderFilter, data);
      })
      .catch(() => !cancelled && setError(true))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [query, genderFilter]);

  function submitQuery(q, gender) {
    const trimmed = q.trim();
    if (!trimmed) return;
    const next = { q: trimmed };
    if (gender !== DEFAULT_GENDER) next.gender = gender || GENDER_ANY;
    setSearchParams(next);
  }

  function onSubmit(e) {
    e.preventDefault();
    submitQuery(draft, genderFilter);
  }

  function toggleGender(g) {
    const next = genderFilter === g ? null : g;
    const params = {};
    if (query) params.q = query;
    if (next !== DEFAULT_GENDER) params.gender = next || GENDER_ANY;
    // replace, not push — flipping a filter shouldn't stack history
    // entries the back button then has to walk through one at a time.
    setSearchParams(params, { replace: true });
  }

  function retry() {
    try {
      sessionStorage.removeItem(cacheKey(query, genderFilter));
    } catch {
      /* nothing cached to clear */
    }
    setError(false);
    setLoading(true);
    searchProducts(query, genderFilter)
      .then((data) => {
        setResult(data);
        writeCache(query, genderFilter, data);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
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
              <button type="button" key={text} className="ai-search__example-chip" onClick={() => submitQuery(text, genderFilter)}>
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
                <span className="skeleton-line" />
              </div>
              <div className="product-grid product-grid--5">
                {Array.from({ length: 10 }, (_, i) => (
                  <ProductCardSkeleton key={i} />
                ))}
              </div>
            </>
          ) : error ? (
            <div className="empty-state">
              <h3>Couldn't reach the search engine</h3>
              <p>Something went wrong talking to the server. Check your connection and try again.</p>
              <button type="button" className="btn btn--primary" onClick={retry}>
                Try again
              </button>
            </div>
          ) : result ? (
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
                <div className="product-grid product-grid--5">
                  {result.products.map((p) => (
                    <ProductCard key={p.id} product={p} />
                  ))}
                </div>
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
