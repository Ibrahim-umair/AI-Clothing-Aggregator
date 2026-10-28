import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation } from "react-router-dom";
import { useTheme } from "../hooks/useTheme.js";
import { useWishlist } from "../hooks/useWishlist.js";
import { SunIcon, MoonIcon, HeartIcon, LogoMark, MenuIcon, CloseIcon } from "./icons.jsx";

// Libas is an AI shopping assistant with a catalog behind it, so the header
// no longer carries its own keyword search box or the category mega-menu:
// asking happens on the home page (and /ai-search), and the full category
// tree lives on /shop's own filters. Keeping one place to search avoids
// three competing search boxes on one screen.
const NAV_LINKS = [
  // `newChat` makes Ask open a fresh chat even when already on /ai-search
  // (a link to the current page is a replace, not a new visit).
  { to: "/ai-search", label: "Ask", end: true, state: { newChat: true } },
  { to: "/shop", label: "Browse" },
  { to: "/#occasions", label: "Occasions", hash: true },
  { to: "/shop?onSale=true", label: "On sale" },
];

export default function Header() {
  const { theme, toggle } = useTheme();
  const { ids: wishlistIds } = useWishlist();
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  // Close the drawer on any navigation.
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname, location.search, location.hash]);

  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === "Escape") setMobileOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
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

  const isActive = (link) => {
    if (link.hash) return false;
    if (link.to === "/shop?onSale=true") return location.pathname === "/shop" && location.search.includes("onSale=true");
    if (link.to === "/shop") return location.pathname === "/shop" && !location.search.includes("onSale=true");
    if (link.to === "/ai-search") return location.pathname === "/" || location.pathname === "/ai-search";
    return location.pathname === link.to;
  };

  return (
    <header className="site-header">
      <div className="site-header__inner">
        <Link to="/" className="brand" aria-label="Libas AI home">
          <LogoMark className="brand__logo" size={28} />
          <span className="brand__name">
            Libas <span className="brand__ai">AI</span>
          </span>
        </Link>

        <nav className="top-nav" aria-label="Primary">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.label}
              to={link.to}
              state={link.state}
              className="top-nav__link"
              aria-current={isActive(link) ? "page" : undefined}
              data-active={isActive(link)}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="header-actions">
          <button
            type="button"
            className="header-btn header-btn--icon"
            onClick={toggle}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            {theme === "dark" ? <SunIcon size={17} /> : <MoonIcon size={17} />}
          </button>
          <Link to="/favourites" className="header-btn" aria-label={`Saved items (${wishlistIds.size})`}>
            <HeartIcon size={16} />
            <span className="header-btn__label">Saved</span>
            {wishlistIds.size > 0 && <span className="header-btn__count">{wishlistIds.size}</span>}
          </Link>
          <button
            type="button"
            className="header-btn header-btn--icon mobile-menu-btn"
            aria-label="Open menu"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen(true)}
          >
            <MenuIcon size={18} />
          </button>
        </div>
      </div>

      <MobileNav open={mobileOpen} onClose={() => setMobileOpen(false)} isActive={isActive} />
    </header>
  );
}

// Slide-in drawer below the .top-nav breakpoint. Portaled to document.body
// so position:fixed resolves against the viewport, not the header box.
function MobileNav({ open, onClose, isActive }) {
  return createPortal(
    <>
      <div className={`mobile-nav-backdrop${open ? " mobile-nav-backdrop--open" : ""}`} onClick={onClose} />
      <div className={`mobile-nav${open ? " mobile-nav--open" : ""}`} role="dialog" aria-modal="true" aria-label="Menu">
        <div className="mobile-nav__head">
          <Link to="/" className="brand" onClick={onClose}>
            <LogoMark className="brand__logo" size={24} />
            <span className="brand__name">
              Libas <span className="brand__ai">AI</span>
            </span>
          </Link>
          <button type="button" className="header-btn header-btn--icon" onClick={onClose} aria-label="Close menu">
            <CloseIcon size={17} />
          </button>
        </div>
        <nav className="mobile-nav__list" aria-label="Primary">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.label}
              to={link.to}
              state={link.state}
              className="mobile-nav__flat-link"
              data-active={isActive(link)}
              onClick={onClose}
            >
              {link.label}
            </Link>
          ))}
          <Link to="/favourites" className="mobile-nav__flat-link" onClick={onClose}>
            Saved
          </Link>
        </nav>
      </div>
    </>,
    document.body
  );
}
