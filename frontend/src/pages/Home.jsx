import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchBrands, fetchProducts } from "../lib/api.js";
import {
  ArrowUpRightIcon,
  ShieldCheckIcon,
  TruckIcon,
  RefreshIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ShirtIcon,
  TShirtIcon,
  TrouserIcon,
  KurtaIcon,
  ShoeIcon,
  ShoppingBagIcon,
  SunglassesIcon,
} from "../components/icons.jsx";
import ProductCard from "../components/ProductCard.jsx";
import ProductCardSkeleton from "../components/ProductCardSkeleton.jsx";

// Real 15-brand roster (server/load_data.py BRANDS) — a representative 8 of
// them get a distinct wordmark treatment so the strip reads like genuinely
// different brand identities side by side, everything else falls back to
// the plain bold style. Wordmark styling is cosmetic only; the link target
// is always the real brand.
const WORDMARK_STYLE = {
  edenrobe: "wordmark--italic",
  cambridge: "wordmark--outline",
  royal_tag: "wordmark--spaced",
  diners: "wordmark--condensed",
};

const QUICK_CATEGORIES = [
  { gender: "Men", category: "Shirt", label: "Shirts", Icon: ShirtIcon },
  { gender: "Men", category: "T-Shirt", label: "T-Shirts", Icon: TShirtIcon },
  { gender: "Men", category: "Polo", label: "Polo Shirts", Icon: TShirtIcon },
  { gender: "Men", category: "Jeans", label: "Denim", Icon: TrouserIcon },
  { gender: "Men", category: "Kurta", label: "Kurtas", Icon: KurtaIcon },
  { gender: "Men", category: "Shoes", label: "Footwear", Icon: ShoeIcon },
  { gender: "Women", category: "Bag", label: "Bags", Icon: ShoppingBagIcon },
  { gender: "Women", category: "Sunglasses", label: "Accessories", Icon: SunglassesIcon },
];

const FEATURED_PAGE_SIZE = 6;
const FEATURED_MAX_PAGES = 5;

export default function Home() {
  const [brands, setBrands] = useState([]);
  const [featured, setFeatured] = useState({ total: 0, products: [] });
  const [featuredPage, setFeaturedPage] = useState(1);
  const [featuredLoading, setFeaturedLoading] = useState(true);
  const [featuredError, setFeaturedError] = useState(false);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Brand strip failing silently (empty strip) is an acceptable soft
    // degrade — it's a secondary decoration, not core page content, unlike
    // the featured products below.
    fetchBrands()
      .then((data) => !cancelled && setBrands(data))
      .catch(() => !cancelled && setBrands([]));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setFeaturedLoading(true);
    setFeaturedError(false);
    fetchProducts({}, { page: featuredPage, pageSize: FEATURED_PAGE_SIZE, sort: "newest" })
      .then((data) => !cancelled && setFeatured(data))
      .catch(() => {
        if (cancelled) return;
        setFeaturedError(true);
        setFeatured({ total: 0, products: [] });
      })
      .finally(() => !cancelled && setFeaturedLoading(false));
    return () => {
      cancelled = true;
    };
  }, [featuredPage, retryToken]);

  const featuredPages = Math.min(FEATURED_MAX_PAGES, Math.max(1, Math.ceil(featured.total / FEATURED_PAGE_SIZE)));

  return (
    <>
      <section className="hero">
        <div className="hero__copy">
          <span className="eyebrow">One destination. Countless brands.</span>
          <h1 className="hero__headline">Shop Pakistan&rsquo;s best fashion, all in one place.</h1>
          <p className="hero__sub">
            Browse real, in-stock pieces from 15 Pakistani apparel brands — eastern &amp; western
            wear, footwear, accessories and fragrance — organized one way, no matter whose label
            is on it.
          </p>
          <div className="hero__actions">
            <Link to="/shop?gender=Men" className="btn btn--primary">
              Shop Men
            </Link>
            <Link to="/shop?gender=Women" className="btn btn--ghost">
              Shop Women <ArrowUpRightIcon size={14} />
            </Link>
          </div>

          <div className="benefit-row">
            <div className="benefit-row__item">
              <ShieldCheckIcon size={20} />
              <span className="benefit-row__copy">
                <b>15 real brands</b>
                <small>Not a marketplace listing</small>
              </span>
            </div>
            <div className="benefit-row__item">
              <TruckIcon size={20} />
              <span className="benefit-row__copy">
                <b>Direct to store</b>
                <small>Checkout on the brand's site</small>
              </span>
            </div>
            <div className="benefit-row__item">
              <RefreshIcon size={20} />
              <span className="benefit-row__copy">
                <b>Refreshed daily</b>
                <small>Prices &amp; stock as last scraped</small>
              </span>
            </div>
          </div>
        </div>

        <div className="hero__art">
          <img src="/sample-assets/hero-img.png" alt="" />
          <div className="hero__float-card">
            <span>
              <ShoppingBagIcon size={12} /> Live catalog
            </span>
            <strong>100,000+ pieces</strong>
            <Link to="/shop">
              Explore now <ArrowUpRightIcon size={13} />
            </Link>
          </div>
        </div>
      </section>

      <section className="brand-strip">
        <div className="brand-strip__track">
          {/* Rendered twice back-to-back so the marquee loop has no visible
              seam — the track scrolls exactly one copy's width, then jumps
              back to a pixel-identical starting frame. */}
          {[0, 1].map((copy) => (
            <div className="brand-strip__scroller" key={copy} aria-hidden={copy === 1}>
              {brands.map((b) => (
                <Link
                  key={b.id}
                  to={`/shop?brand=${encodeURIComponent(b.slug)}`}
                  className={`wordmark ${WORDMARK_STYLE[b.slug] || ""}`}
                  tabIndex={copy === 1 ? -1 : undefined}
                >
                  {b.name}
                </Link>
              ))}
            </div>
          ))}
        </div>
      </section>

      <section className="quickcat-section">
        <div className="quickcat-row">
          {QUICK_CATEGORIES.map(({ gender, category, label, Icon }) => (
            <Link
              key={label}
              to={`/shop?gender=${encodeURIComponent(gender)}&category=${encodeURIComponent(category)}`}
              className="quickcat-chip"
            >
              <Icon size={18} />
              <span>{label}</span>
            </Link>
          ))}
        </div>
      </section>

      <section className="featured-section">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Curated picks</span>
            <h2>Featured For You</h2>
          </div>
          <div className="section-heading__nav">
            <Link to="/shop?sort=newest" className="section-heading__link">
              View All
            </Link>
            <div className="section-heading__arrows">
              <button
                type="button"
                className="section-heading__arrow"
                disabled={featuredPage <= 1}
                onClick={() => setFeaturedPage((p) => Math.max(1, p - 1))}
                aria-label="Previous"
              >
                <ChevronLeftIcon size={13} />
              </button>
              <button
                type="button"
                className="section-heading__arrow"
                disabled={featuredPage >= featuredPages}
                onClick={() => setFeaturedPage((p) => Math.min(featuredPages, p + 1))}
                aria-label="Next"
              >
                <ChevronRightIcon size={13} />
              </button>
            </div>
          </div>
        </div>

        {featuredError ? (
          <div className="empty-state">
            <h3>Couldn't load featured products</h3>
            <p>Something went wrong reaching the server. Check your connection and try again.</p>
            <button type="button" className="btn btn--primary" onClick={() => setRetryToken((t) => t + 1)}>
              Try again
            </button>
          </div>
        ) : (
          <div className="product-grid product-grid--6">
            {featuredLoading
              ? Array.from({ length: FEATURED_PAGE_SIZE }, (_, i) => <ProductCardSkeleton key={i} />)
              : featured.products.map((p) => <ProductCard key={p.id} product={p} />)}
          </div>
        )}

        {featuredPages > 1 && (
          <div className="dot-pagination">
            {Array.from({ length: featuredPages }, (_, i) => i + 1).map((n) => (
              <button key={n} data-active={n === featuredPage} onClick={() => setFeaturedPage(n)} aria-label={`Page ${n}`} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}
