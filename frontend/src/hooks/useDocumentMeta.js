import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { DEFAULT_DESCRIPTION, DEFAULT_OG_IMAGE, DEFAULT_TITLE, SITE_NAME, SITE_URL } from "../lib/site.js";

// Per-route <head> tags for a client-rendered SPA. index.html carries the
// same tags statically with the site defaults; this overwrites them in
// place as the route changes. Every call sets EVERY tag (falling back to
// the defaults), so a page that doesn't mention, say, an image can't
// inherit the previous product's photo.
//
// Who sees what: Google renders JavaScript, so it indexes these per-page
// values. Link-preview bots (WhatsApp, Facebook, X, Slack) don't run JS
// and always see index.html's static defaults — per-product share cards
// would need the HTML rewritten at the edge (a Cloudflare Worker), which
// this static-assets deploy doesn't have.

function setMeta(attr, key, content) {
  let el = document.head.querySelector(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

function setCanonical(href) {
  let el = document.head.querySelector('link[rel="canonical"]');
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", "canonical");
    document.head.appendChild(el);
  }
  el.setAttribute("href", href);
}

const absolute = (url) => (/^https?:\/\//.test(url) ? url : `${SITE_URL}${url}`);

/**
 * @param {object} meta
 * @param {string} [meta.title]        page-specific part; " | Libas AI" is appended
 * @param {string} [meta.description]
 * @param {string} [meta.image]        absolute or site-relative
 * @param {string} [meta.path]         canonical path; defaults to the current pathname (query string dropped)
 * @param {boolean} [meta.noindex]     keep the page out of search results
 * @param {string} [meta.type]         og:type, "website" by default
 */
export function useDocumentMeta({ title, description, image, path, noindex = false, type = "website" } = {}) {
  const { pathname } = useLocation();

  useEffect(() => {
    const fullTitle = title ? `${title} | ${SITE_NAME}` : DEFAULT_TITLE;
    const desc = (description || DEFAULT_DESCRIPTION).replace(/\s+/g, " ").trim().slice(0, 160);
    const url = absolute(path ?? pathname);
    const img = absolute(image || DEFAULT_OG_IMAGE);

    document.title = fullTitle;
    setMeta("name", "description", desc);
    setMeta("name", "robots", noindex ? "noindex, follow" : "index, follow");
    setCanonical(url);

    setMeta("property", "og:title", fullTitle);
    setMeta("property", "og:description", desc);
    setMeta("property", "og:url", url);
    setMeta("property", "og:image", img);
    setMeta("property", "og:type", type);

    setMeta("name", "twitter:title", fullTitle);
    setMeta("name", "twitter:description", desc);
    setMeta("name", "twitter:image", img);
  }, [title, description, image, path, pathname, noindex, type]);
}
