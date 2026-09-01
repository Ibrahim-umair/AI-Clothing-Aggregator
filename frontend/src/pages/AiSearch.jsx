import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import ProductCard from "../components/ProductCard.jsx";
import ProductCardSkeleton from "../components/ProductCardSkeleton.jsx";
import {
  SparklesIcon,
  ArrowUpIcon,
  SlidersIcon,
  PlusIcon,
  ShirtIcon,
  KurtaIcon,
  ShoeIcon,
  TShirtIcon,
  TrouserIcon,
  SunglassesIcon,
} from "../components/icons.jsx";
import { searchProducts } from "../lib/api.js";

// Situation-led, not brand-led — a brand name in a suggestion chip only
// ever helps the one shopper who already wanted that brand; an occasion
// ("a wedding", "a work presentation") is something everyone reads and
// immediately has their own version of. Kept to concise, real sentences,
// one set per gender so the row always feels like it was written for
// whoever's currently selected rather than a generic catch-all.
const EXAMPLES_BY_GENDER = {
  Men: [
    { icon: ShirtIcon, text: "A sharp shirt for a work presentation" },
    { icon: KurtaIcon, text: "Traditional kurta for Eid" },
    { icon: ShoeIcon, text: "Comfortable sneakers for everyday wear" },
    { icon: TShirtIcon, text: "Relaxed tee for a weekend hangout" },
    { icon: ShirtIcon, text: "Something sharp for a friend's wedding" },
    { icon: SunglassesIcon, text: "Sunglasses for a sunny day out" },
  ],
  Women: [
    { icon: KurtaIcon, text: "Elegant outfit for a wedding" },
    { icon: TShirtIcon, text: "Everyday kurti for work" },
    { icon: ShirtIcon, text: "Chic top for a night out" },
    { icon: TrouserIcon, text: "Smart trousers for the office" },
    { icon: ShoeIcon, text: "Comfortable flats for daily wear" },
    { icon: SunglassesIcon, text: "Sunglasses for a beach day" },
  ],
  Boys: [
    { icon: KurtaIcon, text: "Festive kurta for Eid" },
    { icon: TShirtIcon, text: "Everyday tee for school" },
    { icon: ShoeIcon, text: "Sturdy sneakers for play" },
    { icon: ShirtIcon, text: "Smart outfit for a family photo" },
  ],
  Girls: [
    { icon: KurtaIcon, text: "Pretty outfit for a birthday party" },
    { icon: TShirtIcon, text: "Comfy everyday joggers" },
    { icon: ShoeIcon, text: "Cute shoes for school" },
    { icon: ShirtIcon, text: "Festive outfit for Eid" },
  ],
};

// Sorts within the AI's own already-selected result set, not a fresh
// server query — this page returns a bounded, relevance-ranked pool (see
// rag.py's FINAL_POOL), not a full paginated browse of every match, so
// "sort by price" means "reorder what the AI already picked as relevant,"
// same as sorting the shortlist a person handed you rather than
// re-searching from scratch. Done client-side for exactly that reason: no
// second request, no risk of returning a DIFFERENT (less relevant) set.
const SORT_OPTIONS = [
  { value: "relevance", label: "Relevance" },
  { value: "price_asc", label: "Price: Low to High" },
  { value: "price_desc", label: "Price: High to Low" },
];

function sortProducts(products, sort) {
  if (sort === "price_asc") return [...products].sort((a, b) => (a.price ?? Infinity) - (b.price ?? Infinity));
  if (sort === "price_desc") return [...products].sort((a, b) => (b.price ?? -Infinity) - (a.price ?? -Infinity));
  return products;
}

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


export default function AiSearch() {
  // The query and gender live in the URL, not component state, so browser
  // back/forward and reload all restore the search exactly — this page is
  // a real destination people navigate away from (into a product) and
  // come back to.
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const genderParam = searchParams.get("gender");
  const genderFilter = genderParam === GENDER_ANY ? null : genderParam || DEFAULT_GENDER;
  const sort = searchParams.get("sort") || "relevance";
  // Boys/Girls are real, separately-selectable genders (never merged into a
  // combined "Kids" value — the search backend has no such concept, and
  // introducing one client-side would just reintroduce that ambiguity).
  // "Kids mode" is derived purely from which gender is active, not a
  // separate piece of state — see toggleKidsMode below, which moves this
  // by actually changing the selected gender rather than tracking a
  // parallel "mode" flag that could drift out of sync with it.
  const isKidsMode = genderFilter === "Boys" || genderFilter === "Girls";
  const examples = EXAMPLES_BY_GENDER[genderFilter] || EXAMPLES_BY_GENDER[DEFAULT_GENDER];

  // Deliberately NOT initialized from `query` — the composer always starts
  // empty (placeholder showing), whether that's the very first visit or a
  // refinement after results are already on screen. What was searched is
  // already visible in the answer/results above; echoing it back into the
  // input just makes "type something new" harder, not easier.
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [result, setResult] = useState(() => (query ? readCache(query, genderFilter) : null));
  // Once a search has been made, the gender/kids toggle moves off the page
  // and behind this icon next to the sticky composer — filtersOpen controls
  // whether that small panel is showing.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const filtersRef = useRef(null);
  const filtersToggleRef = useRef(null);

  // Clears the composer back to empty every time the searched query
  // changes — covers a fresh submission, a suggestion-chip refinement, and
  // back/forward navigation landing on a different query, all the same
  // way: whatever was searched is already shown above, so the input is
  // always ready for the NEXT thing rather than echoing the last one.
  useEffect(() => {
    setDraft("");
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

  // Closes the sticky filter panel on an outside click, same pattern as
  // the header's mega-menu — without this it stays open across an
  // unrelated click anywhere else on the page.
  useEffect(() => {
    if (!filtersOpen) return;
    function onPointerDown(e) {
      if (filtersRef.current?.contains(e.target)) return;
      if (filtersToggleRef.current?.contains(e.target)) return;
      setFiltersOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [filtersOpen]);

  function submitQuery(q, gender) {
    const trimmed = q.trim();
    if (!trimmed) return;
    const next = { q: trimmed };
    if (gender !== DEFAULT_GENDER) next.gender = gender || GENDER_ANY;
    setSearchParams(next);
    setFiltersOpen(false);
  }

  function onSubmit(e) {
    e.preventDefault();
    submitQuery(draft, genderFilter);
  }

  function setGender(g) {
    const params = {};
    if (query) params.q = query;
    if (g !== DEFAULT_GENDER) params.gender = g || GENDER_ANY;
    if (sort !== "relevance") params.sort = sort;
    // replace, not push — flipping a filter shouldn't stack history
    // entries the back button then has to walk through one at a time.
    setSearchParams(params, { replace: true });
  }

  function setSort(nextSort) {
    const params = { q: query };
    if (genderFilter !== DEFAULT_GENDER) params.gender = genderFilter || GENDER_ANY;
    if (nextSort !== "relevance") params.sort = nextSort;
    setSearchParams(params, { replace: true });
  }

  function toggleGender(g) {
    if (isKidsMode) {
      // There's no way to express "kids, unspecified" to the backend (see
      // the "kids" gender gap this whole toggle exists to work around) —
      // so unlike Men/Women, Boys/Girls never has a cleared third state.
      // Exactly one of the two is always active while in kids mode.
      setGender(g);
      return;
    }
    setGender(genderFilter === g ? null : g);
  }

  // The button that actually swaps the toggle's contents between
  // Men/Women and Boys/Girls — moves the real gender selection (to a
  // sensible default for whichever side it's entering) rather than
  // tracking a separate "mode" flag, so isKidsMode never has a chance to
  // drift out of sync with what's actually selected.
  function toggleKidsMode() {
    setGender(isKidsMode ? DEFAULT_GENDER : "Boys");
  }

  // Ends the current search and returns to the hero landing state — a
  // real "start over," not just clearing the input. Keeps whichever
  // gender/kids selection was active (that's a shopping preference, not
  // part of the conversation being ended) and drops only the query itself.
  function newChat() {
    const params = {};
    if (genderFilter !== DEFAULT_GENDER) params.gender = genderFilter || GENDER_ANY;
    setSearchParams(params);
    setFiltersOpen(false);
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

  function renderModeRow() {
    return (
      <div className="ai-search__mode-row">
        <div
          className={`ai-search__gender-toggle${isKidsMode ? " ai-search__gender-toggle--kids" : ""}`}
          role="group"
          aria-label="Shop for"
        >
          {isKidsMode ? (
            <>
              <button
                type="button"
                className={`ai-search__gender-btn${genderFilter === "Boys" ? " ai-search__gender-btn--active" : ""}`}
                onClick={() => toggleGender("Boys")}
              >
                Boys
              </button>
              <button
                type="button"
                className={`ai-search__gender-btn${genderFilter === "Girls" ? " ai-search__gender-btn--active" : ""}`}
                onClick={() => toggleGender("Girls")}
              >
                Girls
              </button>
            </>
          ) : (
            <>
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
            </>
          )}
        </div>
        <button
          type="button"
          className={`ai-search__kids-toggle${isKidsMode ? " ai-search__kids-toggle--active" : ""}`}
          onClick={toggleKidsMode}
          aria-pressed={isKidsMode}
        >
          Kids
        </button>
      </div>
    );
  }

  return (
    <div className={`ai-search${isKidsMode ? " ai-search--kids" : ""}`}>
      {!query && (
        <div className="ai-search__hero">
          <h1 className="ai-search__headline">
            Shop across Pakistan's best brands with one <em>intelligent search</em>.
          </h1>
          <p className="ai-search__subtext">
            Describe what you're looking for in your own words. Libas searches the whole real
            catalog — every store, one line — to find the right pieces for you.
          </p>

          {renderModeRow()}

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

          <div className="ai-search__examples">
            {examples.map(({ icon: Icon, text }) => (
              <button type="button" key={text} className="ai-search__example-chip" onClick={() => submitQuery(text, genderFilter)}>
                <Icon size={15} />
                {text}
              </button>
            ))}
          </div>
        </div>
      )}

      {query && (
        <div className="ai-search__results ai-search__results--chat">
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
              <h3>AI mode is taking a short break</h3>
              <p>We've hit a snag on our end and the team's already on it. Please check back shortly — or browse the regular Shop page in the meantime.</p>
              <button type="button" className="btn btn--primary" onClick={retry}>
                Try again
              </button>
            </div>
          ) : result ? (
            <>
              <div className="ai-search__results-header">
                <div className="ai-search__answer">
                  <SparklesIcon size={15} />
                  <span>{result.response_text}</span>
                </div>
                {result.products.length > 1 && (
                  <label className="select-control">
                    <span className="select-control__label">Sort by</span>
                    <span className="select-control__field">
                      <select value={sort} onChange={(e) => setSort(e.target.value)}>
                        {SORT_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </span>
                  </label>
                )}
              </div>

              {/* Next-query suggestions, not a readout of the filters just
                  applied — each chip is a real subtype/fit/style word for
                  THIS result set (see suggested_refinements in search.js),
                  and clicking one submits a brand-new search combining it
                  with the current query. There's no actual multi-turn
                  memory behind this (each search is independent — see
                  runSearch), so the refinement is folded into the query
                  TEXT itself rather than relying on the backend to
                  remember anything from this turn. */}
              {result.filters.suggested_refinements?.length > 0 && (
                <div className="ai-search__chips">
                  {result.filters.suggested_refinements.map((r, i) => (
                    <button
                      type="button"
                      className="ai-search__chip--action"
                      key={i}
                      onClick={() => submitQuery(`${query}, ${r}`, genderFilter)}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              )}

              {result.products.length === 0 ? (
                <div className="empty-state">
                  <h3>Nothing matched that</h3>
                  <p>Try describing it a little differently, or broaden the budget/brand.</p>
                </div>
              ) : (
                <div className="product-grid product-grid--5">
                  {sortProducts(result.products, sort).map((p) => (
                    <ProductCard key={p.id} product={p} />
                  ))}
                </div>
              )}
            </>
          ) : null}
        </div>
      )}

      {/* Replaces the hero composer once a search is underway — this is
          the "new chat session" moment: the pitch/headline/examples are
          gone, and searching from here on reads as continuing a
          conversation rather than starting over on a landing page. The
          gender/kids toggle moves behind the sliders icon so the bar
          stays a single slim line instead of growing back into the hero. */}
      {query && (
        <div className="ai-search__sticky-bar">
          {filtersOpen && (
            <div className="ai-search__sticky-filters" ref={filtersRef}>
              {renderModeRow()}
            </div>
          )}
          <form className="ai-search__composer ai-search__composer--sticky" onSubmit={onSubmit}>
            <button
              type="button"
              className="ai-search__filter-toggle"
              onClick={newChat}
              aria-label="Start a new chat"
              title="Start a new chat"
            >
              <PlusIcon size={16} />
            </button>
            <button
              type="button"
              ref={filtersToggleRef}
              className={`ai-search__filter-toggle${filtersOpen ? " ai-search__filter-toggle--active" : ""}`}
              onClick={() => setFiltersOpen((v) => !v)}
              aria-label="Change who you're shopping for"
              aria-expanded={filtersOpen}
            >
              <SlidersIcon size={16} />
            </button>
            <input
              className="ai-search__composer-input ai-search__composer-input--sticky"
              placeholder="Explore further, or ask something else…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <button type="submit" className="ai-search__submit ai-search__submit--sticky" disabled={loading || !draft.trim()} aria-label="Search">
              <ArrowUpIcon size={16} />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
