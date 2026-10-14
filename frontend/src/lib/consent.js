// Cookie / tracking consent. The site itself sets no cookies — theme,
// favourites and the AI-search cache are localStorage/sessionStorage that
// never leave the browser — so the only thing that needs consent is
// optional analytics. Nothing non-essential may load until
// getConsent()?.analytics === true; lib/analytics.js is the one consumer.
//
// Stored in localStorage (not a cookie) for the same reason as the theme:
// it's only ever read by our own JS. Versioned so a future change in what
// we ask for (e.g. adding a second purpose) can re-prompt everyone.

const STORAGE_KEY = "libas-consent";
const CONSENT_VERSION = 1;
const CHANGE_EVENT = "libas-consent-change";
const OPEN_EVENT = "libas-consent-open";

// The banner only appears when there's actually something to consent to.
// Asking about cookies on a site that sets none would just be noise.
export const ANALYTICS_CONFIGURED = Boolean(import.meta.env.VITE_GA_MEASUREMENT_ID);

export function getConsent() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed?.v === CONSENT_VERSION ? parsed : null;
  } catch {
    return null;
  }
}

export function setConsent({ analytics }) {
  const value = { v: CONSENT_VERSION, analytics: Boolean(analytics), at: new Date().toISOString() };
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    /* storage blocked — the choice still applies for this page view */
  }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: value }));
  return value;
}

export function onConsentChange(callback) {
  const handler = (e) => callback(e.detail);
  window.addEventListener(CHANGE_EVENT, handler);
  return () => window.removeEventListener(CHANGE_EVENT, handler);
}

// The footer's "Cookie settings" link reopens the banner so a choice can
// be changed or withdrawn as easily as it was given.
export function openConsentSettings() {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

export function onConsentSettingsOpen(callback) {
  window.addEventListener(OPEN_EVENT, callback);
  return () => window.removeEventListener(OPEN_EVENT, callback);
}
