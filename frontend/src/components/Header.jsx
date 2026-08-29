import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate } from "react-router-dom";
import { useTheme } from "../hooks/useTheme.js";
import { useWishlist } from "../hooks/useWishlist.js";
import { fetchTaxonomy } from "../lib/api.js";
import {
  SunIcon,
  MoonIcon,
  HeartIcon,
  LogoMark,
  ChevronDownIcon,
  SearchIcon,
  MenuIcon,
  CloseIcon,
  SparklesIcon,
} from "./icons.jsx";

const NAV_GENDERS = ["Women", "Men"];
const KIDS_GENDERS = ["Boys", "Girls"];

// The category mega-menu lives on the global navbar (hover WOMEN/MEN to
// reveal it). Menu columns come from /api/taxonomy — independent of any
// current selection, so one fetch on mount covers both genders and the
// full brand list for the whole session. Below 900px the mega-menu nav is
// hidden (see .top-nav in index.css) in favor of MobileNav, a slide-in
// drawer — the hamburger button is the only way to reach Women/Men/Kids
// navigation on a phone-width viewport, so it isn't optional chrome.
export default function Header() {
  const { theme, toggle } = useTheme();
  const { ids: wishlistIds } = useWishlist();
  const navigate = useNavigate();
  const [menus, setMenus] = useState({});
  const [openPanel, setOpenPanel] = useState(null); // "Women" | "Men" | "kids" | null
  const [kidsGender, setKidsGender] = useState("Boys");
  const [query, setQuery] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const headerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    fetchTaxonomy({})
      .then((data) => !cancelled && setMenus(data.menus || {}))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function onDocPointerDown(e) {
      if (headerRef.current && !headerRef.current.contains(e.target)) setOpenPanel(null);
    }
    function onKeyDown(e) {
      if (e.key === "Escape") {
        setOpenPanel(null);
        setMobileOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onDocPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  // Lock page scroll while the mobile drawer is open, same as any modal.
  useEffect(() => {
    if (!mobileOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [mobileOpen]);

  function go(params) {
    const qs = new URLSearchParams(params).toString();
    navigate(`/shop?${qs}`);
    setOpenPanel(null);
    setMobileOpen(false);
  }

  function submitSearch(e) {
    e.preventDefault();
    if (!query.trim()) return;
    navigate(`/shop?q=${encodeURIComponent(query.trim())}`);
    setMobileOpen(false);
  }

  const activeGender = openPanel === "kids" ? kidsGender : openPanel;
  const columns = NAV_GENDERS.includes(openPanel) || openPanel === "kids" ? menus[activeGender] || [] : null;

  return (
    <header className="site-header" ref={headerRef} onMouseLeave={() => setOpenPanel(null)}>
      <div className="site-header__inner">
        <button
          type="button"
          className="mobile-menu-btn"
          aria-label="Open menu"
          aria-expanded={mobileOpen}
          onClick={() => setMobileOpen(true)}
        >
          <MenuIcon size={20} />
        </button>

        <Link to="/" className="brand">
          <LogoMark className="brand__logo" size={26} />
          <span className="brand__wordmark">
            <span className="brand__mark">Libas</span>
            <span className="brand__caption">Pakistan</span>
          </span>
        </Link>

        <nav className="top-nav" aria-label="Primary">
          {NAV_GENDERS.map((g) => (
            <div key={g} className="top-nav__item" onMouseEnter={() => setOpenPanel(g)}>
              <button
                type="button"
                className="top-nav__link top-nav__link--trigger"
                aria-expanded={openPanel === g}
                aria-haspopup="true"
                onClick={() => (openPanel === g ? go({ gender: g }) : setOpenPanel(g))}
              >
                {g}
                <ChevronDownIcon size={11} className="top-nav__chevron" data-open={openPanel === g} />
              </button>
            </div>
          ))}
          <div className="top-nav__item" onMouseEnter={() => setOpenPanel("kids")}>
            <button
              type="button"
              className="top-nav__link top-nav__link--trigger"
              aria-expanded={openPanel === "kids"}
              aria-haspopup="true"
              onClick={() => (openPanel === "kids" ? go({ gender: kidsGender }) : setOpenPanel("kids"))}
            >
              Kids
              <ChevronDownIcon size={11} className="top-nav__chevron" data-open={openPanel === "kids"} />
            </button>
          </div>
          <button type="button" className="top-nav__link" onClick={() => go({ sort: "newest" })}>
            New In
          </button>
          <Link to="/ai-search" className="top-nav__link top-nav__link--ai">
            <SparklesIcon size={13} />
            AI Search
          </Link>
        </nav>

        <form className="header-search" onSubmit={submitSearch}>
          <SearchIcon size={15} />
          <input
            type="search"
            placeholder="Search products, brands & more"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </form>

        <div className="header-actions">
          <button
            className="theme-toggle"
            onClick={toggle}
            aria-label="Toggle color theme"
            title="Toggle light / dark mode"
          >
            {theme === "dark" ? <SunIcon size={16} /> : <MoonIcon size={16} />}
          </button>
          <Link to="/favourites" className="icon-btn" aria-label="Favourites">
            <HeartIcon size={17} />
            {wishlistIds.size > 0 && <span className="icon-btn__badge">{wishlistIds.size}</span>}
          </Link>
          <Link to="/signup" className="icon-btn icon-btn--dark" aria-label="Account">
            <LogoMark size={16} />
          </Link>
        </div>
      </div>

      {columns && columns.length > 0 && (
        <div className="meganav__panel" role="menu">
          <div className="meganav__panel-inner">
            {openPanel === "kids" && (
              <div className="meganav__tabs">
                {KIDS_GENDERS.map((g) => (
                  <button
                    key={g}
                    type="button"
                    className="meganav__tab"
                    data-active={kidsGender === g}
                    onClick={() => setKidsGender(g)}
                  >
                    {g}
                  </button>
                ))}
              </div>
            )}
            <button type="button" className="meganav__view-all" onClick={() => go({ gender: activeGender })}>
              View all {activeGender.toLowerCase()}
            </button>
            <div className="meganav__columns">
              {columns.map((col) => (
                <div className="meganav__column" key={col.branch}>
                  <span className="meganav__column-title">{col.branch}</span>

                  {col.subs
                    ? col.subs.map((s) => (
                        <div className="meganav__group" key={s.sub}>
                          <button
                            type="button"
                            className="meganav__sub-title"
                            onClick={() => go({ gender: activeGender, branch: col.branch, sub: s.sub })}
                          >
                            {s.sub}
                          </button>
                          <ul className="meganav__links">
                            {s.categories.map((c) => (
                              <li key={c.value}>
                                <button
                                  type="button"
                                  className="meganav__link"
                                  onClick={() =>
                                    go({ gender: activeGender, branch: col.branch, sub: s.sub, category: c.value })
                                  }
                                >
                                  {c.value}
                                  <span className="meganav__link-count">{c.count}</span>
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))
                    : (
                      <ul className="meganav__links">
                        {col.categories.map((c) => (
                          <li key={c.value}>
                            <button
                              type="button"
                              className="meganav__link"
                              onClick={() => go({ gender: activeGender, branch: col.branch, category: c.value })}
                            >
                              {c.value}
                              <span className="meganav__link-count">{c.count}</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <MobileNav
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        menus={menus}
        query={query}
        setQuery={setQuery}
        onSubmitSearch={submitSearch}
        onNavigate={go}
        kidsGender={kidsGender}
        setKidsGender={setKidsGender}
      />
    </header>
  );
}

// Slide-in drawer used below the .top-nav breakpoint (900px) — the desktop
// mega-menu is intentionally simplified here to a two-level accordion
// (gender -> branch, tapping a branch goes straight to that listing)
// rather than reproducing the full branch/sub/category depth, since that
// much nesting doesn't work well as a touch accordion.
function MobileNav({ open, onClose, menus, query, setQuery, onSubmitSearch, onNavigate, kidsGender, setKidsGender }) {
  const [expanded, setExpanded] = useState(null); // "Women" | "Men" | "Kids" | null

  useEffect(() => {
    if (!open) setExpanded(null);
  }, [open]);

  function renderBranchLinks(gender) {
    const columns = menus[gender] || [];
    if (columns.length === 0) return <p className="mobile-nav__empty">Loading…</p>;
    return (
      <ul className="mobile-nav__branch-list">
        {columns.map((col) => (
          <li key={col.branch}>
            <button type="button" onClick={() => onNavigate({ gender, branch: col.branch })}>
              {col.branch}
            </button>
          </li>
        ))}
      </ul>
    );
  }

  // Portaled to document.body rather than rendered inline (it would
  // otherwise stay nested inside <header>): .site-header has
  // backdrop-filter, which creates a new containing block for
  // position:fixed descendants in modern browsers, so this drawer's fixed
  // positioning would resolve against the header's own short box instead
  // of the viewport — clipping the whole thing down to header height and
  // making it effectively invisible even though `open` was working fine.
  return createPortal(
    <>
      <div className={`mobile-nav-backdrop${open ? " mobile-nav-backdrop--open" : ""}`} onClick={onClose} />
      <div className={`mobile-nav${open ? " mobile-nav--open" : ""}`} role="dialog" aria-modal="true" aria-label="Menu">
        <div className="mobile-nav__head">
          <Link to="/" className="brand" onClick={onClose}>
            <LogoMark className="brand__logo" size={24} />
            <span className="brand__wordmark">
              <span className="brand__mark">Libas</span>
              <span className="brand__caption">Pakistan</span>
            </span>
          </Link>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close menu">
            <CloseIcon size={17} />
          </button>
        </div>

        <form className="mobile-nav__search" onSubmit={onSubmitSearch}>
          <SearchIcon size={15} />
          <input
            type="search"
            placeholder="Search products, brands & more"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </form>

        <nav className="mobile-nav__list" aria-label="Primary">
          {NAV_GENDERS.map((g) => (
            <div className="mobile-nav__section" key={g}>
              <button
                type="button"
                className="mobile-nav__section-head"
                aria-expanded={expanded === g}
                onClick={() => setExpanded(expanded === g ? null : g)}
              >
                {g}
                <ChevronDownIcon size={13} data-open={expanded === g} />
              </button>
              {expanded === g && <div className="mobile-nav__section-body">{renderBranchLinks(g)}</div>}
            </div>
          ))}

          <div className="mobile-nav__section">
            <button
              type="button"
              className="mobile-nav__section-head"
              aria-expanded={expanded === "Kids"}
              onClick={() => setExpanded(expanded === "Kids" ? null : "Kids")}
            >
              Kids
              <ChevronDownIcon size={13} data-open={expanded === "Kids"} />
            </button>
            {expanded === "Kids" && (
              <div className="mobile-nav__section-body">
                <div className="meganav__tabs">
                  {KIDS_GENDERS.map((g) => (
                    <button
                      key={g}
                      type="button"
                      className="meganav__tab"
                      data-active={kidsGender === g}
                      onClick={() => setKidsGender(g)}
                    >
                      {g}
                    </button>
                  ))}
                </div>
                {renderBranchLinks(kidsGender)}
              </div>
            )}
          </div>

          <button type="button" className="mobile-nav__flat-link" onClick={() => onNavigate({ sort: "newest" })}>
            New In
          </button>
          <Link to="/ai-search" className="mobile-nav__flat-link mobile-nav__flat-link--ai" onClick={onClose}>
            <SparklesIcon size={14} />
            AI Search
          </Link>
          <Link to="/favourites" className="mobile-nav__flat-link" onClick={onClose}>
            Favourites
          </Link>
        </nav>
      </div>
    </>,
    document.body
  );
}
