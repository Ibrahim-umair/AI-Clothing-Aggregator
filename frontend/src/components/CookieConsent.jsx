import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ANALYTICS_CONFIGURED, getConsent, onConsentSettingsOpen, setConsent } from "../lib/consent.js";

// Bottom-of-screen consent bar. Accept and Decline are deliberately the
// same size and weight: declining has to be as easy as accepting, and
// nothing optional loads while the bar is still open (no choice = no).
export default function CookieConsent() {
  const [open, setOpen] = useState(() => ANALYTICS_CONFIGURED && getConsent() === null);

  useEffect(() => onConsentSettingsOpen(() => setOpen(true)), []);

  if (!ANALYTICS_CONFIGURED || !open) return null;

  function choose(analytics) {
    setConsent({ analytics });
    setOpen(false);
  }

  return (
    <div className="cookie-consent" role="region" aria-label="Cookie consent">
      <p className="cookie-consent__text">
        We&rsquo;d like to use analytics cookies to see which searches and pages help people find clothes, so we
        can improve them. They stay off unless you accept. <Link to="/privacy#cookies">Privacy policy</Link>
      </p>
      <div className="cookie-consent__actions">
        <button type="button" className="btn btn--ghost" onClick={() => choose(false)}>
          Decline
        </button>
        <button type="button" className="btn btn--primary" onClick={() => choose(true)}>
          Accept
        </button>
      </div>
    </div>
  );
}
