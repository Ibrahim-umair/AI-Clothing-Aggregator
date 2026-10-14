import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { MAX_QUERY_LENGTH, cleanQuery, fetchBrands, fetchProducts } from "../lib/api.js";
import { SparklesIcon, ArrowRightIcon } from "../components/icons.jsx";
import ProductCard from "../components/ProductCard.jsx";
import ProductCardSkeleton from "../components/ProductCardSkeleton.jsx";

// Home IS the AI search entry point: Libas is a shopping assistant with a
// catalog behind it. The composer here hands off to /ai-search (which owns
// results, caching and refinement) via the URL, exactly as a typed search
// there would, so nothing about the search pipeline changes.

const GENDERS = ["Men", "Women", "Boys", "Girls"];

const TRY_ASKING = [
  "A white kurta for Jummah, under Rs 5,000",
  "Chunky sneakers that go with jeans",
  "Office shirts I can rotate through the week",
];

// Each occasion opens as a ready-made question the shopper can then refine.
// The tile image is a real catalog product from the matching category
// (page picks a different item where two tiles share a category).
const OCCASIONS = [
  { name: "Eid", ask: "A kurta for Eid day", gender: "Men", category: "Kurta", page: 1 },
  { name: "Shaadi season", ask: "Something smart for a mehndi, not too shiny", gender: "Men", category: "Shirt", page: 2 },
  { name: "Office week", ask: "Office shirts I can rotate through the week", gender: "Men", category: "Shirt", page: 1 },
  { name: "Summer heat", ask: "Breathable tees in light colours", gender: "Men", category: "T-Shirt", page: 1 },
  { name: "Weekend", ask: "An easy polo and sneakers for the weekend", gender: "Men", category: "Polo", page: 1 },
];

const SALE_COUNT = 5;

function buildQuery(text, budget) {
  const trimmed = text.trim();
  const digits = String(budget || "").replace(/[^\d]/g, "");
  // The search model already extracts price caps from plain language
  // (server/SEARCH.md: filters.maxPrice), so the budget field is appended as
  // words rather than needing a new API parameter.
  if (digits && !/\brs\.?\s*\d|under\s+\d|budget/i.test(trimmed)) {
    return `${trimmed}, under Rs ${Number(digits).toLocaleString("en-PK")}`;
  }
  return trimmed;
}

export default function Home() {
  const navigate = useNavigate();
  const location = useLocation();
  const [text, setText] = useState("");
  const [budget, setBudget] = useState("");
  const [gender, setGender] = useState("Men");
  const [brands, setBrands] = useState([]);
  const [occasionImages, setOccasionImages] = useState({});
  const [sale, setSale] = useState({ loading: true, error: false, products: [] });
  const [retryToken, setRetryToken] = useState(0);

  // "/#occasions" from the header: react-router doesn't scroll to hashes.
  useEffect(() => {
    if (!location.hash) return;
    const el = document.getElementById(location.hash.slice(1));
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [location.hash]);

  useEffect(() => {
    let cancelled = false;
    // Soft degrade: an empty brand wall is acceptable, it's secondary.
    fetchBrands()
      .then((data) => !cancelled && setBrands(data))
      .catch(() => !cancelled && setBrands([]));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    OCCASIONS.forEach((o) => {
      fetchProducts({ gender: o.gender, category: o.category }, { page: o.page, pageSize: 1, sort: "featured" })
        .then((data) => {
          const img = data.products?.[0]?.image_url;
          if (!cancelled && img) setOccasionImages((prev) => ({ ...prev, [o.name]: img }));
        })
        .catch(() => {});
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setSale((s) => ({ ...s, loading: true, error: false }));
    fetchProducts({}, { page: 1, pageSize: SALE_COUNT, sort: "featured", onSale: true })
      .then((data) => !cancelled && setSale({ loading: false, error: false, products: data.products || [] }))
      .catch(() => !cancelled && setSale({ loading: false, error: true, products: [] }));
    return () => {
      cancelled = true;
    };
  }, [retryToken]);

  function ask(question, g = gender) {
    const q = cleanQuery(question);
    if (!q) return;
    navigate(`/ai-search?q=${encodeURIComponent(q)}&gender=${encodeURIComponent(g)}`);
  }

  function onSubmit(e) {
    e.preventDefault();
    ask(buildQuery(text, budget));
  }

  function onKeyDown(e) {
    // Enter sends, Shift+Enter adds a line — same as any chat box.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      ask(buildQuery(text, budget));
    }
  }

  const half = Math.ceil(brands.length / 2);

  return (
    <>
      <section className="home-hero">
        <div className="home-hero__main">
          <p className="home-kicker">Your shopping assistant for Pakistani brands</p>
          <h1 className="home-hero__headline">
            Ask once.
            <br />
            <span className="soft">Every brand</span> <em>answers.</em>
          </h1>
          <p className="home-hero__sub">
            Tell Libas the occasion, the look and what you want to spend. It searches every store&rsquo;s real
            stock and lays out what fits.
          </p>

          <form className="composer" onSubmit={onSubmit}>
            <div className="composer__input-row">
              <SparklesIcon size={20} className="composer__spark" />
              <label htmlFor="home-ask" className="visually-hidden">
                What are you shopping for?
              </label>
              <textarea
                id="home-ask"
                rows={2}
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={onKeyDown}
                maxLength={MAX_QUERY_LENGTH}
                placeholder="Something smart for a mehndi, nothing too shiny"
              />
            </div>
            <div className="composer__bar">
              <label className="composer__field">
                <span>Budget</span>
                <span className="composer__pill">
                  Rs
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={9}
                    value={budget}
                    onChange={(e) => setBudget(e.target.value.replace(/[^\d,]/g, ""))}
                    placeholder="any"
                    aria-label="Budget in rupees"
                  />
                </span>
              </label>
              <label className="composer__field">
                <span>For</span>
                <select className="composer__pill" value={gender} onChange={(e) => setGender(e.target.value)}>
                  {GENDERS.map((g) => (
                    <option key={g}>{g}</option>
                  ))}
                </select>
              </label>
              <button type="submit" className="composer__submit" disabled={!text.trim()}>
                Search <ArrowRightIcon size={16} />
              </button>
            </div>
          </form>

          <div className="try-list">
            <p className="home-kicker home-kicker--muted">Or try</p>
            {TRY_ASKING.map((q) => (
              <button key={q} type="button" className="try-list__item" onClick={() => ask(q)}>
                <span>{q}</span>
                <ArrowRightIcon size={16} />
              </button>
            ))}
          </div>
        </div>

        {/* A worked example of what the assistant does. Illustrative only:
            the full-outfit-within-a-budget answer is Phase 4 of the
            redesign and not yet a real search mode. */}
        <aside className="example-card" aria-label="Example answer">
          <div className="example-card__top">
            <span className="home-kicker home-kicker--muted">Example · Full outfit</span>
            <span className="example-card__tag">2 brands · 2 picks</span>
          </div>
          <p className="example-card__quote">&ldquo;A smart look for my cousin&rsquo;s mehndi. Rs 12,000, all in.&rdquo;</p>
          <div className="flatlay">
            <img className="flatlay__a" src="/sample-assets/outfit-shirt.jpg" alt="White linen blend shirt" />
            <img className="flatlay__b" src="/sample-assets/outfit-sneakers.jpg" alt="White chunky sneakers" />
            <span className="flatlay__label flatlay__label--a">
              <i aria-hidden="true" />
              <b>Shirt</b> <span className="mono">Rs 2,990</span>
            </span>
            <span className="flatlay__label flatlay__label--b">
              <b>Sneakers</b> <span className="mono">Rs 7,490</span>
            </span>
          </div>
          <div className="budget-line">
            <div className="budget-line__labels mono">
              <span>Budget Rs 12,000</span>
              <span>
                Left <b>Rs 1,520</b>
              </span>
            </div>
            <div className="budget-line__track">
              <div className="budget-line__fill" style={{ width: "87%" }} />
            </div>
            <div className="example-card__foot">
              <span className="accent-serif">Rs 1,520 to spare.</span>
            </div>
          </div>
        </aside>
      </section>

      {brands.length > 0 && (
        <section className="brand-wall" id="brands" aria-label="Brands we search">
          <p className="home-kicker home-kicker--muted">Searching across, refreshed daily</p>
          {[brands.slice(0, half), brands.slice(half)].map((row, i) => (
            <div className={`brand-wall__row${i === 1 ? " brand-wall__row--offset" : ""}`} key={i}>
              {row.map((b) => (
                <Link key={b.id} to={`/shop?brand=${encodeURIComponent(b.slug)}`} className="brand-wall__tag">
                  {b.name}
                </Link>
              ))}
            </div>
          ))}
        </section>
      )}

      <section className="home-section" id="occasions">
        <div className="home-section__head">
          <h2 className="home-h2">
            Shop by <em>occasion</em>
          </h2>
          <p className="home-section__note">Each one opens as a question you can tweak: budget, colours, how dressy.</p>
        </div>
        <div className="occasion-grid">
          {OCCASIONS.map((o) => (
            <button key={o.name} type="button" className="occasion" onClick={() => ask(o.ask, o.gender)}>
              <span className="occasion__media">
                {occasionImages[o.name] ? <img src={occasionImages[o.name]} alt="" loading="lazy" /> : null}
              </span>
              <span className="occasion__name">{o.name}</span>
              <span className="occasion__ask">&ldquo;{o.ask}&rdquo;</span>
            </button>
          ))}
        </div>
      </section>

      <section className="home-section home-section--ruled">
        <div className="home-section__head">
          <h2 className="home-h2">
            Every sale, <span className="soft">one search</span>
          </h2>
          <Link to="/shop?onSale=true" className="text-link">
            All markdowns today
          </Link>
        </div>
        {sale.error ? (
          <div className="empty-state">
            <h3>Couldn&rsquo;t load today&rsquo;s sales</h3>
            <p>Something went wrong reaching the server. Check your connection and try again.</p>
            <button type="button" className="btn btn--primary" onClick={() => setRetryToken((t) => t + 1)}>
              Try again
            </button>
          </div>
        ) : (
          <div className="product-grid product-grid--5">
            {sale.loading
              ? Array.from({ length: SALE_COUNT }, (_, i) => <ProductCardSkeleton key={i} />)
              : sale.products.map((p) => <ProductCard key={p.id} product={p} />)}
          </div>
        )}
      </section>

      <footer className="home-footer mono">
        Prices and stock refresh daily. Checkout happens on each brand&rsquo;s own site.
      </footer>
    </>
  );
}
