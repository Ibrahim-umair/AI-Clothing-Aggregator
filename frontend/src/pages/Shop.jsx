import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb.jsx";
import ProductCard from "../components/ProductCard.jsx";
import ProductCardSkeleton from "../components/ProductCardSkeleton.jsx";
import { fetchProducts, fetchTaxonomy } from "../lib/api.js";
import { ChevronDownIcon, SearchIcon, SlidersIcon, CloseIcon } from "../components/icons.jsx";
import { colorHex } from "../lib/colors.js";

const PAGE_SIZE = 24;
const SORT_OPTIONS = [
  { value: "newest", label: "Newest Arrivals" },
  { value: "price_asc", label: "Price: Low to High" },
  { value: "price_desc", label: "Price: High to Low" },
];

function selectionFromParams(params) {
  return {
    gender: params.get("gender") || null,
    branch: params.get("branch") || null,
    sub: params.get("sub") || null,
    category: params.get("category") || null,
    store: params.get("brand") || null,
  };
}

function paramsFromSelection(selection) {
  const params = {};
  if (selection.gender) params.gender = selection.gender;
  if (selection.branch) params.branch = selection.branch;
  if (selection.sub) params.sub = selection.sub;
  if (selection.category) params.category = selection.category;
  if (selection.store) params.brand = selection.store;
  return params;
}

function FilterGroup({ label, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="filter-group">
      <button type="button" className="filter-group__label" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {label}
        <ChevronDownIcon size={13} />
      </button>
      {open && <div className="filter-group__body">{children}</div>}
    </div>
  );
}

export default function Shop() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selection = useMemo(() => selectionFromParams(searchParams), [searchParams]);
  const page = Math.max(1, parseInt(searchParams.get("page"), 10) || 1);
  const sort = searchParams.get("sort") || "newest";
  const minPrice = searchParams.get("minPrice") || "";
  const maxPrice = searchParams.get("maxPrice") || "";
  const onSale = searchParams.get("onSale") === "true";
  const q = searchParams.get("q") || "";
  const sizes = useMemo(() => (searchParams.get("sizes") || "").split(",").filter(Boolean), [searchParams]);
  const colors = useMemo(() => (searchParams.get("colors") || "").split(",").filter(Boolean), [searchParams]);
  const showOOS = searchParams.get("includeOOS") === "true";
  // Sizing systems aren't comparable across garment types (S/M/L for a
  // shirt, a numeric waist for jeans, a piece-count for unstitched fabric,
  // shoe sizes for footwear) — a merged size list/filter only makes sense
  // once the view is narrowed to a single specific category (e.g.
  // "T-Shirt"). A broad view like "browse this brand" or "New In" mixes
  // all of those together, so Size is ignored there — not just hidden in
  // the sidebar, but actually excluded from the product query too, so a
  // stale ?sizes=M left over from a narrower view can't silently keep
  // filtering results with no visible control showing it's active.
  //
  // Memoized deliberately: this feeds the product-fetch effect's
  // dependency array below. Without useMemo, the `selection.category
  // ? sizes : []` fallback allocates a BRAND NEW empty array on every
  // render whenever no leaf category is selected (any "New In" view, a
  // bare branch/sub browse like Western/Eastern with no category drilled
  // in, or a plain search) — a new array reference looks like a changed
  // dependency to React every time, so the fetch effect re-fires, causing
  // a state update, causing a re-render, causing another new `[]`,
  // forever. Confirmed via Playwright: /shop with no category was firing
  // ~15 fetches in 4 seconds before this fix, matching exactly the three
  // places this was reported (New In, general categories, search).
  const effectiveSizes = useMemo(() => (selection.category ? sizes : []), [selection.category, sizes]);

  const [taxonomy, setTaxonomy] = useState(null);
  const [result, setResult] = useState({ total: 0, products: [] });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  const [searchDraft, setSearchDraft] = useState(q);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  useEffect(() => setSearchDraft(q), [q]);
  // Lock page scroll while the mobile filter drawer is open, same as any modal.
  useEffect(() => {
    if (!mobileFiltersOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [mobileFiltersOpen]);

  const priceBounds = taxonomy?.priceBounds || { min: 0, max: 10000 };
  const boundsMin = Math.floor(priceBounds.min ?? 0);
  const boundsMax = Math.ceil(priceBounds.max ?? 10000);
  const [priceDraft, setPriceDraft] = useState([boundsMin, boundsMax]);
  useEffect(() => {
    setPriceDraft([minPrice ? Number(minPrice) : boundsMin, maxPrice ? Number(maxPrice) : boundsMax]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [minPrice, maxPrice, boundsMin, boundsMax]);

  function updateParams(patch) {
    const next = {
      ...paramsFromSelection(selection),
      sort: sort === "newest" ? undefined : sort,
      minPrice: minPrice || undefined,
      maxPrice: maxPrice || undefined,
      sizes: sizes.length ? sizes.join(",") : undefined,
      colors: colors.length ? colors.join(",") : undefined,
      onSale: onSale ? "true" : undefined,
      q: q || undefined,
      includeOOS: showOOS ? "true" : undefined,
      ...patch,
    };
    Object.keys(next).forEach((k) => (next[k] == null || next[k] === "") && delete next[k]);
    setSearchParams(next);
  }

  function setSelection(nextSelection) {
    setSearchParams({ ...paramsFromSelection(nextSelection), ...(sort !== "newest" ? { sort } : {}) });
  }

  function setSort(nextSort) {
    updateParams({ sort: nextSort === "newest" ? undefined : nextSort, page: undefined });
  }

  function setPage(nextPage) {
    updateParams({ page: nextPage > 1 ? String(nextPage) : undefined });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function toggleSize(size) {
    const next = sizes.includes(size) ? sizes.filter((s) => s !== size) : [...sizes, size];
    updateParams({ sizes: next.length ? next.join(",") : undefined, page: undefined });
  }

  function toggleColor(color) {
    const next = colors.includes(color) ? colors.filter((c) => c !== color) : [...colors, color];
    updateParams({ colors: next.length ? next.join(",") : undefined, page: undefined });
  }

  function commitPriceDraft() {
    updateParams({
      minPrice: priceDraft[0] > boundsMin ? priceDraft[0] : undefined,
      maxPrice: priceDraft[1] < boundsMax ? priceDraft[1] : undefined,
      page: undefined,
    });
  }

  function submitSearch(e) {
    e.preventDefault();
    updateParams({ q: searchDraft.trim() || undefined, page: undefined });
  }

  function clearAll() {
    setSearchDraft("");
    setSearchParams({});
  }

  useEffect(() => {
    let cancelled = false;
    fetchTaxonomy(selection)
      .then((data) => !cancelled && setTaxonomy(data))
      .catch(() => !cancelled && setTaxonomy(null));
    return () => {
      cancelled = true;
    };
  }, [selection.gender, selection.branch, selection.sub, selection.category, selection.store]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(false);
    fetchProducts(selection, {
      page,
      pageSize: PAGE_SIZE,
      sort,
      minPrice,
      maxPrice,
      sizes: effectiveSizes,
      colors,
      q,
      onSale,
    })
      .then((data) => !cancelled && setResult(data))
      .catch(() => {
        if (cancelled) return;
        // Distinct from a genuine "0 results" search — that's a valid
        // outcome for a narrow filter combo, this is the fetch itself
        // failing (network drop, API down), which needs its own message
        // and a retry, not the "try a broader category" empty-state copy.
        setLoadError(true);
        setResult({ total: 0, products: [] });
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [selection.gender, selection.branch, selection.sub, selection.category, selection.store, page, sort, minPrice, maxPrice, effectiveSizes, colors, q, onSale, retryToken]);

  const totalPages = Math.max(1, Math.ceil(result.total / PAGE_SIZE));
  const heading = selection.category || selection.sub || selection.branch || selection.gender || "All Products";
  const brandFacets = taxonomy?.brandFacets || [];
  const sizeFacets = selection.category ? taxonomy?.sizeFacets || [] : [];
  const colorFacets = taxonomy?.colorFacets || [];

  const siblingCategories = useMemo(() => {
    const columns = taxonomy?.menus?.[selection.gender];
    if (!columns) return [];
    const column = selection.branch ? columns.find((c) => c.branch === selection.branch) : null;
    if (!column) return [];
    if (column.subs) {
      const subGroup = selection.sub ? column.subs.find((s) => s.sub === selection.sub) : column.subs[0];
      return subGroup?.categories || [];
    }
    return column.categories || [];
  }, [taxonomy, selection.gender, selection.branch, selection.sub]);

  const activeChips = [];
  if (selection.store) activeChips.push({ key: "brand", label: selection.store, clear: () => updateParams({ brand: undefined, page: undefined }) });
  if (selection.category) activeChips.push({ key: "category", label: selection.category, clear: () => updateParams({ category: undefined, page: undefined }) });
  if (onSale) activeChips.push({ key: "sale", label: "On Sale", clear: () => updateParams({ onSale: undefined, page: undefined }) });
  if (q) activeChips.push({ key: "q", label: `"${q}"`, clear: () => updateParams({ q: undefined, page: undefined }) });
  effectiveSizes.forEach((s) => activeChips.push({ key: `size-${s}`, label: s, clear: () => toggleSize(s) }));
  colors.forEach((c) => activeChips.push({ key: `color-${c}`, label: c, clear: () => toggleColor(c) }));
  if (minPrice || maxPrice) {
    activeChips.push({
      key: "price",
      label: `PKR ${minPrice || boundsMin} – ${maxPrice || boundsMax}`,
      clear: () => updateParams({ minPrice: undefined, maxPrice: undefined, page: undefined }),
    });
  }
  const hasActiveFilters = activeChips.length > 0;

  // Shared between the always-visible desktop sidebar and the mobile
  // slide-in drawer (below 900px, see .filters / .mobile-filters-btn) —
  // same controls, same state, just a different container.
  const filterBody = (
    <>
      {sizeFacets.length > 0 && (
        <FilterGroup label="Size">
          <div className="size-grid">
            {sizeFacets.map((s) => (
              <button
                type="button"
                key={s.value}
                className={`size-chip ${sizes.includes(s.value) ? "size-chip--active" : ""}`}
                onClick={() => toggleSize(s.value)}
              >
                {s.value}
              </button>
            ))}
          </div>
        </FilterGroup>
      )}

      <FilterGroup label="Availability">
        <label className="check-row">
          <input type="checkbox" checked={showOOS} onChange={() => updateParams({ includeOOS: showOOS ? undefined : "true", page: undefined })} />
          Include out-of-stock
        </label>
      </FilterGroup>

      {colorFacets.length > 0 && (
        <FilterGroup label="Colors">
          <div className="swatch-grid">
            {colorFacets.map((c) => (
              <button
                type="button"
                key={c.value}
                className="swatch-dot"
                data-active={colors.includes(c.value)}
                style={{ background: colorHex(c.value) }}
                title={c.value}
                aria-label={c.value}
                onClick={() => toggleColor(c.value)}
              />
            ))}
          </div>
        </FilterGroup>
      )}

      <FilterGroup label="Price Range">
        <div className="price-slider">
          <div className="price-slider__labels">
            <span>PKR {priceDraft[0].toLocaleString()}</span>
            <span>
              PKR {priceDraft[1].toLocaleString()}
              {priceDraft[1] >= boundsMax ? "+" : ""}
            </span>
          </div>
          <div className="price-slider__track">
            <div className="price-slider__rail" />
            <div
              className="price-slider__fill"
              style={{
                left: `${((priceDraft[0] - boundsMin) / (boundsMax - boundsMin || 1)) * 100}%`,
                right: `${100 - ((priceDraft[1] - boundsMin) / (boundsMax - boundsMin || 1)) * 100}%`,
              }}
            />
            <input
              type="range"
              min={boundsMin}
              max={boundsMax}
              value={priceDraft[0]}
              onChange={(e) => setPriceDraft([Math.min(Number(e.target.value), priceDraft[1]), priceDraft[1]])}
              onMouseUp={commitPriceDraft}
              onTouchEnd={commitPriceDraft}
              onKeyUp={commitPriceDraft}
              aria-label="Minimum price"
            />
            <input
              type="range"
              min={boundsMin}
              max={boundsMax}
              value={priceDraft[1]}
              onChange={(e) => setPriceDraft([priceDraft[0], Math.max(Number(e.target.value), priceDraft[0])])}
              onMouseUp={commitPriceDraft}
              onTouchEnd={commitPriceDraft}
              onKeyUp={commitPriceDraft}
              aria-label="Maximum price"
            />
          </div>
        </div>
      </FilterGroup>
    </>
  );

  return (
    <>
      <Breadcrumb selection={selection} onChange={setSelection} />

      <div className="shop-heading">
        <div className="shop-heading__copy">
          <h1>{heading}</h1>
        </div>
      </div>

      {siblingCategories.length > 0 && (
        <div className="subcat-row" role="tablist" aria-label="Refine category">
          <button
            type="button"
            className={`subcat-chip ${!selection.category ? "subcat-chip--active" : ""}`}
            onClick={() => updateParams({ category: undefined, page: undefined })}
          >
            All
          </button>
          {siblingCategories.map((c) => (
            <button
              key={c.value}
              type="button"
              className={`subcat-chip ${selection.category === c.value ? "subcat-chip--active" : ""}`}
              onClick={() => updateParams({ category: c.value, page: undefined })}
            >
              {c.value}
            </button>
          ))}
        </div>
      )}

      <div className="shop-toolbar">
        <form className="shop-search" onSubmit={submitSearch}>
          <SearchIcon size={15} />
          <input
            placeholder={`Search within ${heading}`}
            value={searchDraft}
            onChange={(e) => setSearchDraft(e.target.value)}
          />
        </form>
        <label className="select-control">
          <span className="select-control__label">Brand</span>
          <select value={selection.store || ""} onChange={(e) => updateParams({ brand: e.target.value || undefined, page: undefined })}>
            <option value="">All brands</option>
            {brandFacets.map((b) => (
              <option key={b.value} value={b.value}>
                {b.value} ({b.count})
              </option>
            ))}
          </select>
        </label>
        <label className="select-control">
          <span className="select-control__label">Sort by</span>
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <span className="shop-toolbar__count">{result.total.toLocaleString()} Products</span>
      </div>

      {hasActiveFilters && (
        <div className="active-chips">
          {activeChips.map((c) => (
            <span className="active-chip" key={c.key}>
              {c.label}
              <button type="button" onClick={c.clear} aria-label={`Remove ${c.label}`}>
                ×
              </button>
            </span>
          ))}
          <button type="button" className="active-chips__clear" onClick={clearAll}>
            Clear All
          </button>
        </div>
      )}

      <div className="shop-layout">
        <aside className="filters">
          <div className="filters__head">
            <b>Filters</b>
            <button type="button" onClick={clearAll}>
              Clear All
            </button>
          </div>
          {filterBody}
        </aside>

        <div>
          <div className="results-count">
            <span>{result.total.toLocaleString()} products</span>
            <button type="button" className="mobile-filters-btn" onClick={() => setMobileFiltersOpen(true)}>
              <SlidersIcon size={15} />
              Filters
              {hasActiveFilters && <span className="mobile-filters-btn__badge">{activeChips.length}</span>}
            </button>
          </div>
          {loading ? (
            <div className="product-grid product-grid--4">
              {Array.from({ length: PAGE_SIZE }, (_, i) => (
                <ProductCardSkeleton key={i} />
              ))}
            </div>
          ) : loadError ? (
            <div className="empty-state">
              <h3>Couldn't load these results</h3>
              <p>Something went wrong reaching the server. Check your connection and try again.</p>
              <button type="button" className="btn btn--primary" onClick={() => setRetryToken((t) => t + 1)}>
                Try again
              </button>
            </div>
          ) : (
            <div className="product-grid product-grid--4">
              {result.products.length === 0 ? (
                <div className="empty-state" style={{ gridColumn: "1 / -1" }}>
                  <h3>No products in this corner of the store yet</h3>
                  <p>Try a broader category or a different brand.</p>
                </div>
              ) : (
                result.products.map((p) => <ProductCard key={p.id} product={p} />)
              )}
            </div>
          )}

          {!loading && totalPages > 1 && (
            <div className="pagination">
              <button type="button" className="btn btn--ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                Previous
              </button>
              <span className="pagination__status">
                Page {page} of {totalPages.toLocaleString()}
              </span>
              <button type="button" className="btn btn--ghost" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
                Next
              </button>
            </div>
          )}
        </div>
      </div>

      <div
        className={`mobile-filters-backdrop${mobileFiltersOpen ? " mobile-filters-backdrop--open" : ""}`}
        onClick={() => setMobileFiltersOpen(false)}
      />
      <div
        className={`mobile-filters${mobileFiltersOpen ? " mobile-filters--open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Filters"
      >
        <div className="mobile-filters__head">
          <b>Filters</b>
          <button type="button" className="icon-btn" onClick={() => setMobileFiltersOpen(false)} aria-label="Close filters">
            <CloseIcon size={17} />
          </button>
        </div>
        <div className="mobile-filters__body">{filterBody}</div>
        <div className="mobile-filters__foot">
          <button type="button" className="btn btn--ghost" onClick={clearAll}>
            Clear All
          </button>
          <button type="button" className="btn btn--primary" onClick={() => setMobileFiltersOpen(false)}>
            Show {result.total.toLocaleString()} results
          </button>
        </div>
      </div>
    </>
  );
}
