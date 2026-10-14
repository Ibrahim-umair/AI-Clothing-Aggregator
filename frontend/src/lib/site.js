// Site-wide facts the legal pages, footer and meta tags all quote. One
// place so the privacy policy can't drift from the terms.

export const SITE_NAME = "Libas AI";

// Canonical origin for <link rel="canonical">, og:url and the sitemap.
// Change here (and in scripts/generate-sitemap.mjs's default, robots.txt
// and index.html's static tags) when a custom domain is added.
export const SITE_URL = "https://ai-clothing-aggregator.ibrahimumair900.workers.dev";

export const DEFAULT_TITLE = "Libas AI — Ask once, every brand answers";
export const DEFAULT_DESCRIPTION =
  "Describe what you want to wear and Libas AI searches the real stock of Pakistan's clothing brands for it.";
export const DEFAULT_OG_IMAGE = "/og-image.png";

// TODO before launch: a real inbox people can write to about privacy or
// takedown requests. Both legal pages render it.
export const CONTACT_EMAIL = "hello@example.com";

// Bump whenever /privacy or /terms changes materially.
export const LEGAL_LAST_UPDATED = "14 October 2026";
