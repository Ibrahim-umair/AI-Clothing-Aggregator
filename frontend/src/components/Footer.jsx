import { Link } from "react-router-dom";
import { ANALYTICS_CONFIGURED, openConsentSettings } from "../lib/consent.js";
import { SITE_NAME } from "../lib/site.js";

export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="container site-footer__inner">
        <p className="site-footer__note">
          {SITE_NAME} links to each brand&rsquo;s own store. Prices and stock are checked regularly but can change;
          the brand&rsquo;s site is always the final word.
        </p>
        <nav className="site-footer__links" aria-label="Footer">
          <Link to="/">Ask</Link>
          <Link to="/shop">Browse</Link>
          <Link to="/privacy">Privacy</Link>
          <Link to="/terms">Terms</Link>
          {ANALYTICS_CONFIGURED && (
            <button type="button" className="site-footer__link-button" onClick={openConsentSettings}>
              Cookie settings
            </button>
          )}
        </nav>
        <p className="site-footer__copy">
          &copy; {new Date().getFullYear()} {SITE_NAME}
        </p>
      </div>
    </footer>
  );
}
