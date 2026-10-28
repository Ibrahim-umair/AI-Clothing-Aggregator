import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useNavigationType, useSearchParams } from "react-router-dom";
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

// Search v2 (server/search_v2.py) can answer one query with several
// searches, e.g. an occasion becomes kurtas + waistcoats + shawls, each
// returned as its own group. v1 has no groups, so it reads as one untitled
// group and renders exactly as before.
function resultGroups(result) {
  return result.groups?.length ? result.groups : [{ label: null, query: null, products: result.products }];
}

// One group: its title (only when there are several), the rewritten query
// it actually searched for, its matches, then any "close alternatives"
// (products that don't state what was asked for, e.g. a fit) after a
// divider instead of mixed in with the real matches.
function ResultGroup({ group, showTitle, sort }) {
  const matches = group.products.filter((p) => !p.alternative);
  const alternatives = group.products.filter((p) => p.alternative);
  return (
    <section className="ai-search__group">
      {(showTitle || group.query) && (
        <div className="ai-search__group-head">
          {showTitle && <h2 className="ai-search__group-title">{group.label}</h2>}
          {group.query && <p className="ai-search__group-query">Searched for “{group.query}”</p>}
        </div>
      )}
      {matches.length > 0 && (
        <div className="product-grid product-grid--5">
          {sortProducts(matches, sort).map((p) => (
            <ProductCard key={p.id} product={p} />
          ))}
        </div>
      )}
      {alternatives.length > 0 && (
        <>
          <p className="ai-search__alt-divider">
            {matches.length ? "Close alternatives" : "No exact matches. Closest alternatives"}
          </p>
          <div className="product-grid product-grid--5">
            {sortProducts(alternatives, sort).map((p) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

const DEFAULT_GENDER = "Men";
// Sentinel for "explicitly cleared" in the URL. Needed because an absent
// ?gender= means "untouched, use the default", which is NOT the same as
// the user having deliberately cleared the toggle to let the AI infer
// gender from the text. Without this the cleared state would silently
// snap back to Men on reload or back-navigation.
const GENDER_ANY = "any";

// Results are cached per (query, gender) so asking the same thing again,
// or restoring the thread, costs no second LLM call. sessionStorage (not
// localStorage) because a stale price/stock snapshot shouldn't outlive the
// tab. Every read and write is guarded: storage throws outright in some
// contexts (private windows, blocked site data, quota), and a failed cache
// must degrade to "just fetch it again", never to a crash.
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

// The conversation itself: every query asked in this tab, in order, each
// with its own results. Kept in sessionStorage so opening a product and
// coming back restores the whole thread (and the scroll position) instead
// of just the last search.
const THREAD_KEY = "libas-ai-thread";
const SCROLL_KEY = "libas-ai-thread-scroll";
function readThread() {
  try {
    const turns = JSON.parse(sessionStorage.getItem(THREAD_KEY) || "[]");
    return Array.isArray(turns) ? turns : [];
  } catch {
    return [];
  }
}
function writeThread(turns) {
  try {
    // Results live in the per-query cache; the thread only stores what was asked.
    sessionStorage.setItem(THREAD_KEY, JSON.stringify(turns.map(({ id, query, gender }) => ({ id, query, gender }))));
  } catch {
    /* see writeCache */
  }
}

// What the AI made of the query: the rewritten search(es), the product
// types it filtered to, the words a product must (and must not) state, and
// the hard filters. Shown under each answer so a wrong reading is visible
// instead of just producing odd results.
function Understanding({ result }) {
  const f = result.filters || {};
  const hard = [
    f.gender && `For: ${f.gender}`,
    f.colors?.length > 0 && `Color: ${f.colors.join(", ")}`,
    f.sizes?.length > 0 && `Size: ${f.sizes.join(", ")}`,
    f.minPrice != null && `From Rs ${f.minPrice}`,
    f.maxPrice != null && `Under Rs ${f.maxPrice}`,
    f.brand && `Brand: ${f.brand}`,
    f.onSale && "On sale",
  ].filter(Boolean);
  const groups = result.groups?.length ? result.groups : null;

  return (
    <details className="ai-understood" open>
      <summary>How Libas read this</summary>
      {hard.length > 0 && (
        <div className="ai-understood__row">
          {hard.map((h) => (
            <span key={h} className="ai-understood__chip">{h}</span>
          ))}
        </div>
      )}
      {groups ? (
        groups.map((g, i) => (
          <div key={i} className="ai-understood__search">
            <div className="ai-understood__query">
              {groups.length > 1 && <b>{g.label}: </b>}“{g.query}”
            </div>
            <div className="ai-understood__row">
              {(g.categories || []).map((c) => (
                <span key={c} className="ai-understood__chip">{c}</span>
              ))}
              {(g.must_have || []).map((w) => (
                <span key={`+${w}`} className="ai-understood__chip ai-understood__chip--have">+ {w}</span>
              ))}
              {(g.must_not || []).map((w) => (
                <span key={`-${w}`} className="ai-understood__chip ai-understood__chip--not">− {w}</span>
              ))}
            </div>
            {(g.notes || []).map((n) => (
              <p key={n} className="ai-understood__note">{n}</p>
            ))}
          </div>
        ))
      ) : (
        <div className="ai-understood__row">
          {(f.categories || []).map((c) => (
            <span key={c} className="ai-understood__chip">{c}</span>
          ))}
          {f.semantic_query && <span className="ai-understood__chip">keywords: {f.semantic_query}</span>}
        </div>
      )}
    </details>
  );
}

// One question + answer in the thread.
function Turn({ turn, onRetry, turnRef }) {
  const [sort, setSort] = useState("relevance");
  const { result, status } = turn;
  const groups = result ? resultGroups(result) : [];
  const count = groups.reduce((n, g) => n + g.products.length, 0);

  return (
    <article className="ai-turn" ref={turnRef}>
      <div className="ai-turn__question">
        <span>{turn.query}</span>
        {turn.gender && <span className="ai-turn__for">{turn.gender}</span>}
      </div>

      {status === "loading" && (
        <>
          <div className="ai-search__answer ai-search__answer--loading">
            <SparklesIcon size={15} />
            <span className="skeleton-line" />
          </div>
          <div className="product-grid product-grid--5">
            {Array.from({ length: 5 }, (_, i) => (
              <ProductCardSkeleton key={i} />
            ))}
          </div>
        </>
      )}

      {status === "error" && (
        <div className="empty-state">
          <h3>AI mode is taking a short break</h3>
          <p>We've hit a snag on our end. Try again in a moment.</p>
          <button type="button" className="btn btn--primary" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}

      {status === "done" && result && (
        <>
          <div className="ai-search__results-header">
            <div className="ai-search__answer">
              <SparklesIcon size={15} />
              <span>{result.response_text}</span>
            </div>
            {count > 1 && (
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

          <Understanding result={result} />

          {count === 0 ? (
            <div className="empty-state">
              <h3>Nothing matched that</h3>
              <p>Try describing it a little differently, or broaden the budget/brand.</p>
            </div>
          ) : (
            groups.map((g, gi) => <ResultGroup key={gi} group={g} showTitle={groups.length > 1} sort={sort} />)
          )}
        </>
      )}
    </article>
  );
}

export default function AiSearch() {
  // Only the gender choice lives in the URL now (so reload keeps it); a
  // ?q= in the URL (example chip, shared link) is asked once as a new turn
  // and then dropped from the URL, since the thread holds the history.
  const [searchParams, setSearchParams] = useSearchParams();
  const urlQuery = searchParams.get("q") || "";
  const genderParam = searchParams.get("gender");
  const genderFilter = genderParam === GENDER_ANY ? null : genderParam || DEFAULT_GENDER;
  // Boys/Girls are real, separately-selectable genders (never merged into a
  // combined "Kids" value — the search backend has no such concept).
  // "Kids mode" is derived purely from which gender is active.
  const isKidsMode = genderFilter === "Boys" || genderFilter === "Girls";
  const examples = EXAMPLES_BY_GENDER[genderFilter] || EXAMPLES_BY_GENDER[DEFAULT_GENDER];

  const [turns, setTurns] = useState(() =>
    readThread().map((t) => {
      const cached = readCache(t.query, t.gender);
      return { ...t, result: cached, status: cached ? "done" : "error" };
    })
  );
  const [draft, setDraft] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const filtersRef = useRef(null);
  const filtersToggleRef = useRef(null);
  const inputRef = useRef(null);
  const turnRefs = useRef({});
  const scrollToId = useRef(null);
  const busy = turns.some((t) => t.status === "loading");

  useEffect(() => writeThread(turns), [turns]);

  function run(id, query, gender) {
    const cached = readCache(query, gender);
    if (cached) {
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, result: cached, status: "done" } : t)));
      return;
    }
    searchProducts(query, gender)
      .then((data) => {
        writeCache(query, gender, data);
        setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, result: data, status: "done" } : t)));
      })
      .catch(() => setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, status: "error" } : t))))
      // Ready for the next question as soon as this one is answered.
      .finally(() => inputRef.current?.focus());
  }

  function ask(text, gender = genderFilter) {
    const query = text.trim();
    if (!query) return;
    const id = Date.now();
    scrollToId.current = id;
    setTurns((ts) => [...ts, { id, query, gender, status: "loading", result: null }]);
    setDraft("");
    setFiltersOpen(false);
    run(id, query, gender);
  }

  function retry(turn) {
    try {
      sessionStorage.removeItem(cacheKey(turn.query, turn.gender));
    } catch {
      /* nothing cached to clear */
    }
    setTurns((ts) => ts.map((t) => (t.id === turn.id ? { ...t, status: "loading" } : t)));
    run(turn.id, turn.query, turn.gender);
  }

  // Opening this page fresh (the header's "Ask", the home composer, any
  // link) starts a new chat: the landing hero, or a new thread with the
  // linked ?q as its first question. Back/forward and reload are POP
  // navigations and keep the thread, so returning from a product lands
  // where you were. REPLACE is ignored too: the gender toggle and the ?q
  // clean-up below use it.
  // The header's Ask link also sends state.newChat, because a link to the
  // page you're already on is a REPLACE; the flag is cleared straight away
  // so going back to this entry later doesn't wipe the thread again.
  const location = useLocation();
  const navigationType = useNavigationType();
  const navigate = useNavigate();
  useEffect(() => {
    const askedFresh = location.state?.newChat;
    if (navigationType === "PUSH" || askedFresh) newChat();
    if (askedFresh) navigate(location.pathname + location.search, { replace: true, state: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  // A query arriving through the URL becomes a turn once, then leaves the
  // URL. The ref stops StrictMode's double effect run asking it twice.
  const handledUrlQuery = useRef(null);
  useEffect(() => {
    if (!urlQuery || handledUrlQuery.current === urlQuery) return;
    handledUrlQuery.current = urlQuery;
    ask(urlQuery);
    const params = {};
    if (genderParam) params.gender = genderParam;
    setSearchParams(params, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery]);

  // New question: bring it to the top of the screen, like a chat.
  useEffect(() => {
    const id = scrollToId.current;
    if (id && turnRefs.current[id]) {
      turnRefs.current[id].scrollIntoView({ behavior: "smooth", block: "start" });
      scrollToId.current = null;
    }
  }, [turns]);

  // Coming back from a product page lands where you were in the thread.
  useEffect(() => {
    let saved = 0;
    try {
      saved = Number(sessionStorage.getItem(SCROLL_KEY) || 0);
    } catch {
      /* no saved position */
    }
    if (saved && turns.length) requestAnimationFrame(() => window.scrollTo(0, saved));
    function onScroll() {
      try {
        sessionStorage.setItem(SCROLL_KEY, String(window.scrollY));
      } catch {
        /* see writeCache */
      }
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // "/" jumps to the composer from anywhere on the page.
  useEffect(() => {
    function onKey(e) {
      if (e.key !== "/" || e.target.closest?.("input, textarea, select")) return;
      e.preventDefault();
      inputRef.current?.focus();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Closes the sticky filter panel on an outside click.
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

  function onSubmit(e) {
    e.preventDefault();
    if (!busy) ask(draft);
  }

  // Changes who the NEXT question is for; earlier turns keep their own.
  function setGender(g) {
    const params = {};
    if (g !== DEFAULT_GENDER) params.gender = g || GENDER_ANY;
    setSearchParams(params, { replace: true });
  }

  function toggleGender(g) {
    if (isKidsMode) {
      setGender(g);
      return;
    }
    setGender(genderFilter === g ? null : g);
  }

  function toggleKidsMode() {
    setGender(isKidsMode ? DEFAULT_GENDER : "Boys");
  }

  // Ends the thread and returns to the hero landing state. Keeps the
  // gender selection (a shopping preference, not part of the conversation).
  function newChat() {
    setTurns([]);
    setFiltersOpen(false);
    setDraft("");
    try {
      sessionStorage.removeItem(SCROLL_KEY);
    } catch {
      /* nothing saved */
    }
    window.scrollTo(0, 0);
  }

  function renderModeRow() {
    return (
      <div className="ai-search__mode-row">
        <div
          className={`ai-search__gender-toggle${isKidsMode ? " ai-search__gender-toggle--kids" : ""}`}
          role="group"
          aria-label="Shop for"
        >
          {(isKidsMode ? ["Boys", "Girls"] : ["Men", "Women"]).map((g) => (
            <button
              key={g}
              type="button"
              className={`ai-search__gender-btn${genderFilter === g ? " ai-search__gender-btn--active" : ""}`}
              onClick={() => toggleGender(g)}
            >
              {g}
            </button>
          ))}
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
      {turns.length === 0 && (
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
              ref={inputRef}
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
              <button type="submit" className="ai-search__submit" disabled={!draft.trim()} aria-label="Search">
                <ArrowUpIcon size={17} />
              </button>
            </div>
          </form>

          <div className="ai-search__examples">
            {examples.map(({ icon: Icon, text }) => (
              <button type="button" key={text} className="ai-search__example-chip" onClick={() => ask(text)}>
                <Icon size={15} />
                {text}
              </button>
            ))}
          </div>
        </div>
      )}

      {turns.length > 0 && (
        <div className="ai-search__results ai-search__results--chat">
          {turns.map((t) => (
            <Turn key={t.id} turn={t} onRetry={() => retry(t)} turnRef={(el) => (turnRefs.current[t.id] = el)} />
          ))}
        </div>
      )}

      {/* Once a thread exists the composer stays docked at the bottom, so
          the next question is always one click (or "/") away. The
          gender/kids toggle sits behind the sliders icon. */}
      {turns.length > 0 && (
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
              title={`Shopping for: ${genderFilter || "anyone"}`}
            >
              <SlidersIcon size={16} />
            </button>
            <input
              ref={inputRef}
              className="ai-search__composer-input ai-search__composer-input--sticky"
              placeholder={busy ? "Searching…" : `Ask a follow-up or something new${genderFilter ? ` (${genderFilter})` : ""}…  Press / to focus`}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <button
              type="submit"
              className="ai-search__submit ai-search__submit--sticky"
              disabled={busy || !draft.trim()}
              aria-label="Search"
            >
              <ArrowUpIcon size={16} />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
